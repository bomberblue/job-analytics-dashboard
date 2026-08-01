"""Unit tests for src/pipeline/data_cleaning.py."""
import unittest
import pandas as pd

from src.pipeline.data_cleaning import remove_ghost_rows, remove_synthetic_rows, prune_dead_columns


class TestRemoveGhostRows(unittest.TestCase):
    def test_drops_structurally_empty_rows(self):
        df = pd.DataFrame({
            'title': ['Engineer', None],
            'company': ['Acme', None],
            'salary_minimum': [3000, 0],
            'salary_maximum': [5000, 0],
        })
        result = remove_ghost_rows(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]['title'], 'Engineer')

    def test_keeps_partially_populated_rows(self):
        df = pd.DataFrame({
            'title': ['Engineer', None],
            'company': ['Acme', 'Beta'],
            'salary_minimum': [3000, 0],
            'salary_maximum': [5000, 0],
        })
        result = remove_ghost_rows(df)
        self.assertEqual(len(result), 2)


class TestRemoveSyntheticRows(unittest.TestCase):
    def test_drops_random_job_prefixed_ids(self):
        df = pd.DataFrame({
            'metadata_jobPostId': ['MCF-123', 'RANDOM_JOB_456', 'ATS-789'],
            'title': ['A', 'B', 'C'],
        })
        result = remove_synthetic_rows(df)
        self.assertEqual(sorted(result['metadata_jobPostId']), ['ATS-789', 'MCF-123'])


class TestPruneDeadColumns(unittest.TestCase):
    def test_drops_empty_and_constant_columns(self):
        df = pd.DataFrame({
            'title': ['Engineer', 'Analyst'],
            'all_nan': [None, None],
            'all_blank': ['', '  '],
            'constant': ['Monthly', 'Monthly'],
        })
        result = prune_dead_columns(df)
        self.assertEqual(list(result.columns), ['title'])


if __name__ == '__main__':
    unittest.main()
