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
    df['pct_change'] = df.apply(compute_pct_change, axis=1)
    return df.sort_values('pct_change', ascending=False, na_position='last').reset_index(drop=True)


def compute_pct_change(row):
    """
    Percent change from prior_avg_monthly to recent_avg_monthly for one row of
    fetch_industry_momentum's output. None when prior_avg_monthly is 0 or missing
    (can't compute a percent change off a zero or absent base), including when
    recent_avg_monthly is also missing.
    """
    if pd.isna(row['prior_avg_monthly']) or row['prior_avg_monthly'] == 0:
        return None
    return round(100 * (row['recent_avg_monthly'] - row['prior_avg_monthly']) / row['prior_avg_monthly'], 1)


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
            # industries is already ORDER BY postings DESC; pin that as the
            # chart's category order, or Vega-Lite defaults to alphabetical.
            industries['sector'] = pd.Categorical(
                industries['sector'], categories=industries['sector'], ordered=True
            )
            st.bar_chart(industries.set_index('sector')['postings'], use_container_width=True)
    with col2:
        st.caption("By position level")
        if levels.empty:
            st.info("No postings match the current filters.")
        else:
            levels['position_level'] = pd.Categorical(
                levels['position_level'], categories=levels['position_level'], ordered=True
            )
            st.bar_chart(levels.set_index('position_level')['postings'], use_container_width=True)


def fetch_employment_type_mix(db, sector=None, position_level=None):
    """Return job types ranked by posting count, with median pay for each:
    columns job_type, postings, median_pay."""
    where = build_where_clause(sector, position_level)
    sql = f"""
        SELECT
            job_type,
            COUNT(*) AS postings,
            ROUND(MEDIAN((salary_min + salary_max) / 2.0)) AS median_pay
        FROM jobs
        {where} AND job_type IS NOT NULL
        GROUP BY job_type
        ORDER BY postings DESC
    """
    return db.query(sql)


def render_employment_type_mix(db, sector=None, position_level=None):
    """Render the employment type breakdown: volume and median pay per type."""
    df = fetch_employment_type_mix(db, sector, position_level)
    st.subheader("Employment Type Mix")
    if df.empty:
        st.info("No postings match the current filters.")
        return

    # Pin postings-desc as the shared category order for both charts, or
    # Vega-Lite defaults to alphabetical (matches render_category_rankings).
    df['job_type'] = pd.Categorical(df['job_type'], categories=df['job_type'], ordered=True)

    col1, col2 = st.columns(2)
    with col1:
        st.caption("By postings")
        st.bar_chart(df.set_index('job_type')['postings'], use_container_width=True)
    with col2:
        st.caption("By median pay")
        st.bar_chart(df.set_index('job_type')['median_pay'], use_container_width=True)


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
    df['month_name'] = pd.Categorical(
        df['month_num'].apply(lambda n: _MONTH_NAMES[n]),
        categories=_MONTH_NAMES[1:],
        ordered=True
    )
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


# Postings before this date are the platform's early onboarding ramp (Oct 2022 -
# Feb 2023 averaged under 6k postings/month platform-wide, vs 19k+ from March 2023
# on). Left in, that ramp would be mistaken for a real early-period baseline by
# any analysis comparing an early window to a later one.
WAGE_DECOMPOSITION_START_DATE = '2023-03-01'

# Minimum postings a sector/position-level segment needs in BOTH the early and
# late window to be included, so a handful of rare segments can't swing the total.
MIN_SEGMENT_SIZE = 50


def _ramp_excluded_where(sector=None, position_level=None):
    """build_where_clause's filters, plus the onboarding ramp excluded."""
    return build_where_clause(sector, position_level) + \
        f" AND posting_date >= '{WAGE_DECOMPOSITION_START_DATE}'"


