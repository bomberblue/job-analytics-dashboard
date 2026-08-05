"""
Market Overview board.
Standalone entry point: streamlit run src/dashboard/market_overview.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import altair as alt
from config.settings import STREAMLIT_CONFIG, ENGAGEMENT_COUNTER_FREEZE_DATE
from src.database.database_manager import DatabaseManager
from src.dashboard.utils import (
    create_metric_columns,
    filter_selectbox,
    format_currency,
    format_percentage,
    create_comparison_table,
)
from src.dashboard.finance_view import _table_exists
from src.dashboard.theme import VOLUME_COLOR, PAY_COLOR


def _labeled_table(df, rename_map):
    """Render df as a table with plain-English headers.

    columns_to_show is always exactly rename_map's values, in order - deriving
    it here instead of typing it out at each call site means renaming or
    adding a column can't drift the two lists out of sync.
    """
    create_comparison_table(
        df.rename(columns=rename_map),
        columns_to_show=list(rename_map.values())
    )


def build_where_clause(sector=None, position_level=None):
    """Build a composable SQL WHERE clause from optional filters."""
    conditions = ["posting_date IS NOT NULL"]
    if sector:
        conditions.append(f"sector = '{sector}'")
    if position_level:
        conditions.append(f"position_level = '{position_level}'")
    return "WHERE " + " AND ".join(conditions)


# One row per real posting (dup_group_id, first-seen), approximating
# hirer_data_loader.py's _market() dedup rule (that one keeps pandas'
# insertion-order "first"; this keeps the earliest posting_date instead, since
# SQL has no equivalent notion of row order to key off). Every fetch_*
# function below queries this instead of `jobs` directly, so postings aren't
# double-counted from same-day duplicates - `jobs` deliberately keeps every
# duplicate as its own row rather than dropping them at the pipeline layer, so
# dedup happens here, at the query layer, instead.
#
# job_id is a required secondary sort key, not cosmetic: within a dup_group_id,
# posting_date is usually identical for every row (it's close to the group's
# own key), which leaves ROW_NUMBER() with nothing to break the tie on and
# DuckDB picks arbitrarily - confirmed empirically, the same query returned
# different applicants/views sums across repeated runs on unchanged data
# before job_id (the table's primary key, so always unique) was added here.
DEDUPED_JOBS_CTE = """
    deduped_jobs AS (
        SELECT *
        FROM jobs
        QUALIFY ROW_NUMBER() OVER (PARTITION BY dup_group_id ORDER BY posting_date, job_id) = 1
    )
