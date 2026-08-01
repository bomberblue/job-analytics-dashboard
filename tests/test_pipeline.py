"""
Integration test for the data pipeline.
"""
import unittest
import pandas as pd
import json

from src.pipeline.data_cleaning import clean_dataset
from src.pipeline.feature_enrichment import feature_enrichment, schema_report


class TestPipelineIntegration(unittest.TestCase):
    """clean_dataset() -> feature_enrichment() end to end, on a tiny synthetic frame.

    Uses 2 rows with a distinct value in every column (except the two intentionally
    dead ones) rather than 1 - prune_dead_columns() drops any column with <= 1 distinct
    value across the frame, and with a single row EVERY column trivially qualifies,
    which would strip columns the rest of the pipeline needs and crash with a KeyError
    downstream, not just fail an assertion. See TestCleanDataset's docstring in
    tests/test_data_cleaning.py for the same reasoning. check_dead_columns=False is
    passed for the same reason it's passed there: even 2 diverse rows can still
    coincidentally collide on a derived column like `source`.
    """

    def _raw_frame(self):
        return pd.DataFrame([
            {
                'metadata_jobPostId': 'MCF-1', 'title': 'Data Engineer',
                'postedCompany_name': 'ACME', 'salary_minimum': 4000, 'salary_maximum': 6000,
                'employmentTypes': 'Full-time', 'positionLevels': 'Senior',
                'categories': json.dumps([{'id': 1, 'category': 'Information Technology'}]),
                'metadata_newPostingDate': '2026-01-01', 'metadata_originalPostingDate': '2026-01-01',
                'metadata_expiryDate': '2026-02-01',
                'minimumYearsExperience': 5, 'metadata_repostCount': 0, 'numberOfVacancies': 1,
                'metadata_totalNumberOfView': 10, 'metadata_totalNumberJobApplication': 1,
                'status_jobStatus': 'Open', 'occupationId': None, 'salary_type': 'Monthly',
            },
            {
                'metadata_jobPostId': 'MCF-2', 'title': 'Retail Assistant',
                'postedCompany_name': 'BETA RETAIL', 'salary_minimum': 2000, 'salary_maximum': 2800,
                'employmentTypes': 'Part-time', 'positionLevels': 'Entry',
                'categories': json.dumps([{'id': 2, 'category': 'Retail'}]),
                'metadata_newPostingDate': '2026-01-10', 'metadata_originalPostingDate': '2026-01-10',
                'metadata_expiryDate': '2026-02-15',
                'minimumYearsExperience': 0, 'metadata_repostCount': 1, 'numberOfVacancies': 2,
                'metadata_totalNumberOfView': 8, 'metadata_totalNumberJobApplication': 0,
                'status_jobStatus': 'Closed', 'occupationId': None, 'salary_type': 'Monthly',
            },
        ])

    def test_clean_and_enrich_produces_valid_schema(self):
        cleaned, job_category = clean_dataset(self._raw_frame(), check_dead_columns=False)
        enriched = feature_enrichment(cleaned, job_category=job_category)

        check = schema_report(enriched)
        self.assertEqual(check['missing'], [])
        self.assertEqual(enriched.loc[0, 'company'], 'ACME')
        self.assertEqual(enriched.loc[0, 'sector'], 'Information Technology')
        self.assertEqual(enriched.loc[1, 'company'], 'BETA RETAIL')


if __name__ == '__main__':
    unittest.main()