def fetch_wage_decomposition(db, sector=None, position_level=None):
    """
    Split the pay change between the earliest and latest 3 months of data into
    two parts: real wage growth within the same sector/position-level segments
    (the "within" effect), versus the market simply posting more of its higher-
    or lower-paying segments (the "mix" effect).

    Method: hold segment weights fixed at the early window's mix, and price
    them at the late window's pay rates ("late_pay_at_early_mix"). The gap from
    actual_early to that bridge value is pure wage movement; the gap from the
    bridge value to actual_late is pure mix movement. The two always sum
    exactly to the headline change.
    """
    where = _ramp_excluded_where(sector, position_level)
    sql = f"""
        WITH filtered AS (
            SELECT sector, position_level, strftime(posting_date, '%Y-%m') AS ym,
                   (salary_min + salary_max) / 2.0 AS pay
            FROM jobs
            {where}
        ),
        all_months AS (SELECT DISTINCT ym FROM filtered),
        early_months AS (SELECT ym FROM all_months ORDER BY ym ASC LIMIT 3),
        late_months AS (SELECT ym FROM all_months ORDER BY ym DESC LIMIT 3),
        segment AS (
            SELECT
                sector, position_level,
                AVG(pay) FILTER (WHERE ym IN (SELECT ym FROM early_months)) AS pay_early,
                AVG(pay) FILTER (WHERE ym IN (SELECT ym FROM late_months))  AS pay_late,
                COUNT(*) FILTER (WHERE ym IN (SELECT ym FROM early_months)) AS n_early,
                COUNT(*) FILTER (WHERE ym IN (SELECT ym FROM late_months))  AS n_late
            FROM filtered
            GROUP BY sector, position_level
        ),
        valid AS (
            SELECT * FROM segment
            WHERE n_early >= {MIN_SEGMENT_SIZE} AND n_late >= {MIN_SEGMENT_SIZE}
        )
        SELECT
            (SELECT MIN(ym) FROM early_months) || ' to ' || (SELECT MAX(ym) FROM early_months) AS early_window_label,
            (SELECT MIN(ym) FROM late_months)  || ' to ' || (SELECT MAX(ym) FROM late_months)  AS late_window_label,
            COUNT(*)::INTEGER AS n_segments,
            SUM(n_early)::INTEGER AS n_early_total,
            SUM(n_late)::INTEGER AS n_late_total,
            SUM(pay_early * n_early) / NULLIF(SUM(n_early), 0) AS actual_early,
            SUM(pay_late  * n_late)  / NULLIF(SUM(n_late), 0)  AS actual_late,
            SUM(pay_late  * n_early) / NULLIF(SUM(n_early), 0) AS late_pay_at_early_mix
        FROM valid
    """
    return db.query(sql)


def fetch_sector_mix_shift(db, position_level=None, limit=8):
    """
    Return the sectors whose share of postings changed the most between the
    early and late windows used by fetch_wage_decomposition. This is the detail
    behind that function's "mix effect": a sector gaining share pulls overall
    pay toward its own pay level even when nobody's individual wage moved.
    """
    where = _ramp_excluded_where(sector=None, position_level=position_level)
    sql = f"""
        WITH filtered AS (
            SELECT sector, strftime(posting_date, '%Y-%m') AS ym
            FROM jobs
            {where}
        ),
        all_months AS (SELECT DISTINCT ym FROM filtered),
        early_months AS (SELECT ym FROM all_months ORDER BY ym ASC LIMIT 3),
        late_months AS (SELECT ym FROM all_months ORDER BY ym DESC LIMIT 3),
        totals AS (
            SELECT
                COUNT(*) FILTER (WHERE ym IN (SELECT ym FROM early_months)) AS total_early,
                COUNT(*) FILTER (WHERE ym IN (SELECT ym FROM late_months))  AS total_late
            FROM filtered
        )
        SELECT
            sector,
            COUNT(*) FILTER (WHERE ym IN (SELECT ym FROM early_months)) * 100.0
                / NULLIF((SELECT total_early FROM totals), 0) AS share_early_pct,
            COUNT(*) FILTER (WHERE ym IN (SELECT ym FROM late_months)) * 100.0
                / NULLIF((SELECT total_late FROM totals), 0) AS share_late_pct
        FROM filtered
        GROUP BY sector
    """
    df = db.query(sql)
    if df.empty:
        return df
    df['share_change_pct'] = df['share_late_pct'] - df['share_early_pct']
    return (
        df.reindex(df['share_change_pct'].abs().sort_values(ascending=False).index)
        .head(limit)
        .reset_index(drop=True)
    )


# Keyword match on company name, used only to flag likely staffing/recruitment
# agencies for the concentration caveat below - not a verified employer registry,
# so treat matches as "looks like an agency," not a confirmed classification.
_AGENCY_NAME_PATTERN = (
    r'RECRUIT|STAFFING|MANPOWER|\bHR\b|HUMAN RESOURCE|TALENT|CONSULTANC|'
    r'EMPLOYMENT|OUTSOURC|HEADHUNT|PLACEMENT|ADVISORY'
)


def fetch_top_companies(db, sector=None, position_level=None, limit=10):
    """Return the top companies by posting count, each with its share of all
    postings in the current filter: columns company, postings, share_pct."""
    where = build_where_clause(sector, position_level)
    sql = f"""
        WITH ranked AS (
            SELECT company, COUNT(*) AS postings
            FROM jobs
            {where}
            GROUP BY company
            ORDER BY postings DESC
            LIMIT {int(limit)}
        )
        SELECT company, postings, postings * 100.0 / (SELECT COUNT(*) FROM jobs {where}) AS share_pct
        FROM ranked
    """
    return db.query(sql)


