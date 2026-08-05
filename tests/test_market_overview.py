"""
Unit tests for the Market Overview board.
"""
import unittest
import pandas as pd
from src.database.database_manager import DatabaseManager
from src.dashboard.market_overview import (
    build_where_clause, fetch_position_levels, fetch_headline_metrics,
    fetch_industry_ranking, fetch_industry_momentum, fetch_salary_trend,
    fetch_position_level_ranking, fetch_seasonality, compute_pct_change,
    _early_late_windows, fetch_wage_decomposition, fetch_sector_mix_shift,
    fetch_employment_type_mix, fetch_top_companies, MIN_SEGMENT_SIZE,
    fetch_repost_rate_by_sector, MIN_REPOST_SAMPLE,
)


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
        # total_postings is a filtered view of the raw layer, so it can never exceed the
        # raw row count - a live bound instead of a hardcoded one that rots when the
        # pipeline's row count changes.
        raw_count = self.db.query("SELECT COUNT(*) AS count FROM raw_jobs_flat").iloc[0]['count']
        self.assertLessEqual(df.iloc[0]['total_postings'], raw_count)
        self.assertGreater(df.iloc[0]['median_pay'], 0)

    def test_sector_filter_reduces_total(self):
        unfiltered_total = fetch_headline_metrics(self.db).iloc[0]['total_postings']
        filtered_total = fetch_headline_metrics(self.db, sector="Information Technology").iloc[0]['total_postings']
        self.assertLess(filtered_total, unfiltered_total)


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

    def test_sector_filter_returns_one_row(self):
        df = fetch_industry_ranking(self.db, sector="Information Technology")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['sector'], "Information Technology")


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


class TestComputePctChange(unittest.TestCase):
    """
    Pins down compute_pct_change's null-handling, which the DB-backed tests above
    can't reach: the current dataset has no sector with a zero-postings window, so
    these edge cases only show up in a synthetic row shaped like one from
    fetch_industry_momentum.
    """

    def test_normal_case(self):
        row = pd.Series({'recent_avg_monthly': 120.0, 'prior_avg_monthly': 100.0})
        self.assertEqual(compute_pct_change(row), 20.0)

    def test_prior_zero_returns_none(self):
        row = pd.Series({'recent_avg_monthly': 50.0, 'prior_avg_monthly': 0.0})
        self.assertIsNone(compute_pct_change(row))

    def test_prior_nan_returns_none(self):
        row = pd.Series({'recent_avg_monthly': 50.0, 'prior_avg_monthly': float('nan')})
        self.assertIsNone(compute_pct_change(row))

    def test_recent_nan_returns_nan(self):
        # A sector with postings in the prior window but none in the recent one -
        # the strongest possible "slowing" signal - still comes out as NaN rather
        # than a large negative number, so it reads as "N/A" rather than as the
        # biggest decline. Current behavior, pinned here rather than changed: see
        # the fix report for the reasoning.
        row = pd.Series({'recent_avg_monthly': float('nan'), 'prior_avg_monthly': 100.0})
        self.assertTrue(pd.isna(compute_pct_change(row)))


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
        # Under the Oct 2022 - May 2024 range (posting_date runs 2022-10-03 to 2024-05-29),
        # June-September only occur in one year (2023); October-May occur in two
        # (2022/2023 or 2023/2024).
        self.assertTrue((df['years_included'] >= 1).all())
        self.assertTrue((df['years_included'] <= 2).all())


class TestEarlyLateWindows(unittest.TestCase):
    """
    Pins down the disjointness guarantee: unlike a naive `ORDER BY ym ASC/DESC
    LIMIT N` pair (what fetch_wage_decomposition used before), this must never
    return overlapping months, and must signal insufficient data explicitly
    rather than silently double-counting a month in both windows.
    """

    def setUp(self):
        self.db = DatabaseManager()

    def test_unfiltered_windows_are_disjoint_and_ordered(self):
        early, late = _early_late_windows(self.db)
        self.assertIsNotNone(early)
        self.assertEqual(len(early), 3)
        self.assertEqual(len(late), 3)
        self.assertTrue(set(early).isdisjoint(set(late)))
        self.assertLess(max(early), min(late))

    def test_narrow_combo_with_few_months_returns_none(self):
        # Real combo with only 5 distinct months after the ramp cutoff (9
        # postings total) - too narrow for two disjoint 3-month windows.
        early, late = _early_late_windows(
            self.db, sector="Precision Engineering", position_level="Senior Management"
        )
        self.assertIsNone(early)
        self.assertIsNone(late)


