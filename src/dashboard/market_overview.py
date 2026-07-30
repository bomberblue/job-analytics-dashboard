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


def fetch_headline_metrics(db, sector=None, position_level=None):
    """Return a 1-row DataFrame: total_postings, median_pay."""
    where = build_where_clause(sector, position_level)
    sql = f"""
        SELECT
            COUNT(*) AS total_postings,
            ROUND(MEDIAN((salary_min + salary_max) / 2.0)) AS median_pay
        FROM jobs
        {where}
    """
    return db.query(sql)


def fetch_industry_ranking(db, sector=None, position_level=None, limit=None):
    """Return industries ranked by posting count: columns sector, postings."""
    where = build_where_clause(sector, position_level)
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    sql = f"""
        SELECT sector, COUNT(*) AS postings
        FROM jobs
        {where}
        GROUP BY sector
        ORDER BY postings DESC
        {limit_clause}
    """
    return db.query(sql)


def render_headline(db, sector=None, position_level=None):
    """Render the headline metrics row."""
    metrics = fetch_headline_metrics(db, sector, position_level)
    top_industries = fetch_industry_ranking(db, sector, position_level, limit=3)

    if metrics.empty or metrics.iloc[0]['total_postings'] == 0:
        st.info("No postings match the current filters.")
        return

    row = metrics.iloc[0]
    top_industry_label = ", ".join(top_industries['sector'].tolist()) if not top_industries.empty else "N/A"

    create_metric_columns({
        "Total Postings": f"{int(row['total_postings']):,}",
        "Median Pay": format_currency(row['median_pay']),
        "Top Industries": top_industry_label,
    })


def fetch_industry_momentum(db, sector=None, position_level=None):
    """
    Return industries ranked by recent hiring momentum.

    "Recent" and "prior" are the 3 most recent distinct year-months present in the
    filtered data, and the 3 before that - picked from the data itself, not a
    hardcoded calendar cutoff, so a narrow filter's own data decides the window.
    recent_month_count/prior_month_count expose when a window has fewer than 3
    months (a narrow filter can have gaps), so a thin average isn't silently
    shown as a full one.
    """
    where = build_where_clause(sector, position_level)
    sql = f"""
        WITH monthly AS (
            SELECT
                sector,
                strftime(posting_date, '%Y-%m') AS ym,
                COUNT(*) AS postings
            FROM jobs
            {where}
            GROUP BY sector, ym
        ),
        all_months AS (
            SELECT DISTINCT ym FROM monthly ORDER BY ym DESC
        ),
        recent_months AS (
            SELECT ym FROM all_months LIMIT 3
        ),
        prior_months AS (
            SELECT ym FROM all_months LIMIT 3 OFFSET 3
        )
        SELECT
            m.sector,
            AVG(CASE WHEN m.ym IN (SELECT ym FROM recent_months) THEN m.postings END) AS recent_avg_monthly,
            AVG(CASE WHEN m.ym IN (SELECT ym FROM prior_months) THEN m.postings END) AS prior_avg_monthly,
            COUNT(DISTINCT CASE WHEN m.ym IN (SELECT ym FROM recent_months) THEN m.ym END) AS recent_month_count,
            COUNT(DISTINCT CASE WHEN m.ym IN (SELECT ym FROM prior_months) THEN m.ym END) AS prior_month_count
        FROM monthly m
        WHERE m.ym IN (SELECT ym FROM recent_months) OR m.ym IN (SELECT ym FROM prior_months)
        GROUP BY m.sector
    """
    df = db.query(sql)

    def pct_change(row):
        if pd.isna(row['prior_avg_monthly']) or row['prior_avg_monthly'] == 0:
            return None
        return round(100 * (row['recent_avg_monthly'] - row['prior_avg_monthly']) / row['prior_avg_monthly'], 1)

    df['pct_change'] = df.apply(pct_change, axis=1)
    return df.sort_values('pct_change', ascending=False, na_position='last').reset_index(drop=True)