def render_market_concentration(db, sector=None, position_level=None):
    """Render the top-companies table and the total share they hold, flagging
    which look like staffing/recruitment agencies rather than direct employers."""
    df = fetch_top_companies(db, sector, position_level)
    st.subheader("Market Concentration: Top Companies")
    if df.empty:
        st.info("No postings match the current filters.")
        return

    df['likely_agency'] = df['company'].str.contains(_AGENCY_NAME_PATTERN, case=False, regex=True)
    total_share = df['share_pct'].sum()
    agency_share = df.loc[df['likely_agency'], 'share_pct'].sum()

    create_metric_columns({
        "Top 10 Companies' Share": format_percentage(total_share),
        "...of which, likely agencies": format_percentage(agency_share),
    })
    st.caption(
        "\"Likely agency\" is a name match (e.g. containing \"Recruit\", \"Staffing\", "
        "\"Advisory\"), not a verified list. When most of a top employer's volume is "
        "staffing agencies, that ranking reflects posting activity, not who is actually "
        "hiring - a useful caveat anywhere else in the dashboard that surfaces \"top companies.\""
    )
    display_df = df.copy()
    display_df['share_pct'] = display_df['share_pct'].apply(format_percentage)
    create_comparison_table(
        display_df,
        columns_to_show=['company', 'postings', 'share_pct', 'likely_agency']
    )


def render_wage_decomposition(db, sector=None, position_level=None):
    """Render the wage-growth decomposition and, for the unfiltered view, the
    sector share shifts behind its mix effect."""
    result = fetch_wage_decomposition(db, sector, position_level)
    st.subheader("Wage Growth: Real Increase vs. Market Mix Shift")

    row = result.iloc[0] if not result.empty else None
    if row is None or pd.isna(row['actual_early']) or row['n_segments'] == 0:
        st.info(
            f"Not enough data in this selection to decompose wage growth (each "
            f"sector/position-level segment needs at least {MIN_SEGMENT_SIZE} "
            f"postings in both the earliest and latest 3-month windows)."
        )
        return

    total_change = row['actual_late'] - row['actual_early']
    within_effect = row['late_pay_at_early_mix'] - row['actual_early']
    mix_effect = row['actual_late'] - row['late_pay_at_early_mix']

    st.caption(
        f"Comparing {row['early_window_label']} to {row['late_window_label']}, "
        f"across {int(row['n_segments'])} sector x position-level segments "
        f"({int(row['n_early_total']):,} and {int(row['n_late_total']):,} postings)."
    )
    create_metric_columns({
        "Headline Pay Change": format_currency(total_change),
        "From Real Wage Growth": format_currency(within_effect),
        "From Market Mix Shift": format_currency(mix_effect),
    })
    st.caption(
        "Real wage growth is the pay change within the same sector and position "
        "level. Market mix shift is the effect of the market posting relatively "
        "more (or fewer) jobs in higher- or lower-paying segments - it can mask "
        "or exaggerate the headline number even when nobody's actual pay moved."
    )

    if sector is not None:
        st.caption('Sector mix-shift detail is shown only for "All Sectors".')
        return

    shift_df = fetch_sector_mix_shift(db, position_level)
    if shift_df.empty:
        return
    st.caption("Sectors with the biggest change in share of postings:")
    display_df = shift_df.copy()
    for col in ['share_early_pct', 'share_late_pct', 'share_change_pct']:
        display_df[col] = display_df[col].apply(format_percentage)
    create_comparison_table(
        display_df,
        columns_to_show=['sector', 'share_early_pct', 'share_late_pct', 'share_change_pct']
    )


def render_market_overview_view():
    """
    Render the board's own header, filters, and all eight sections. Composable
    entry point for a shell that already has session state set up (e.g.
    app.py) — matches render_hirer_view()/render_seeker_view()'s
    zero-argument calling convention and self-contained header style.
    """
    st.header("📊 Market Overview")
    st.caption("What's happening in the Singapore job market")
    db = st.session_state.db
    sector, position_level = render_filters(db)
    st.divider()

    render_headline(db, sector, position_level)
    st.divider()
    render_industry_momentum(db, sector, position_level)
    st.divider()
    render_salary_trend(db, sector, position_level)
    st.divider()
    render_wage_decomposition(db, sector, position_level)
    st.divider()
    render_category_rankings(db, sector, position_level)
    st.divider()
    render_employment_type_mix(db, sector, position_level)
    st.divider()
    render_seasonality(db, sector, position_level)
    st.divider()
    render_market_concentration(db, sector, position_level)


def main():
    """Render the full Market Overview board, standalone."""
    initialize_session()
    render_market_overview_view()


if __name__ == "__main__":
    st.set_page_config(**STREAMLIT_CONFIG)
    main()
