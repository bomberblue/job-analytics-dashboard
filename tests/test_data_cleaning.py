"""Unit tests for src/pipeline/data_cleaning.py."""
import json
import unittest
import pandas as pd

from src.pipeline.data_cleaning import remove_ghost_rows, remove_synthetic_rows, prune_dead_columns, parse_dates, split_categories, fix_salaries, cap_experience


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


class TestParseDates(unittest.TestCase):
    def test_converts_to_datetime_losslessly(self):
        df = pd.DataFrame({
            'metadata_newPostingDate': ['2026-01-01'],
            'metadata_originalPostingDate': ['2026-01-01'],
            'metadata_expiryDate': ['2026-02-01'],
        })
        result = parse_dates(df)
        self.assertEqual(result['metadata_newPostingDate'].dtype.kind, 'M')

    def test_refuses_lossy_conversion(self):
        df = pd.DataFrame({
            'metadata_newPostingDate': ['not-a-date'],
            'metadata_originalPostingDate': ['2026-01-01'],
            'metadata_expiryDate': ['2026-02-01'],
        })
        with self.assertRaises(AssertionError):
            parse_dates(df)

    def test_handles_legitimate_nulls(self):
        df = pd.DataFrame({
            'metadata_newPostingDate': ['2026-01-01', None],
            'metadata_originalPostingDate': ['2026-01-01', None],
            'metadata_expiryDate': ['2026-02-01', None],
        })
        result = parse_dates(df)
        self.assertEqual(result['metadata_newPostingDate'].dtype.kind, 'M')
        self.assertTrue(pd.isna(result['metadata_newPostingDate'].iloc[1]))


class TestSplitCategories(unittest.TestCase):
    def test_explodes_categories_and_keeps_primary(self):
        df = pd.DataFrame({
            'metadata_jobPostId': ['MCF-1', 'MCF-2'],
            'categories': [
                json.dumps([{'id': 1, 'category': 'IT'}, {'id': 2, 'category': 'Engineering'}]),
                json.dumps([{'id': 3, 'category': 'Finance'}]),
            ],
        })
        cleaned, job_category = split_categories(df)
        self.assertEqual(cleaned['primary_category'].tolist(), ['IT', 'Finance'])
        self.assertEqual(cleaned['n_categories'].tolist(), [2, 1])
        self.assertEqual(len(job_category), 3)
        self.assertNotIn('categories', cleaned.columns)

    def test_handles_empty_categories_array(self):
        df = pd.DataFrame({
            'metadata_jobPostId': ['MCF-1', 'MCF-2'],
            'categories': [
                json.dumps([{'id': 1, 'category': 'IT'}]),
                json.dumps([]),
            ],
        })
        cleaned, job_category = split_categories(df)
        self.assertEqual(cleaned['primary_category'].tolist()[0], 'IT')
        self.assertTrue(pd.isna(cleaned['primary_category'].iloc[1]))
        self.assertEqual(cleaned['n_categories'].tolist(), [1, 0])
        self.assertEqual(len(job_category), 1)


class TestFixSalaries(unittest.TestCase):
    def _base_df(self, **overrides):
        base = {
            'salary_minimum': [1, 3000, 150000],
            'salary_maximum': [1, 5000, 200000],
            'employmentTypes': ['Full-time', 'Full-time', 'Full-time'],
        }
        base.update(overrides)
        return pd.DataFrame(base)

    def test_nulls_placeholder_salaries(self):
        result = fix_salaries(self._base_df())
        self.assertTrue(pd.isna(result.loc[0, 'salary_minimum']))
        self.assertEqual(result.loc[0, 'salary_flag'], 'undisclosed')

    def test_flags_but_keeps_outliers(self):
        result = fix_salaries(self._base_df())
        self.assertEqual(result.loc[2, 'salary_maximum'], 200000)
        self.assertEqual(result.loc[2, 'salary_flag'], 'outlier')

    def test_keeps_plausible_internship_stipend(self):
        df = pd.DataFrame({
            'salary_minimum': [350],
            'salary_maximum': [400],
            'employmentTypes': ['Internship/Attachment'],
        })
        result = fix_salaries(df)
        self.assertEqual(result.loc[0, 'salary_minimum'], 350)
        self.assertEqual(result.loc[0, 'salary_flag'], 'low_stipend')

    def test_ok_rows_keep_flag_ok(self):
        result = fix_salaries(self._base_df())
        self.assertEqual(result.loc[1, 'salary_flag'], 'ok')


class TestCapExperience(unittest.TestCase):
    def test_nulls_impossible_values_keeps_zero(self):
        df = pd.DataFrame({'minimumYearsExperience': [0, 5, 500]})
        result = cap_experience(df)
        self.assertEqual(result.loc[0, 'minimumYearsExperience'], 0)
        self.assertEqual(result.loc[1, 'minimumYearsExperience'], 5)
        self.assertTrue(pd.isna(result.loc[2, 'minimumYearsExperience']))


if __name__ == '__main__':
    unittest.main()