"""

# Median of (salary_min + salary_max)/2, restricted to disclosed/plausible
# salaries. A named fragment rather than three copies of the same FILTER
# clause, reused wherever a query also needs an unrestricted COUNT(*) in the
# same SELECT (FILTER scopes just this expression, not sibling aggregates).
MEDIAN_PAY_OK_SQL = "MEDIAN((salary_min + salary_max) / 2.0) FILTER (WHERE salary_flag = 'ok')"


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
        sector = filter_selectbox(
            "Sector:",
            db.get_sector_list(),
            "All Sectors",
            key="mkt_sector"
        )
    with col2:
        position_level = filter_selectbox(
            "Position Level:",
            fetch_position_levels(db),
            "All Levels",
            key="mkt_position_level"
        )
    return sector, position_level


@st.cache_data
def fetch_headline_metrics(_db, sector=None, position_level=None):
    """Return a 1-row DataFrame: total_postings, median_pay."""
    where = build_where_clause(sector, position_level)
    sql = f"""
        WITH {DEDUPED_JOBS_CTE}
        SELECT
            COUNT(*) AS total_postings,
            ROUND({MEDIAN_PAY_OK_SQL}) AS median_pay
        FROM deduped_jobs
        {where}
    """
    return _db.query(sql)


@st.cache_data
def fetch_industry_ranking(_db, sector=None, position_level=None, limit=None):
    """Return industries ranked by posting count: columns sector, postings."""
    where = build_where_clause(sector, position_level)
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    sql = f"""
        WITH {DEDUPED_JOBS_CTE}
        SELECT sector, COUNT(*) AS postings
        FROM deduped_jobs
        {where}
        GROUP BY sector
        ORDER BY postings DESC
        {limit_clause}
    """
    return _db.query(sql)


def render_headline(db, sector=None, position_level=None):
    """Render the headline metrics row."""
    metrics = fetch_headline_metrics(db, sector, position_level)
    top_industries = fetch_industry_ranking(db, sector, position_level, limit=3)

    if metrics.empty or metrics.iloc[0]['total_postings'] == 0:
        st.info("No postings match the current filters.")
        return

    row = metrics.iloc[0]
    top_industry_label = ", ".join(top_industries['sector'].tolist()) if not top_industries.empty else "N/A"

    # st.metric's value is truncate=True inside Streamlit's own Metric
    # component (single line, ellipsis) - there is no supported prop or CSS
    # override for it, since the truncating style is runtime-generated
    # CSS-in-JS with no stable selector to target. Fine for a number or a
    # dollar amount, wrong for a joined list of sector names, some of which
    # (e.g. "Real Estate / Property Management") are 30+ characters on their
    # own. So this one value is plain markdown instead of st.metric - no
    # truncation logic to fight because there's no Metric component involved.
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Postings", f"{int(row['total_postings']):,}")
    with col2:
        st.metric("Median Pay", format_currency(row['median_pay']))
    with col3:
        st.caption("Top Industries")
        st.markdown(f"##### {top_industry_label}")


@st.cache_data
def fetch_industry_momentum(_db, sector=None, position_level=None):
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
        WITH {DEDUPED_JOBS_CTE},
        monthly AS (
            SELECT
                sector,
                strftime(posting_date, '%Y-%m') AS ym,
                COUNT(*) AS postings
            FROM deduped_jobs
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
    df = _db.query(sql)
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
    _labeled_table(display_df, {
        'sector': 'Industry',
        'recent_avg_monthly': 'Recent Avg. Postings/Month',
        'prior_avg_monthly': 'Prior Avg. Postings/Month',
        'pct_change': '% Change',
        'recent_month_count': 'Recent Months Counted',
        'prior_month_count': 'Prior Months Counted',
    })


@st.cache_data
def fetch_salary_trend(_db, sector=None, position_level=None):
    """Return median pay by month: columns month ('YYYY-MM'), median_pay."""
    where = build_where_clause(sector, position_level)
    sql = f"""
        WITH {DEDUPED_JOBS_CTE}
        SELECT
            strftime(posting_date, '%Y-%m') AS month,
            ROUND({MEDIAN_PAY_OK_SQL}) AS median_pay
        FROM deduped_jobs
        {where}
        GROUP BY month
        ORDER BY month
    """
    return _db.query(sql)


def render_salary_trend(db, sector=None, position_level=None):
    """Render the salary trend line chart."""
    df = fetch_salary_trend(db, sector, position_level)
    st.subheader("Salary Trend")
    if df.empty:
        st.info("No postings match the current filters.")
        return
    st.caption(f"Median pay by month, {df['month'].iloc[0]} - {df['month'].iloc[-1]}")
    # st.line_chart has no axis-range control and defaults to a zero-based y-axis,
    # which on this data (a $500 range) squeezes every real change into a sliver
    # at the top of the chart. alt.Scale(zero=False) fits the axis to the data.
    # Deliberately a one-off: the bar charts elsewhere in this file are correctly
    # zero-based (they encode magnitude), so this isn't the start of a wider Altair
    # migration - just the one line chart with a range too narrow for a zero axis.
    chart = alt.Chart(df).mark_line(point=True, color=PAY_COLOR).encode(
        x=alt.X('month:O', title=None),
        y=alt.Y('median_pay:Q', title='Median Pay ($)', scale=alt.Scale(zero=False)),
    )
    st.altair_chart(chart, width='stretch')


@st.cache_data
def fetch_position_level_ranking(_db, sector=None, position_level=None):
    """Return position levels ranked by posting count: columns position_level, postings."""
    where = build_where_clause(sector, position_level)
    sql = f"""
        WITH {DEDUPED_JOBS_CTE}
        SELECT position_level, COUNT(*) AS postings
        FROM deduped_jobs
        {where}
        GROUP BY position_level
        ORDER BY postings DESC
    """
    return _db.query(sql)


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
            st.bar_chart(industries.set_index('sector')['postings'], color=VOLUME_COLOR, width='stretch')
    with col2:
        st.caption("By position level")
        if levels.empty:
            st.info("No postings match the current filters.")
        else:
            levels['position_level'] = pd.Categorical(
                levels['position_level'], categories=levels['position_level'], ordered=True
            )
            st.bar_chart(levels.set_index('position_level')['postings'], color=VOLUME_COLOR, width='stretch')


@st.cache_data
def fetch_employment_type_mix(_db, sector=None, position_level=None):
    """Return job types ranked by posting count, with median pay for each:
    columns job_type, postings, median_pay."""
    where = build_where_clause(sector, position_level)
    sql = f"""
        WITH {DEDUPED_JOBS_CTE}
        SELECT
            job_type,
            COUNT(*) AS postings,
            ROUND({MEDIAN_PAY_OK_SQL}) AS median_pay
        FROM deduped_jobs
        {where} AND job_type IS NOT NULL
        GROUP BY job_type
        ORDER BY postings DESC
    """
    return _db.query(sql)


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
        st.bar_chart(df.set_index('job_type')['postings'], color=VOLUME_COLOR, width='stretch')
    with col2:
        st.caption("By median pay")
        st.bar_chart(df.set_index('job_type')['median_pay'], color=PAY_COLOR, width='stretch')


_MONTH_NAMES = [
    None, "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
]


@st.cache_data
def fetch_seasonality(_db, sector=None, position_level=None):
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
        WITH {DEDUPED_JOBS_CTE},
        monthly AS (
            SELECT
                strftime(posting_date, '%Y') AS yr,
                EXTRACT(MONTH FROM posting_date)::INTEGER AS month_num,
                COUNT(*) AS postings
            FROM deduped_jobs
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
    df = _db.query(sql)
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
    st.bar_chart(df.set_index('month_name')['avg_postings'], color=VOLUME_COLOR, width='stretch')
    st.caption("Years and total postings behind each bar (a thin sample, like a month covered by only one partial year, will read as unreliable):")
    _labeled_table(df, {
        'month_name': 'Month',
        'years_included': 'Years of Data',
        'total_postings': 'Total Postings',
    })


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


@st.cache_data
def _early_late_windows(_db, sector=None, position_level=None, window_size=3):
    """
    Return (early_months, late_months): the first and last `window_size`
    distinct months present in the ramp-excluded, filtered data, as lists of
    'YYYY-MM' strings. Sliced from one sorted list rather than two independent
    SQL queries, so the two windows can never overlap regardless of how few
    months are available.

    Returns (None, None) when fewer than 2*window_size distinct months are
    available, so callers can show an "insufficient data" message instead.
    """
    where = _ramp_excluded_where(sector, position_level)
    months = _db.query(f"""
        WITH {DEDUPED_JOBS_CTE}
        SELECT DISTINCT strftime(posting_date, '%Y-%m') AS ym FROM deduped_jobs {where} ORDER BY ym
    """)['ym'].tolist()
    if len(months) < 2 * window_size:
        return None, None
    return months[:window_size], months[-window_size:]


def _sql_month_list(months):
    """Quote a list of 'YYYY-MM' strings for a SQL IN (...) clause."""
    return ", ".join(f"'{m}'" for m in months)


@st.cache_data
def fetch_wage_decomposition(_db, sector=None, position_level=None, windows=None):
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

    Only segments with at least MIN_SEGMENT_SIZE ok-salary postings in both
    windows are included (total_early_all/total_late_all report all ok-salary
    postings in each window - not literally every posting, since undisclosed/
    outlier/low-stipend rows are dropped before this count too - so callers
    can show how much was excluded for being in a thin segment).

    windows: optional (early_months, late_months) pair from a prior
    _early_late_windows() call, for a caller (render_wage_decomposition) that
    also needs the same windows for fetch_sector_mix_shift and would otherwise
    trigger that query twice. Computed internally when omitted.
    """
    early_months, late_months = windows if windows is not None else \
        _early_late_windows(_db, sector, position_level)
    if early_months is None:
        return pd.DataFrame()

    where = _ramp_excluded_where(sector, position_level)
    early_sql = _sql_month_list(early_months)
    late_sql = _sql_month_list(late_months)
    sql = f"""
        WITH {DEDUPED_JOBS_CTE},
        filtered AS (
            SELECT sector, position_level, strftime(posting_date, '%Y-%m') AS ym,
                   (salary_min + salary_max) / 2.0 AS pay
            FROM deduped_jobs
            {where} AND salary_flag = 'ok'
        ),
        segment AS (
            SELECT
                sector, position_level,
                AVG(pay) FILTER (WHERE ym IN ({early_sql})) AS pay_early,
                AVG(pay) FILTER (WHERE ym IN ({late_sql}))  AS pay_late,
                COUNT(*) FILTER (WHERE ym IN ({early_sql})) AS n_early,
                COUNT(*) FILTER (WHERE ym IN ({late_sql}))  AS n_late
            FROM filtered
            GROUP BY sector, position_level
        ),
        valid AS (
            SELECT * FROM segment
            WHERE n_early >= {MIN_SEGMENT_SIZE} AND n_late >= {MIN_SEGMENT_SIZE}
        )
        SELECT
            COUNT(*)::INTEGER AS n_segments,
            SUM(n_early)::INTEGER AS n_early_total,
            SUM(n_late)::INTEGER AS n_late_total,
            (SELECT SUM(n_early) FROM segment) AS total_early_all,
            (SELECT SUM(n_late)  FROM segment) AS total_late_all,
            SUM(pay_early * n_early) / NULLIF(SUM(n_early), 0) AS actual_early,
            SUM(pay_late  * n_late)  / NULLIF(SUM(n_late), 0)  AS actual_late,
            SUM(pay_late  * n_early) / NULLIF(SUM(n_early), 0) AS late_pay_at_early_mix
        FROM valid
    """
    df = _db.query(sql)
    df['early_window_label'] = f"{early_months[0]} to {early_months[-1]}"
    df['late_window_label'] = f"{late_months[0]} to {late_months[-1]}"
    return df


