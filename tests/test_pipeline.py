"""
Integration test for the data pipeline.
"""
import os
import tempfile
import unittest

import duckdb

from src.database.database_manager import DatabaseManager
from src.dashboard.hirer_data_loader import MARKET_COLUMNS
from src.pipeline.data_cleaning import clean_dataset
from src.pipeline.feature_enrichment import feature_enrichment, schema_report, JOBS_SCHEMA_COLUMNS
from tests.fixtures import two_row_raw_frame


class TestPipelineIntegration(unittest.TestCase):
    """clean_dataset() -> feature_enrichment() end to end, on the shared
    two_row_raw_frame() fixture (see tests/fixtures.py for why it needs 2 diverse rows).
    """

    def test_clean_and_enrich_produces_valid_schema(self):
        cleaned, job_category = clean_dataset(two_row_raw_frame())
        enriched = feature_enrichment(cleaned, job_category=job_category)

        check = schema_report(enriched)
        self.assertEqual(check['missing'], [])
        self.assertEqual(enriched.loc[0, 'company'], 'ACME')
        self.assertEqual(enriched.loc[0, 'sector'], 'Information Technology')
        self.assertEqual(enriched.loc[1, 'company'], 'BETA RETAIL')

    def test_insert_jobs_carries_every_column_hirer_view_reads(self):
        """Regression test for the jobs table silently dropping columns -- twice now
        (views/applications/job_type in 0952d53, then dup_group_id/salary_midpoint/
        salary_flag/listing_days/is_repost). insert_jobs() and JOBS_SCHEMA both need
        to carry every JOBS_SCHEMA_COLUMNS entry, and hirer_data_loader.MARKET_COLUMNS
        must stay a subset of it, or this same crash recurs.
        """
        cleaned, job_category = clean_dataset(two_row_raw_frame())
        enriched = feature_enrichment(cleaned, job_category=job_category)
        df_jobs = enriched[JOBS_SCHEMA_COLUMNS].copy()

        db = DatabaseManager()
        with tempfile.TemporaryDirectory() as tmp:
            db.db_path = os.path.join(tmp, 'test.duckdb')
            db.insert_jobs(df_jobs)

            conn = duckdb.connect(db.db_path, read_only=True)
            try:
                table_columns = set(conn.execute("PRAGMA table_info('jobs')").df()['name'])
                # Column existence alone passes even if the column is unlisted in
                # insert_jobs()'s column list and lands all-NULL -- how views,
                # applications and job_type went missing in 0952d53. Read the
                # values back too, not just PRAGMA table_info's column names.
                col_list = ', '.join(JOBS_SCHEMA_COLUMNS)
                stored = conn.execute(f"SELECT {col_list} FROM jobs").df()
            finally:
                conn.close()

        missing = [c for c in JOBS_SCHEMA_COLUMNS if c not in table_columns]
        self.assertEqual(missing, [])
        self.assertTrue(set(MARKET_COLUMNS).issubset(table_columns))

        # A column insert_jobs() forgot to list comes back all-NULL regardless of
        # what the source had. Compare against the source's own nullness instead of
        # asserting "never null" outright -- some columns (e.g. sub_sector) are
        # legitimately null for this fixture, and that's not the bug being guarded.
        dropped = [c for c in JOBS_SCHEMA_COLUMNS
                   if df_jobs[c].notna().any() and stored[c].isna().all()]
        self.assertEqual(dropped, [])


if __name__ == '__main__':
    unittest.main()
