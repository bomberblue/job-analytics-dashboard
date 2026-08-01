"""
Integration test for the data pipeline.
"""
import unittest

from src.pipeline.data_cleaning import clean_dataset
from src.pipeline.feature_enrichment import feature_enrichment, schema_report
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


if __name__ == '__main__':
    unittest.main()