@st.cache_data
def fetch_sector_mix_shift(_db, position_level=None, limit=8, windows=None):
    """
    Return the sectors whose share of postings changed the most between the
    early and late windows used by fetch_wage_decomposition. This is the detail
    behind that function's "mix effect": a sector gaining share pulls overall
    pay toward its own pay level even when nobody's individual wage moved.

    windows: see fetch_wage_decomposition - reuse its windows when the caller
    already computed them, instead of re-querying for the same months.
    """
    early_months, late_months = windows if windows is not None else \
        _early_late_windows(_db, sector=None, position_level=position_level)
    if early_months is None:
        return pd.DataFrame()

    where = _ramp_excluded_where(sector=None, position_level=position_level)
    early_sql = _sql_month_list(early_months)
    late_sql = _sql_month_list(late_months)
    sql = f"""
        WITH {DEDUPED_JOBS_CTE},
        filtered AS (
            SELECT sector, strftime(posting_date, '%Y-%m') AS ym
            FROM deduped_jobs
            {where}
        ),
        totals AS (
            SELECT
                COUNT(*) FILTER (WHERE ym IN ({early_sql})) AS total_early,
                COUNT(*) FILTER (WHERE ym IN ({late_sql}))  AS total_late
            FROM filtered
        )
        SELECT
            sector,
            COUNT(*) FILTER (WHERE ym IN ({early_sql})) * 100.0
                / NULLIF((SELECT total_early FROM totals), 0) AS share_early_pct,
            COUNT(*) FILTER (WHERE ym IN ({late_sql})) * 100.0
                / NULLIF((SELECT total_late FROM totals), 0) AS share_late_pct
        FROM filtered
        GROUP BY sector
    """
    df = _db.query(sql)
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


