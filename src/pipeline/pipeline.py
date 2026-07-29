"""
Data pipeline orchestrator.
Coordinates the entire ETL process: extract, clean, transform, load.
"""
import json
import pandas as pd
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.pipeline.data_cleaner import DataCleaner
from src.pipeline.feature_engineer import FeatureEngineer
from src.database.database_manager import DatabaseManager
from src.database.schema import initialize_database
from config.settings import RAW_CSV_PATH, DATA_RAW


class DataPipeline:
    """Orchestrates the complete data pipeline with raw data layer."""
    
    def __init__(self):
        self.cleaner = DataCleaner()
        self.engineer = FeatureEngineer()
        self.db = DatabaseManager()
    
    @staticmethod
    def parse_primary_category(categories_json):
        """
        Pull the primary category name out of the raw 'categories' JSON string.

        A posting can carry several categories; the first is treated as primary so
        that every posting lands in exactly one sector.
        """
        if pd.isna(categories_json):
            return "Not Specified"

        text = str(categories_json).strip()
        if not text:
            return "Not Specified"

        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return "Not Specified"

        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list) or not parsed:
            return "Not Specified"

        primary = parsed[0]
        if not isinstance(primary, dict):
            return "Not Specified"

        return str(primary.get('category', '')).strip() or "Not Specified"

    def extract(self, csv_path: str = None, nrows: int = None) -> pd.DataFrame:
        """Extract data from CSV (raw, unmodified)."""
        if csv_path is None:
            csv_path = str(RAW_CSV_PATH)
        
        print(f"📥 Loading raw data from {csv_path}...")
        
        try:
            df = pd.read_csv(csv_path, nrows=nrows)
            print(f"✓ Loaded {len(df)} rows, {len(df.columns)} columns")
            
            # Keep the raw CSV columns intact for the raw layer.
            # Only add a few compatibility columns for downstream cleaning.
            print("🔄 Preparing columns for cleaning...")
            if 'salary_minimum' in df.columns and 'salary_maximum' in df.columns:
                df['salary'] = df.apply(lambda row: f"{row['salary_minimum']}-{row['salary_maximum']}", axis=1)
            
            if 'postedCompany_name' in df.columns:
                df['company'] = df['postedCompany_name']
            else:
                df['company'] = 'Unknown'
            
            if 'title' in df.columns:
                df['title'] = df['title']
            else:
                df['title'] = 'Unknown'
            
            if 'minimumYearsExperience' in df.columns:
                df['experience'] = df['minimumYearsExperience']
                df['min_years_experience'] = pd.to_numeric(
                    df['minimumYearsExperience'], errors='coerce'
                )
            else:
                df['experience'] = None
                df['min_years_experience'] = None

            # positionLevels is the site's own seniority field (Fresh/entry ...
            # Senior Management). It is already clean, so use it directly rather
            # than trying to infer seniority from free text.
            if 'positionLevels' in df.columns:
                df['position_level'] = (
                    df['positionLevels'].fillna('').astype(str).str.strip()
                    .replace('', 'Not Specified')
                )
            else:
                df['position_level'] = 'Not Specified'
            
            if 'employmentTypes' in df.columns:
                df['job_type'] = df['employmentTypes']
            else:
                df['job_type'] = None
            
            if 'metadata_newPostingDate' in df.columns:
                df['posting_date'] = df['metadata_newPostingDate']
            else:
                df['posting_date'] = None
            
            # 'categories' arrives as a JSON array string, e.g.
            #   [{"id":21,"category":"Information Technology"}]
            # Storing it verbatim produced thousands of distinct "sectors" (one per
            # combination), so parse out the primary category name instead.
            if 'categories' in df.columns:
                df['sector'] = df['categories'].apply(self.parse_primary_category)
            else:
                df['sector'] = 'Unknown'

            # Engagement and demand metadata. These are the columns the dashboard
            # needs for "how hard is this role to fill" and they were previously
            # dropped before reaching the jobs table.
            metadata_map = {
                'metadata_totalNumberOfView': 'views',
                'metadata_totalNumberJobApplication': 'applications',
                'numberOfVacancies': 'vacancies',
                'metadata_repostCount': 'repost_count',
            }
            for src, dest in metadata_map.items():
                df[dest] = pd.to_numeric(df[src], errors='coerce') if src in df.columns else None

            df['expiry_date'] = (
                pd.to_datetime(df['metadata_expiryDate'], errors='coerce')
                if 'metadata_expiryDate' in df.columns else pd.NaT
            )
            
            if 'description' not in df.columns:
                df['description'] = ''
            if 'skills' not in df.columns:
                df['skills'] = ''
            if 'location' not in df.columns:
                df['location'] = 'Singapore'
            if 'requirements' not in df.columns:
                df['requirements'] = ''
                
            print(f"✓ Prepared columns for cleaning")
            return df
        except FileNotFoundError:
            print(f"✗ File not found: {csv_path}")
            print(f"✓ Expected at: {RAW_CSV_PATH}")
            return None
    
    def load_raw(self, df: pd.DataFrame) -> bool:
        """Load raw, unprocessed data into raw_jobs_flat table."""
        print("\n📝 STAGE 1: Loading RAW data layer (for audit trail)...")
        self.db.insert_raw_jobs(df)
        return True
    
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and engineer features."""
        print("\n🧹 STAGE 2: Cleaning and transforming data...")
        df = self.cleaner.clean(df)
        df = self.engineer.engineer_features(df)
        return df
    
    def load_processed(self, df: pd.DataFrame) -> bool:
        """Load transformed data into processed tables (jobs, metrics)."""
        print("\n📤 STAGE 3: Loading PROCESSED data layer (denormalized for analytics)...")
        
        # Select relevant columns for jobs table
        jobs_columns = [
            'job_id', 'title', 'company', 'sector', 'location',
            'salary_min', 'salary_max', 'experience_level',
            'seniority_years', 'position_level', 'job_type', 'posting_date',
            'expiry_date', 'views', 'applications', 'vacancies', 'repost_count',
            'skills', 'description'
        ]

        # Filter to available columns
        available_cols = [col for col in jobs_columns if col in df.columns]
        missing = [col for col in jobs_columns if col not in df.columns]
        if missing:
            print(f"  ⚠ Dropped before the jobs table: {', '.join(missing)}")
        df_jobs = df[available_cols].copy()

        # Insert into database
        inserted = self.db.insert_jobs(df_jobs)
        if inserted == 0:
            print("✗ No rows loaded into processed layer")
            return False

        print("✅ Data successfully loaded into processed layer")
        return True
    
    def run(self, csv_path: str = None, nrows: int = None):
        """Run the complete pipeline with raw and processed layers."""
        print("\n" + "="*60)
        print("🚀 STARTING DATA PIPELINE (with Raw Data Layer)")
        print("="*60)
        
        # Initialize database
        initialize_database()
        
        # STAGE 1: Extract
        df = self.extract(csv_path, nrows)
        if df is None:
            print("✗ Pipeline failed at extraction")
            return False
        
        # STAGE 1.5: Load raw data (for audit trail)
        self.load_raw(df.copy())
        
        # STAGE 2: Transform
        df = self.transform(df)
        
        # STAGE 3: Load processed data
        success = self.load_processed(df)
        
        print("\n" + "="*60)
        if success:
            print("✅ PIPELINE COMPLETE - All layers loaded successfully")
            print("   Raw layer:       raw_jobs_flat (audit trail)")
            print("   Processed layer: jobs (analytical queries)")
        else:
            print("✗ PIPELINE FAILED")
        print("="*60 + "\n")
        
        return success


if __name__ == "__main__":
    pipeline = DataPipeline()
    pipeline.run()  # Load ALL rows from CSV
