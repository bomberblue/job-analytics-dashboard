"""
Data pipeline orchestrator.
Coordinates the entire ETL process: extract, clean, enrich, load.
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.pipeline.data_cleaning import clean_dataset, assert_no_dead_columns
from src.pipeline.feature_enrichment import feature_enrichment, JOBS_SCHEMA_COLUMNS
from src.pipeline.finance_feature_pipeline import materialize_finance_feature_tables
from src.database.database_manager import DatabaseManager
from src.database.schema import initialize_database
from config.settings import RAW_CSV_PATH, DATA_PROCESSED

ENRICHED_PARQUET_PATH = DATA_PROCESSED / "jobs_enriched.parquet"


class DataPipeline:
    """Orchestrates the complete data pipeline with raw and processed layers."""

    def __init__(self):
        self.db = DatabaseManager()

    def extract(self, csv_path: str = None, nrows: int = None) -> pd.DataFrame:
        """Extract data from CSV (raw, unmodified)."""
        if csv_path is None:
            csv_path = str(RAW_CSV_PATH)

        print(f"📥 Loading raw data from {csv_path}...")
        try:
            df = pd.read_csv(csv_path, nrows=nrows)
            print(f"✓ Loaded {len(df)} rows, {len(df.columns)} columns")
            return df
        except FileNotFoundError:
            print(f"✗ File not found: {csv_path}")
            return None

    def load_raw(self, df: pd.DataFrame) -> bool:
        """Load raw, unprocessed data into raw_jobs_flat table."""
        print("\n📝 STAGE 1: Loading RAW data layer (for audit trail)...")
        self.db.insert_raw_jobs(df)
        return True

    def load_processed(self, enriched: pd.DataFrame) -> bool:
        """Load the cleaned, enriched data into the processed jobs table."""
        print("\n📤 STAGE 3: Loading PROCESSED data layer (denormalized for analytics)...")
        df_jobs = enriched[JOBS_SCHEMA_COLUMNS].copy()
        inserted = self.db.insert_jobs(df_jobs)
        if inserted == 0:
            print("✗ No rows loaded into processed layer")
            return False
        print("✅ Data successfully loaded into processed layer")
        return True

    def save_parquet(self, enriched: pd.DataFrame, path: Path = ENRICHED_PARQUET_PATH) -> bool:
        """Write the enriched frame to parquet for downstream loads/analysis."""
        print(f"\n💾 Saving enriched data to {path}...")
        path.parent.mkdir(parents=True, exist_ok=True)
        enriched.to_parquet(path, index=False)
        print(f"✓ Wrote {len(enriched)} rows, {len(enriched.columns)} columns")
        return True

    def run(self, csv_path: str = None, nrows: int = None):
        """Run the complete pipeline with raw and processed layers."""
        print("\n" + "="*60)
        print("🚀 STARTING DATA PIPELINE (with Raw Data Layer)")
        print("="*60)

        initialize_database()

        df = self.extract(csv_path, nrows)
        if df is None:
            print("✗ Pipeline failed at extraction")
            return False

        self.load_raw(df.copy())

        print("\n🧹 STAGE 2: Cleaning and enriching data...")
        cleaned, job_category = clean_dataset(df)
        if nrows is None:
            # Only meaningful on the full dataset - see assert_no_dead_columns()'s
            # docstring for why a bounded/test extract must not run this check.
            assert_no_dead_columns(cleaned)
        enriched = feature_enrichment(cleaned, job_category=job_category)

        self.save_parquet(enriched)

        success = self.load_processed(enriched)
        finance_counts = None

        if success:
            print("\n💼 STAGE 4: Building finance workforce-cost feature tables...")
            finance_counts = materialize_finance_feature_tables(self.db.db_path)
            print(
                "✅ Finance feature tables ready: "
                f"finance_job_features={finance_counts['finance_job_features']:,}, "
                f"finance_industry_budget_risk={finance_counts['finance_industry_budget_risk']:,}, "
                "finance_permanent_contract_conversion_economics="
                f"{finance_counts['finance_permanent_contract_conversion_economics']:,}"
            )

        print("\n" + "="*60)
        if success:
            print("✅ PIPELINE COMPLETE - All layers loaded successfully")
            print("   Raw layer:       raw_jobs_flat (audit trail)")
            print("   Processed layer: jobs (analytical queries)")
            print("   Finance layer:   finance_* (cost & budget risk features)")
        else:
            print("✗ PIPELINE FAILED")
        print("="*60 + "\n")

        return success


if __name__ == "__main__":
    pipeline = DataPipeline()
    pipeline.run()  # Load ALL rows from CSV