def render_industry_momentum(db, sector=None, position_level=None):
    """Render the industries growing/slowing table."""
    df = fetch_industry_momentum(db, sector, position_level)
    st.subheader("Industries: Growing vs. Slowing")
    if df.empty:
        st.info("No postings match the current filters.")
        return
    display_df = df.copy()
    display_df['pct_change'] = display_df['pct_change'].apply(format_percentage)
    create_comparison_table(
        display_df,
        columns_to_show=[
            'sector', 'recent_avg_monthly', 'prior_avg_monthly', 'pct_change',
            'recent_month_count', 'prior_month_count',
        ]
    )


def fetch_salary_trend(db, sector=None, position_level=None):
    """Return median pay by month: columns month ('YYYY-MM'), median_pay."""
    where = build_where_clause(sector, position_level)
    sql = f"""
        SELECT
            strftime(posting_date, '%Y-%m') AS month,
            ROUND(MEDIAN((salary_min + salary_max) / 2.0)) AS median_pay
        FROM jobs
        {where}
        GROUP BY month
        ORDER BY month
    """
    return db.query(sql)


def render_salary_trend(db, sector=None, position_level=None):
    """Render the salary trend line chart."""
    df = fetch_salary_trend(db, sector, position_level)
    st.subheader("Salary Trend")
    if df.empty:
        st.info("No postings match the current filters.")
        return
    st.caption(f"Median pay by month, {df['month'].iloc[0]} - {df['month'].iloc[-1]}")
    st.line_chart(df.set_index('month')['median_pay'], use_container_width=True)


def fetch_position_level_ranking(db, sector=None, position_level=None):
    """Return position levels ranked by posting count: columns position_level, postings."""
    where = build_where_clause(sector, position_level)
    sql = f"""
        SELECT position_level, COUNT(*) AS postings
        FROM jobs
        {where}
        GROUP BY position_level
        ORDER BY postings DESC
    """
    return db.query(sql)


def render_category_rankings(db, sector=None, position_level=None):
    """Render the two ranked bar charts: industries and position levels."""
    industries = fetch_industry_ranking(db, sector, position_level, limit=None)
    levels = fetch_position_level_ranking(db, sector, position_level)

    st.subheader("Top Categories by Openings")
    col1, col2 = st.columns(2)
    with col1:
        st.caption("By industry")
        if industries.empty:
            st.info("No postings match the current filters.")
        else:
            st.bar_chart(industries.set_index('sector')['postings'], use_container_width=True)
    with col2:
        st.caption("By position level")
        if levels.empty:
            st.info("No postings match the current filters.")
        else:
            st.bar_chart(levels.set_index('position_level')['postings'], use_container_width=True)


_MONTH_NAMES = [
    None, "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
]


def fetch_seasonality(db, sector=None, position_level=None):
    """
    Return average postings per calendar month.

    Groups by (year, month) first, then averages across years per calendar month -
    not a naive group-by-month-only, which would overweight months that appear in
    more years. years_included/total_postings expose the sample behind each bar
    (e.g. October blends a near-empty Oct 2022 with a full Oct 2023) instead of
    hiding it.
    """
    where = build_where_clause(sector, position_level)
    sql = f"""
        WITH monthly AS (
            SELECT
                strftime(posting_date, '%Y') AS yr,
                EXTRACT(MONTH FROM posting_date)::INTEGER AS month_num,
                COUNT(*) AS postings
            FROM jobs
            {where}
            GROUP BY yr, month_num
        )
        SELECT
            month_num,
            ROUND(AVG(postings)) AS avg_postings,
            COUNT(DISTINCT yr) AS years_included,
            SUM(postings) AS total_postings
        FROM monthly
        GROUP BY month_num
        ORDER BY month_num
    """
    df = db.query(sql)
    df['month_name'] = df['month_num'].apply(lambda n: _MONTH_NAMES[n])
    return df[['month_num', 'month_name', 'avg_postings', 'years_included', 'total_postings']]


def render_seasonality(db, sector=None, position_level=None):
    """Render the seasonality bar chart, plus the sample-size breakdown beneath it."""
    df = fetch_seasonality(db, sector, position_level)
    st.subheader("Seasonality")
    if df.empty:
        st.info("No postings match the current filters.")
        return
    st.bar_chart(df.set_index('month_name')['avg_postings'], use_container_width=True)
    st.caption("Years and total postings behind each bar (a thin sample, like a month covered by only one partial year, will read as unreliable):")
    create_comparison_table(
        df,
        columns_to_show=['month_name', 'years_included', 'total_postings']
    )


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
