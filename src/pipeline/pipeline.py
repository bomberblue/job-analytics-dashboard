"""
Data pipeline orchestrator.
Coordinates the entire ETL process: extract, clean, transform, load.
"""
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
            else:
                df['experience'] = None
            
            if 'employmentTypes' in df.columns:
                df['job_type'] = df['employmentTypes']
            else:
                df['job_type'] = None
            
            if 'metadata_newPostingDate' in df.columns:
                df['posting_date'] = df['metadata_newPostingDate']
            else:
                df['posting_date'] = None
            
            if 'categories' in df.columns:
                df['sector'] = df['categories']
            else:
                df['sector'] = 'Unknown'
            
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
            'seniority_years', 'posting_date', 'skills',
            'description'
        ]
        
        # Filter to available columns
        available_cols = [col for col in jobs_columns if col in df.columns]
        df_jobs = df[available_cols].copy()
        
        # Insert into database
        self.db.insert_jobs(df_jobs)
        
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
