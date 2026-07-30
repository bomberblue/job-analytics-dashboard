"""
Market Overview board.
Standalone entry point: streamlit run src/dashboard/market_overview.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
from config.settings import STREAMLIT_CONFIG
from src.database.database_manager import DatabaseManager
from src.dashboard.utils import (
    create_metric_columns,
    format_currency,
    format_percentage,
    create_comparison_table,
)


def build_where_clause(sector=None, position_level=None):
    """Build a composable SQL WHERE clause from optional filters."""
    conditions = ["posting_date IS NOT NULL"]
    if sector:
        conditions.append(f"sector = '{sector}'")
    if position_level:
        conditions.append(f"position_level = '{position_level}'")
    return "WHERE " + " AND ".join(conditions)


def fetch_position_levels(db):
    """Return the 9 distinct position levels, for the filter dropdown."""
    df = db.query("SELECT DISTINCT position_level FROM jobs ORDER BY position_level")
    return df['position_level'].tolist()


def initialize_session():
    """Set up session state. Safe to call multiple times."""
    if 'db' not in st.session_state:
        st.session_state.db = DatabaseManager()


def render_filters(db):
    """Render the sector and position-level dropdowns.

    Returns (sector, position_level), each None if "All" is selected.
    """
    col1, col2 = st.columns(2)
    with col1:
        sector_choice = st.selectbox(
            "Sector:",
            ["All Sectors"] + db.get_sector_list(),
            key="mkt_sector"
        )
    with col2:
        level_choice = st.selectbox(
            "Position Level:",
            ["All Levels"] + fetch_position_levels(db),
            key="mkt_position_level"
        )
    sector = None if sector_choice == "All Sectors" else sector_choice
    position_level = None if level_choice == "All Levels" else level_choice
    return sector, position_level


def main():
    """Render the full Market Overview board."""
    initialize_session()
    db = st.session_state.db

    st.title("Market Overview")
    st.caption("What's happening in the Singapore job market")

    sector, position_level = render_filters(db)
    st.divider()

    # Sections are wired in here by Task 8, after each is built and tested on its own.


if __name__ == "__main__":
    st.set_page_config(**STREAMLIT_CONFIG)
    main()