@st.cache_data
def fetch_top_companies(_db, sector=None, position_level=None, limit=10):
    """Return the top companies by posting count, each with its share of all
    postings in the current filter: columns company, postings, share_pct."""
    where = build_where_clause(sector, position_level)
    sql = f"""
        WITH {DEDUPED_JOBS_CTE},
        ranked AS (
            SELECT company, COUNT(*) AS postings
            FROM deduped_jobs
            {where}
            GROUP BY company
            ORDER BY postings DESC
            LIMIT {int(limit)}
        )
        SELECT company, postings, postings * 100.0 / (SELECT COUNT(*) FROM deduped_jobs {where}) AS share_pct
        FROM ranked
    """
    return _db.query(sql)


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
    _labeled_table(display_df, {
        'company': 'Company',
        'postings': 'Postings',
        'share_pct': 'Share of Market',
        'likely_agency': 'Likely Recruitment Agency',
    })


def render_wage_decomposition(db, sector=None, position_level=None):
    """Render the wage-growth decomposition and, for the unfiltered view, the
    sector share shifts behind its mix effect."""
    # Computed once and passed to both fetch calls below: with no sector filter,
    # fetch_sector_mix_shift would otherwise recompute the identical windows.
    windows = _early_late_windows(db, sector, position_level)
    result = fetch_wage_decomposition(db, sector, position_level, windows=windows)
    st.subheader("Wage Growth: Real Increase vs. Market Mix Shift")

    row = result.iloc[0] if not result.empty else None
    if row is None or pd.isna(row['actual_early']):
        st.info(
            f"Not enough data in this selection to decompose wage growth (need at "
            f"least 6 distinct months after {WAGE_DECOMPOSITION_START_DATE}, with "
            f"each sector/position-level segment having at least {MIN_SEGMENT_SIZE} "
            f"postings in both the earliest and latest 3-month windows)."
        )
        return

    total_change = row['actual_late'] - row['actual_early']
    within_effect = row['late_pay_at_early_mix'] - row['actual_early']
    mix_effect = row['actual_late'] - row['late_pay_at_early_mix']
    excluded_early = int(row['total_early_all'] - row['n_early_total'])
    excluded_late = int(row['total_late_all'] - row['n_late_total'])

    st.caption(
        f"Comparing {row['early_window_label']} to {row['late_window_label']}, "
        f"across {int(row['n_segments'])} sector x position-level segments with at "
        f"least {MIN_SEGMENT_SIZE} postings in both windows "
        f"({int(row['n_early_total']):,} and {int(row['n_late_total']):,} postings, "
        f"disclosed-salary only; {excluded_early:,} early and {excluded_late:,} late "
        f"such postings fell in thinner segments and are excluded)."
    )
    create_metric_columns({
        "Pay Change (Matched Segments)": format_currency(total_change),
        "From Real Wage Growth": format_currency(within_effect),
        "From Market Mix Shift": format_currency(mix_effect),
    })
    st.caption(
        "Real wage growth is the pay change within the same sector and position "
        "level. Market mix shift is the effect of the market posting relatively "
        "more (or fewer) jobs in higher- or lower-paying segments - it can mask "
        "or exaggerate the headline number even when nobody's actual pay moved. "
        "This figure is restricted to segments with enough postings in both "
        "windows to compare, so it can differ from the overall Median Pay above."
    )

    if sector is not None:
        st.caption('Sector mix-shift detail is shown only for "All Sectors".')
        return

    shift_df = fetch_sector_mix_shift(db, position_level, windows=windows)
    if shift_df.empty:
        return
    st.caption("Sectors with the biggest change in share of postings:")
    display_df = shift_df.copy()
    for col in ['share_early_pct', 'share_late_pct', 'share_change_pct']:
        display_df[col] = display_df[col].apply(format_percentage)
    _labeled_table(display_df, {
        'sector': 'Industry',
        'share_early_pct': 'Early Period Share',
        'share_late_pct': 'Late Period Share',
        'share_change_pct': 'Change in Share',
    })


