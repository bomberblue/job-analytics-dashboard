"""Shared test fixtures for the data-cleaning pipeline tests."""
import json

import pandas as pd


def two_row_raw_frame():
    """A 2-row raw-CSV-shaped DataFrame for exercising clean_dataset()/feature_enrichment().

    Uses 2 rows with a distinct value in every column (except the two intentionally dead
    ones, occupationId and salary_type) rather than 1 - prune_dead_columns() drops any
    column with <= 1 distinct value across the frame, and with a single row EVERY column
    trivially qualifies, which would strip columns the rest of the pipeline needs and
    crash with a KeyError downstream, not just fail an assertion.

    Callers should not expect assert_no_dead_columns() to pass against the result - even
    2 diverse rows can coincidentally collide on a derived column like `source` (both rows
    here use an MCF- job id), which is a sample-size artifact, not a bug. See
    TestValidateDeadColumns in test_data_cleaning.py, which tests that specific check in
    isolation with a fixture built to exercise it correctly.
    """
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