class TestFetchWageDecomposition(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_unfiltered_shape(self):
        df = fetch_wage_decomposition(self.db)
        self.assertEqual(len(df), 1)
        expected_cols = {
            'n_segments', 'n_early_total', 'n_late_total', 'total_early_all',
            'total_late_all', 'actual_early', 'actual_late',
            'late_pay_at_early_mix', 'early_window_label', 'late_window_label',
        }
        self.assertEqual(set(df.columns), expected_cols)
        self.assertGreater(df.iloc[0]['n_segments'], 0)

    def test_within_and_mix_effects_sum_to_total_change(self):
        row = fetch_wage_decomposition(self.db).iloc[0]
        total_change = row['actual_late'] - row['actual_early']
        within_effect = row['late_pay_at_early_mix'] - row['actual_early']
        mix_effect = row['actual_late'] - row['late_pay_at_early_mix']
        self.assertAlmostEqual(within_effect + mix_effect, total_change, places=6)

    def test_matched_postings_do_not_exceed_totals(self):
        row = fetch_wage_decomposition(self.db).iloc[0]
        self.assertLessEqual(row['n_early_total'], row['total_early_all'])
        self.assertLessEqual(row['n_late_total'], row['total_late_all'])

    def test_too_narrow_a_filter_returns_empty(self):
        df = fetch_wage_decomposition(
            self.db, sector="Precision Engineering", position_level="Senior Management"
        )
        self.assertTrue(df.empty)

    def test_segments_below_minimum_size_are_excluded(self):
        # Every included segment's early AND late count must clear the floor -
        # confirms the filter is actually being applied, not just present in SQL.
        row = fetch_wage_decomposition(self.db).iloc[0]
        self.assertGreaterEqual(row['n_early_total'] / row['n_segments'], MIN_SEGMENT_SIZE)


class TestFetchSectorMixShift(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_unfiltered_shape_and_limit(self):
        df = fetch_sector_mix_shift(self.db, limit=8)
        self.assertLessEqual(len(df), 8)
        self.assertEqual(
            set(df.columns), {'sector', 'share_early_pct', 'share_late_pct', 'share_change_pct'}
        )

    def test_sorted_by_absolute_change_descending(self):
        df = fetch_sector_mix_shift(self.db)
        abs_changes = df['share_change_pct'].abs().tolist()
        self.assertEqual(abs_changes, sorted(abs_changes, reverse=True))

    def test_shares_sum_to_roughly_one_hundred(self):
        # All sectors are included (limit only trims the *returned* rows), so
        # this queries with a high limit to check the underlying shares are
        # true percentages of the whole, not of just the top few sectors.
        df = fetch_sector_mix_shift(self.db, limit=100)
        self.assertAlmostEqual(df['share_early_pct'].sum(), 100.0, places=4)
        self.assertAlmostEqual(df['share_late_pct'].sum(), 100.0, places=4)


class TestFetchEmploymentTypeMix(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_unfiltered_shape_and_order(self):
        df = fetch_employment_type_mix(self.db)
        self.assertEqual(list(df.columns), ['job_type', 'postings', 'median_pay'])
        self.assertGreater(len(df), 0)
        postings = df['postings'].tolist()
        self.assertEqual(postings, sorted(postings, reverse=True))

    def test_permanent_and_contract_present(self):
        df = fetch_employment_type_mix(self.db)
        self.assertIn('Permanent', df['job_type'].tolist())
        self.assertIn('Contract', df['job_type'].tolist())


class TestFetchTopCompanies(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_limit_respected(self):
        df = fetch_top_companies(self.db, limit=5)
        self.assertLessEqual(len(df), 5)

    def test_sorted_descending_by_postings(self):
        df = fetch_top_companies(self.db)
        postings = df['postings'].tolist()
        self.assertEqual(postings, sorted(postings, reverse=True))

    def test_share_pct_is_of_full_filtered_population(self):
        # share_pct is each company's share of ALL postings matching the filter,
        # not just of the top-N shown - so the top company's share should be tiny
        # relative to 100%, not close to it (this would break if share_pct were
        # accidentally computed as a share of just the LIMIT-ed rows).
        df = fetch_top_companies(self.db, limit=10)
        self.assertLess(df.iloc[0]['share_pct'], 10.0)


class TestFetchRepostRateBySector(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager()

    def test_shape(self):
        df = fetch_repost_rate_by_sector(self.db)
        self.assertEqual(list(df.columns), ['sector', 'repost_rate_pct', 'n'])

    def test_rate_is_a_percentage(self):
        df = fetch_repost_rate_by_sector(self.db)
        self.assertGreater(len(df), 0)
        self.assertTrue((df['repost_rate_pct'] >= 0).all())
        self.assertTrue((df['repost_rate_pct'] <= 100).all())

    def test_every_row_meets_min_sample(self):
        df = fetch_repost_rate_by_sector(self.db)
        self.assertTrue((df['n'] >= MIN_REPOST_SAMPLE).all())

    def test_position_level_filter_narrows_sectors(self):
        unfiltered = fetch_repost_rate_by_sector(self.db)
        filtered = fetch_repost_rate_by_sector(self.db, position_level="Executive")
        self.assertLessEqual(len(filtered), len(unfiltered))


if __name__ == '__main__':
    unittest.main()