# Same counter-freeze boundary as hirer_data_loader.py's CRAWL_DATE (see
# config/settings.py for the underlying data artifact). Any leverage/competition
# measure below excludes postings after it; pay itself is unaffected and uses
# the full period.
ENGAGEMENT_DATA_END_DATE = ENGAGEMENT_COUNTER_FREEZE_DATE

# Minimum postings an industry needs (in the engagement window, or with a
# disclosed salary) before its leverage or pay figure is trusted.
MIN_LEVERAGE_SAMPLE = 2000

# Minimum Contract and Permanent postings an industry needs in finance_job_features
# before its cost premium is trusted - matches finance_view's own threshold.
MIN_CONTRACT_COHORT_SAMPLE = 30

# Minimum postings a sector needs, in the counters-complete 30-day-listing
# cohort, before its repost rate is trusted - matches hirer_data_loader.MIN_N,
# the smallest cell hirer's own repost figures are read from. Move together.
MIN_REPOST_SAMPLE = 30

# Below this many industries, a correlation coefficient is noise, not a finding.
MIN_SECTORS_FOR_CORRELATION = 5


def _position_level_filter(position_level):
    """SQL fragment narrowing to one position level, or "" for no filter."""
    return f"AND position_level = '{position_level}'" if position_level else ""


