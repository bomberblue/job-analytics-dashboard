"""
Unit tests for the Market Overview board.
"""
import unittest
from src.database.database_manager import DatabaseManager
from src.dashboard.market_overview import build_where_clause, fetch_position_levels


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


if __name__ == '__main__':
    unittest.main()
