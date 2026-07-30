"""
Unit tests for the Market Overview board.
"""
import unittest
from src.database.database_manager import DatabaseManager
from src.dashboard.market_overview import build_where_clause, fetch_position_levels, fetch_headline_metrics, fetch_industry_ranking, fetch_industry_momentum, fetch_salary_trend, fetch_position_level_ranking, fetch_seasonality


class TestBuildWhereClause(unittest.TestCase):
    """Test the shared filter-clause builder."""

    def test_no_filters(self):
        self.assertEqual(build_where_clause(), "WHERE posting_date IS NOT NULL")

    def test_sector_only(self):
        self.assertEqual(
            build_where_clause(sector="Information Technology"),
            "WHERE posting_date IS NOT NULL AND sector = 'Information Technology'"
        )

    def test_both_filters(self):
        self.assertEqual(
            build_where_clause(sector="Information Technology", position_level="Executive"),
            "WHERE posting_date IS NOT NULL AND sector = 'Information Technology' AND position_level = 'Executive'"
        )


class TestFetchPositionLevels(unittest.TestCase):
    """Test the position-level dropdown source."""

    def setUp(self):
        self.db = DatabaseManager()

    def test_returns_all_nine_levels(self):
        levels = fetch_position_levels(self.db)
        self.assertEqual(len(levels), 9)
        self.assertIn("Executive", levels)


class TestFetchHeadlineMetrics(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_unfiltered_shape(self):
        df = fetch_headline_metrics(self.db)
        self.assertEqual(list(df.columns), ['total_postings', 'median_pay'])
        self.assertEqual(len(df), 1)
        self.assertGreater(df.iloc[0]['total_postings'], 0)
        self.assertLessEqual(df.iloc[0]['total_postings'], 1026079)
        self.assertGreater(df.iloc[0]['median_pay'], 0)


class TestFetchIndustryRanking(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_limit_respected(self):
        df = fetch_industry_ranking(self.db, limit=3)
        self.assertLessEqual(len(df), 3)

    def test_sorted_descending(self):
        df = fetch_industry_ranking(self.db)
        postings = df['postings'].tolist()
        self.assertEqual(postings, sorted(postings, reverse=True))

    def test_unfiltered_returns_all_43_sectors(self):
        df = fetch_industry_ranking(self.db)
        self.assertEqual(len(df), 43)


class TestFetchIndustryMomentum(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_unfiltered_shape(self):
        df = fetch_industry_momentum(self.db)
        expected_cols = {
            'sector', 'recent_avg_monthly', 'prior_avg_monthly',
            'recent_month_count', 'prior_month_count', 'pct_change'
        }
        self.assertEqual(set(df.columns), expected_cols)
        self.assertGreater(len(df), 0)

    def test_month_counts_capped_at_three(self):
        df = fetch_industry_momentum(self.db)
        self.assertTrue((df['recent_month_count'] <= 3).all())
        self.assertTrue((df['prior_month_count'] <= 3).all())


class TestFetchSalaryTrend(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_unfiltered_shape_and_order(self):
        df = fetch_salary_trend(self.db)
        self.assertEqual(list(df.columns), ['month', 'median_pay'])
        self.assertGreater(len(df), 0)
        months = df['month'].tolist()
        self.assertEqual(months, sorted(months))


class TestFetchPositionLevelRanking(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_returns_all_nine_levels_sorted_descending(self):
        df = fetch_position_level_ranking(self.db)
        self.assertEqual(len(df), 9)
        postings = df['postings'].tolist()
        self.assertEqual(postings, sorted(postings, reverse=True))


class TestFetchSeasonality(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_twelve_months_in_calendar_order(self):
        df = fetch_seasonality(self.db)
        self.assertEqual(len(df), 12)
        self.assertEqual(df['month_num'].tolist(), list(range(1, 13)))

    def test_years_included_reflects_data_coverage(self):
        df = fetch_seasonality(self.db)
        # Under the Oct 2022 - May 2024 range, June-September only occur in one
        # year (2023); October-May occur in two (2022/2023 or 2023/2024).
        self.assertTrue((df['years_included'] >= 1).all())
        self.assertTrue((df['years_included'] <= 2).all())


if __name__ == '__main__':
    unittest.main()