@st.cache_data
def fetch_leverage_vs_pay(_db, position_level=None, min_n=MIN_LEVERAGE_SAMPLE):
    """
    Return, per industry, how much competitive pressure candidates face
    (applicants per opening, view-to-apply conversion) against median pay -
    the leverage-vs-pay side of "does the market pay more where it's harder
    to hire?"

    Deliberately two independent WHERE clauses rather than one shared filter:
    leverage needs the pre-ENGAGEMENT_DATA_END_DATE window (see that constant),
    pay does not and uses the full period, so restricting pay to the same
    window would throw away good salary data for no reason.
    """
    position_filter = _position_level_filter(position_level)
    sql = f"""
        WITH {DEDUPED_JOBS_CTE},
        leverage AS (
            SELECT sector,
                SUM(applications) * 1.0 / NULLIF(SUM(vacancies), 0) AS applicants_per_opening,
                SUM(applications) * 100.0 / NULLIF(SUM(views), 0) AS apply_rate_pct
            FROM deduped_jobs
            WHERE posting_date < '{ENGAGEMENT_DATA_END_DATE}' AND sector IS NOT NULL
            {position_filter}
            GROUP BY sector
            HAVING COUNT(*) >= {int(min_n)}
        ),
        pay AS (
            SELECT sector, MEDIAN(salary_midpoint) AS median_pay
            FROM deduped_jobs
            WHERE salary_flag = 'ok' AND sector IS NOT NULL
            {position_filter}
            GROUP BY sector
            HAVING COUNT(*) >= {int(min_n)}
        )
        SELECT leverage.sector, applicants_per_opening, apply_rate_pct, median_pay
        FROM leverage JOIN pay ON pay.sector = leverage.sector
    """
    return _db.query(sql)


def fetch_contract_premium(db, position_level=None, min_cohort=MIN_CONTRACT_COHORT_SAMPLE):
    """
    Return, per industry, the median contract-vs-permanent cost premium: how
    much more (or less) a contract posting's estimated monthly cost is versus
    a permanent one, matching finance_view's own cohort definition and sample
    threshold. Empty if the finance pipeline hasn't been run yet.

    Deliberately a coarser (sector-only) re-derivation of finance_view.py's
    _conversion_base_sql, not a call into it: this section needs one number per
    sector to correlate against leverage, not finance_view's full
    sector/sub_sector/position_level breakdown. If the cohort definition or
    MIN_CONTRACT_COHORT_SAMPLE threshold changes there, mirror it here too.
    """
    if not _table_exists(db, 'finance_job_features'):
        return pd.DataFrame()
    position_filter = _position_level_filter(position_level)
    sql = f"""
        WITH cohort AS (
            SELECT sector, employment_cohort,
                MEDIAN(loaded_monthly_cost_per_head) AS median_cost,
                COUNT(*) AS n
            FROM finance_job_features
            WHERE employment_cohort IN ('Contract', 'Permanent') AND sector IS NOT NULL
            {position_filter}
            GROUP BY sector, employment_cohort
        ),
        pivoted AS (
            SELECT sector,
                MAX(CASE WHEN employment_cohort = 'Contract' THEN median_cost END) AS contract_cost,
                MAX(CASE WHEN employment_cohort = 'Contract' THEN n END) AS n_contract,
                MAX(CASE WHEN employment_cohort = 'Permanent' THEN median_cost END) AS permanent_cost,
                MAX(CASE WHEN employment_cohort = 'Permanent' THEN n END) AS n_permanent
            FROM cohort
            GROUP BY sector
        )
        SELECT sector,
            (contract_cost - permanent_cost) * 100.0 / NULLIF(permanent_cost, 0) AS contract_premium_pct
        FROM pivoted
        WHERE n_contract >= {int(min_cohort)} AND n_permanent >= {int(min_cohort)}
    """
    return db.query(sql)


@st.cache_data
def fetch_repost_rate_by_sector(_db, position_level=None, min_n=MIN_REPOST_SAMPLE):
    """
    Return, per industry, the share of postings that were reposted - Hirer's
    headline finding, re-derived at sector grain for the cross-view
    correlation below.

    Mirrors hirer_data_loader._layer2_cohort()'s cohort definition (counters
    complete, 30-day listings) in SQL rather than calling into that module -
    same "coarser sector-only re-derivation, not a call into it" pattern
    fetch_contract_premium already uses, keeping the view modules independent.
    """
    position_filter = _position_level_filter(position_level)
    sql = f"""
        WITH {DEDUPED_JOBS_CTE},
        cohort AS (
            SELECT sector, is_repost
            FROM deduped_jobs
            WHERE expiry_date <= '{ENGAGEMENT_DATA_END_DATE}'
              AND listing_days = 30
              AND sector IS NOT NULL
              {position_filter}
        )
        SELECT sector, AVG(is_repost::INT) * 100 AS repost_rate_pct, COUNT(*) AS n
        FROM cohort
        GROUP BY sector
        HAVING COUNT(*) >= {int(min_n)}
    """
    return _db.query(sql)


