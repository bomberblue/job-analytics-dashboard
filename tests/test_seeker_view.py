"""
Unit tests for the Job Seeker board.
"""
import unittest
from pathlib import Path

from src.database.database_manager import DatabaseManager
from src.dashboard.seeker_view import _cached_seeker_metrics


class TestCachedSeekerMetricsSalaryBenchmarks(unittest.TestCase):
    """Regression coverage for the p25 column, which used to be computed
    (at real cost) and then silently dropped before it reached the rendered
    table."""

    def setUp(self):
        self.db = DatabaseManager()
        self.db_mod_time = Path(self.db.db_path).stat().st_mtime

    def test_p25_present_and_populated(self):
        metrics = _cached_seeker_metrics(self.db.db_path, self.db_mod_time, None, None)
        benchmarks = metrics['salary_benchmarks']
        self.assertIn('p25', benchmarks.columns)
        self.assertGreater(len(benchmarks), 0)
        self.assertTrue(benchmarks['p25'].notna().any())

    def test_salary_benchmarks_columns(self):
        metrics = _cached_seeker_metrics(self.db.db_path, self.db_mod_time, None, None)
        benchmarks = metrics['salary_benchmarks']
        self.assertEqual(
            set(benchmarks.columns),
            {'job_label', 'experience_level', 'p25', 'median_entry', 'median_max', 'p90', 'count_samples'}
        )

    def test_every_job_label_meets_minimum_sample_size(self):
        # The >=200 filter groups by job_label alone (summing across experience
        # levels), so an individual row's own count_samples can be under 200 -
        # check the grouped total, not each row.
        metrics = _cached_seeker_metrics(self.db.db_path, self.db_mod_time, None, None)
        benchmarks = metrics['salary_benchmarks']
        totals = benchmarks.groupby('job_label')['count_samples'].transform('sum')
        self.assertTrue((totals >= 200).all())

    def test_experience_level_filter_narrows_results(self):
        unfiltered = _cached_seeker_metrics(self.db.db_path, self.db_mod_time, None, None)
        filtered = _cached_seeker_metrics(self.db.db_path, self.db_mod_time, 'Senior', None)
        self.assertLessEqual(
            len(filtered['salary_benchmarks']), len(unfiltered['salary_benchmarks'])
        )
        if not filtered['salary_benchmarks'].empty:
            self.assertTrue((filtered['salary_benchmarks']['experience_level'] == 'Senior').all())


if __name__ == '__main__':
    unittest.main()