def fetch_exposure_by_sector(db, position_level=None):
    """
    Return, per industry, median vacancy budget exposure per opening - the
    cost accrued while a vacancy sits open, from Finance's pipeline.

    Reads finance_job_features.vacancy_exposure_per_opening directly, the
    value baked in at the last pipeline run - deliberately not recomputed
    from finance_view's live scenario sliders, matching fetch_contract_premium's
    existing behavior (same accepted staleness trade-off, not a new one).
    Empty if the finance pipeline hasn't been run yet.
    """
    if not _table_exists(db, 'finance_job_features'):
        return pd.DataFrame()
    position_filter = _position_level_filter(position_level)
    sql = f"""
        SELECT sector, MEDIAN(vacancy_exposure_per_opening) AS median_exposure_per_opening
        FROM finance_job_features
        WHERE sector IS NOT NULL
        {position_filter}
        GROUP BY sector
    """
    return db.query(sql)


def _scatter_with_extreme_labels(df, x_col, y_col, x_title, y_title, tooltip_fmt, n_labeled=2):
    """
    A single-color scatter (one dot per industry) with sparse text labels on
    only the highest- and lowest-x points - labeling all ~20 industries would
    be unreadable, so the rest are left to the tooltip.
    """
    base = alt.Chart(df).mark_circle(size=160, opacity=0.85, color=VOLUME_COLOR).encode(
        x=alt.X(f'{x_col}:Q', title=x_title),
        y=alt.Y(f'{y_col}:Q', title=y_title, scale=alt.Scale(zero=False)),
        tooltip=[
            alt.Tooltip('sector:N', title='Industry'),
            alt.Tooltip(f'{x_col}:Q', title=x_title, format='.2f'),
            alt.Tooltip(f'{y_col}:Q', title=y_title, format=tooltip_fmt),
        ],
    ).properties(height=320)

    extremes = pd.concat([df.nlargest(n_labeled, x_col), df.nsmallest(n_labeled, x_col)]).drop_duplicates(subset='sector')
    labels = alt.Chart(extremes).mark_text(align='left', dx=8, dy=-6, fontSize=10, color='#52514e').encode(
        x=f'{x_col}:Q', y=f'{y_col}:Q', text='sector:N',
    )
    return base + labels


def render_cross_view_insight(db, sector=None, position_level=None):
    """
    The capstone: does pay actually respond to how hard a role is to fill, and
    does the standard cost-saving lever (converting permanent roles to
    contract) target the industries that actually need that flexibility?
    Also tests whether repost rate tracks median vacancy budget exposure per
    opening by industry.

    Compares across all industries at once, so - like fetch_sector_mix_shift -
    this only renders for "All Sectors"; position_level may still narrow it.
    """
    st.markdown("#### Does Pay Track Scarcity?")
    st.caption(
        "Leverage - applicants per opening - against pay, by industry: does the "
        "market actually pay more where a role is harder to fill?"
    )
    if sector is not None:
        st.info('This section compares across all industries at once, so it is shown only for "All Sectors".')
        return

    leverage_df = fetch_leverage_vs_pay(db, position_level=position_level)
    if len(leverage_df) < MIN_SECTORS_FOR_CORRELATION:
        st.info(
            f"Not enough industries with sufficient sample size ({MIN_LEVERAGE_SAMPLE:,}+ "
            "postings, before the engagement-data cutoff) to test this under the current filter."
        )
    else:
        leverage_pay_corr = leverage_df['applicants_per_opening'].corr(leverage_df['median_pay'])

        premium_df = fetch_contract_premium(db, position_level=position_level)
        combined = (
            premium_df.merge(leverage_df[['sector', 'applicants_per_opening']], on='sector')
            if not premium_df.empty else pd.DataFrame()
        )
        premium_corr = (
            combined['applicants_per_opening'].corr(combined['contract_premium_pct'])
            if len(combined) >= MIN_SECTORS_FOR_CORRELATION else None
        )

        stats = {"Correlation: Leverage vs. Pay": f"{leverage_pay_corr:+.2f}"}
        if premium_corr is not None:
            stats["Correlation: Leverage vs. Contract Premium"] = f"{premium_corr:+.2f}"
        create_metric_columns(stats)
        st.caption(
            "Correlation coefficients, -1 to +1. Leverage vs. Pay near zero means pay "
            "does not track how competitive an industry is to hire in. A negative "
            "Leverage vs. Contract Premium means converting to contract saves the "
            "least money exactly where competition for talent is fiercest - the "
            "opposite of where that flexibility is actually needed."
        )

        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"Applicants per Opening vs. Median Pay ({len(leverage_df)} industries)")
            st.altair_chart(
                _scatter_with_extreme_labels(
                    leverage_df, 'applicants_per_opening', 'median_pay',
                    'Applicants per Opening', 'Median Pay ($)', ',.0f'
                ),
                width='stretch'
            )
        with col2:
            st.caption(f"Applicants per Opening vs. Contract Premium ({len(combined)} industries)")
            if combined.empty:
                st.info(
                    "Requires the finance pipeline's tables, which aren't materialized in "
                    "this database yet."
                )
            else:
                st.altair_chart(
                    _scatter_with_extreme_labels(
                        combined, 'applicants_per_opening', 'contract_premium_pct',
                        'Applicants per Opening', 'Contract Premium (%)', '+.1f'
                    ),
                    width='stretch'
                )

    st.divider()
    st.markdown("#### Where Reposting Meets Budget Risk")
    st.caption(
        "Repost rate against median vacancy budget exposure per opening, by "
        "industry: do the sectors most likely to repost a vacancy also cost "
        "the most while it sits open?"
    )

    repost_df = fetch_repost_rate_by_sector(db, position_level=position_level)
    exposure_df = fetch_exposure_by_sector(db, position_level=position_level)
    if exposure_df.empty:
        st.info(
            "Requires the finance pipeline's tables, which aren't materialized in "
            "this database yet."
        )
    else:
        risk_df = repost_df.merge(exposure_df, on='sector')
        if len(risk_df) < MIN_SECTORS_FOR_CORRELATION:
            st.info(
                f"Not enough industries with sufficient sample size ({MIN_REPOST_SAMPLE:,}+ "
                "postings in the counters-complete, 30-day-listing cohort) to test this "
                "under the current filter."
            )
        else:
            risk_corr = risk_df['repost_rate_pct'].corr(risk_df['median_exposure_per_opening'])
            create_metric_columns({"Correlation: Repost Rate vs. Exposure/Opening": f"{risk_corr:+.2f}"})
            st.caption(f"Repost Rate vs. Median Exposure per Opening ({len(risk_df)} industries)")
            st.altair_chart(
                _scatter_with_extreme_labels(
                    risk_df, 'repost_rate_pct', 'median_exposure_per_opening',
                    'Repost Rate (%)', 'Median Exposure per Opening ($)', ',.0f'
                ),
                width='stretch'
            )
            st.caption(
                "Sectors in the upper right are paying twice - once in the "
                "re-posting cycle, again in accrued vacancy cost. That combination "
                "is the priority list for the pay/experience-ask fix Hirer's own "
                "repost analysis recommends, not exposure or repost risk alone."
            )


def render_market_overview_view():
    """
    Render the board's own caption, filters, and nine sections grouped into
    four tabs, in narrative order: what's happening and why, what the market
    looks like, who's actually posting, and what it all means together. Tabs
    instead of always-visible bordered panels - matches finance_view.py's
    plain st.tabs() pattern, and shows only one group at a time instead of
    all nine sections in one continuous scroll. Visual only: unlike
    hirer_view.py's tabs (on_change="rerun" + a tab.open check), these are
    plain st.tabs(), so every tab's queries and charts still run on every
    rerun regardless of which one is active - this reduces what's on screen,
    not how much gets computed. No header - the nav chip above already names
    the board (see app.py's render_nav()). Composable entry point for a shell
    that already has session state set up (e.g. app.py) — matches
    render_hirer_view()/render_seeker_view()'s zero-argument calling
    convention.
    """
    db = st.session_state.db
    st.caption("Pay trends, market composition, and structure in Singapore's job postings.")
    sector, position_level = render_filters(db)
    st.divider()

    tab_pulse, tab_composition, tab_structure, tab_cross_view = st.tabs(
        ["Market Pulse", "Market Composition", "Market Structure", "Cross-View Insight"]
    )

    with tab_pulse:
        render_headline(db, sector, position_level)
        st.divider()
        render_industry_momentum(db, sector, position_level)
        st.divider()
        render_salary_trend(db, sector, position_level)
        st.divider()
        render_wage_decomposition(db, sector, position_level)

    with tab_composition:
        render_category_rankings(db, sector, position_level)
        st.divider()
        render_employment_type_mix(db, sector, position_level)
        st.divider()
        render_seasonality(db, sector, position_level)

    with tab_structure:
        render_market_concentration(db, sector, position_level)

    with tab_cross_view:
        render_cross_view_insight(db, sector, position_level)


def main():
    """Render the full Market Overview board, standalone."""
    initialize_session()
    render_market_overview_view()


if __name__ == "__main__":
    st.set_page_config(**STREAMLIT_CONFIG)
    main()
