"""
Job seeker's dashboard view.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from src.dashboard.utils import (
    format_currency,
    format_currency_2dp,
    filter_selectbox,
    create_metric_columns,
)
from src.pipeline.feature_enrichment import derive_ssoc_job_labels_bulk


def _db_mod_time(db):
    """Return the last modified time of the database file for cache invalidation."""
    return Path(db.db_path).stat().st_mtime


@st.cache_data(show_spinner='Loading seeker dashboard query…')
def _cached_query(db_path, db_mod_time, sql):
    import duckdb

    conn = duckdb.connect(db_path, read_only=True)
    try:
        return conn.execute(sql).df()
    finally:
        conn.close()


@st.cache_data(show_spinner='Loading sector list…')
def _cached_sector_list(db_path, db_mod_time):
    sql = "SELECT DISTINCT sector FROM jobs WHERE sector IS NOT NULL ORDER BY sector"
    df = _cached_query(db_path, db_mod_time, sql)
    return df['sector'].tolist()


@st.cache_data(show_spinner='Loading raw seeker dataset…')
def _cached_raw_seeker_dataset(db_path, db_mod_time):
    sql = """
        SELECT
            title,
            company,
            sector,
            experience_level,
            seniority_years,
            position_level,
            salary_min,
            salary_max,
            vacancies,
            skills
        FROM jobs
        WHERE posting_date IS NOT NULL
          AND salary_min IS NOT NULL
          AND salary_max IS NOT NULL
          AND salary_min >= 500
          AND salary_max <= 100000
          AND (seniority_years IS NULL OR seniority_years <= 30)
    """
    df = _cached_query(db_path, db_mod_time, sql)
    if not df.empty:
        df = df.copy()
        df['market_salary'] = (df['salary_min'] + df['salary_max']) / 2.0
    return df


@st.cache_data(show_spinner='Loading job label lookup…')
def _cached_job_label_map(db_path, db_mod_time):
    """title -> job_label for every distinct title, computed once per db build.

    job_label is a pure function of title, and derive_ssoc_job_labels_bulk is cheap per
    distinct title (~360k) but every caller here works with an already title-deduplicated
    frame (post-groupby) - so this returns a lookup dict for a cheap .map(), rather than a
    column pre-populated on the full ~1M-row dataset, which would cost extra to broadcast
    out to every row for no consumer that actually needs it at that grain.
    """
    sql = "SELECT DISTINCT title FROM jobs WHERE title IS NOT NULL"
    titles = _cached_query(db_path, db_mod_time, sql)['title']
    return dict(zip(titles, derive_ssoc_job_labels_bulk(titles)))


@st.cache_data(show_spinner='Loading seeker dataset…')
def _cached_seeker_dataset(db_path, db_mod_time, industry=None, experience_level=None):
    seeker_df = _cached_raw_seeker_dataset(db_path, db_mod_time)
    if seeker_df.empty:
        return seeker_df

    if industry:
        seeker_df = seeker_df[seeker_df['sector'] == industry]
    if experience_level:
        seeker_df = seeker_df[seeker_df['experience_level'] == experience_level]
    return seeker_df


MIN_BENCHMARK_SAMPLE = 200  # smallest job_label total we will quote a salary benchmark for


@st.cache_data(show_spinner='Loading seeker metrics…')
def _cached_seeker_metrics(db_path, db_mod_time, experience_level, sector):
    seeker_df = _cached_seeker_dataset(db_path, db_mod_time, sector, experience_level)

    metrics = {
        'opportunities': pd.DataFrame([{
            'total_opportunities': len(seeker_df),
            'sectors_hiring': int(seeker_df['sector'].nunique(dropna=True)),
            'median_salary': round(seeker_df['market_salary'].median()) if not seeker_df.empty else float('nan'),
            'top_salary': int(seeker_df['salary_max'].max()) if not seeker_df.empty else float('nan'),
        }]),
        'top_roles': pd.DataFrame(columns=['title', 'opportunities', 'avg_salary', 'min_salary', 'num_companies']),
        'salary_benchmarks': pd.DataFrame(columns=['title', 'experience_level', 'p25', 'median_entry', 'median_max', 'p90', 'count_samples']),
        'competitive_skills': pd.DataFrame(columns=['skill', 'opportunities', 'avg_salary']),
    }

    if not seeker_df.empty:
        # top_roles only ever needs job_label for the 10 rows it ends up displaying, so the
        # map is applied after the head(10) truncation rather than on the full title grouping.
        metrics['top_roles'] = (
            seeker_df
            .groupby('title', observed=True, as_index=False)
            .agg(
                opportunities=('title', 'size'),
                avg_salary=('market_salary', 'mean'),
                min_salary=('salary_min', 'min'),
                num_companies=('company', 'nunique')
            )
            .sort_values('opportunities', ascending=False)
            .head(10)
        )
        label_map = _cached_job_label_map(db_path, db_mod_time)
        metrics['top_roles']['job_label'] = metrics['top_roles']['title'].map(label_map)

        grouped = seeker_df.groupby(['title', 'experience_level'], observed=True)
        salary_benchmarks = grouped.agg(
            median_entry=('salary_min', 'mean'),
            median_max=('salary_max', 'mean'),
            p90=('salary_max', 'max'),
            count_samples=('title', 'size')
        )
        # groupby.quantile() is vectorized; a lambda inside .agg() calls Python
        # per group and is unusably slow at title-level cardinality (~380k groups).
        salary_benchmarks['p25'] = grouped['market_salary'].quantile(.25).round(0)
        salary_benchmarks = salary_benchmarks.reset_index()
        salary_benchmarks['job_label'] = salary_benchmarks['title'].map(label_map)
        salary_benchmarks = (
            salary_benchmarks
            .groupby(['job_label', 'experience_level'], observed=True, as_index=False)
            .agg(
                p25=('p25', 'mean'),
                median_entry=('median_entry', 'mean'),
                median_max=('median_max', 'mean'),
                p90=('p90', 'max'),
                count_samples=('count_samples', 'sum')
            )
            .sort_values('median_max', ascending=False)
        )
        valid_labels = (
            salary_benchmarks
            .groupby('job_label')['count_samples']
            .transform('sum')
            >= MIN_BENCHMARK_SAMPLE
        )
        metrics['salary_benchmarks'] = salary_benchmarks[valid_labels]

        skills_df = seeker_df[['skills', 'salary_min', 'salary_max']].copy()
        skills_df = skills_df.assign(skill=skills_df['skills'].fillna('').str.split(','))
        skills_df = skills_df.explode('skill').reset_index(drop=True)
        skills_df['skill'] = skills_df['skill'].astype('string').str.strip()
        skills_df = skills_df[skills_df['skill'].replace('', pd.NA).notna()]
        skills_df = skills_df[skills_df['skill'] != 'Not Specified']
        if not skills_df.empty:
            skills_df['avg_salary'] = (skills_df['salary_min'] + skills_df['salary_max']) / 2.0
            metrics['competitive_skills'] = (
                skills_df
                .groupby('skill', observed=True, as_index=False)
                .agg(
                    opportunities=('skill', 'size'),
                    avg_salary=('avg_salary', 'mean')
                )
                .query('opportunities > 10')
                .sort_values('avg_salary', ascending=False)
                .head(15)
            )
    return metrics


def build_where_clause(sector=None, experience_level=None, seniority_years=None):
    """Build a composable SQL WHERE clause for seeker analytics.

    The current processed jobs table does not include a ``salary_flag`` column,
    so the query falls back to filtering on the salary bounds directly and caps
    experience at a realistic upper bound.
    """
    conditions = [
        "posting_date IS NOT NULL",
        "salary_min IS NOT NULL",
        "salary_max IS NOT NULL",
        "salary_min >= 500",
        "salary_max <= 100000",
        "(seniority_years IS NULL OR seniority_years <= 30)",
    ]
    if sector:
        conditions.append(f"sector = '{sector}'")
    if experience_level:
        conditions.append(f"experience_level = '{experience_level}'")
    if seniority_years is not None:
        conditions.append(f"seniority_years = {int(seniority_years)}")
    return "WHERE " + " AND ".join(conditions)


@st.cache_data(show_spinner='Loading salary percentile…')
def _fetch_salary_percentile(db_path, db_mod_time, industry=None, experience_level=None, salary=None):
    seeker_df = _cached_seeker_dataset(db_path, db_mod_time, industry, experience_level)
    if salary is None:
        salary = 0
    if seeker_df.empty:
        return pd.DataFrame([{'percentile': float('nan'), 'comparable_postings': 0}])

    total = len(seeker_df)
    lower_count = int((seeker_df['market_salary'] <= float(salary)).sum())
    percentile = round(100 * lower_count / total, 1)
    return pd.DataFrame([{
        'percentile': percentile,
        'comparable_postings': int(total),
    }])


def fetch_salary_percentile(db, industry=None, experience_level=None, salary=None):
    """Return the percentile and comparable posting count for a salary input."""
    return _fetch_salary_percentile(db.db_path, _db_mod_time(db), industry, experience_level, salary)


@st.cache_data(show_spinner='Loading pay-by-experience data…')
def _fetch_pay_by_experience_years(db_path, db_mod_time, industry=None, experience_level=None):
    seeker_df = _cached_seeker_dataset(db_path, db_mod_time, industry, experience_level)
    seeker_df = seeker_df.dropna(subset=['seniority_years'])
    if seeker_df.empty:
        return pd.DataFrame(columns=['seniority_years', 'median_salary'])

    result = (
        seeker_df
        .groupby('seniority_years', observed=True, as_index=False)['market_salary']
        .median()
        .rename(columns={'market_salary': 'median_salary'})
        .round(0)
        .sort_values('seniority_years')
    )
    return result


def fetch_pay_by_experience_years(db, industry=None, experience_level=None):
    """Return median pay by required years of experience."""
    return _fetch_pay_by_experience_years(db.db_path, _db_mod_time(db), industry, experience_level)


@st.cache_data(show_spinner='Loading seniority ladder…')
def _fetch_seniority_ladder(db_path, db_mod_time, industry=None, experience_level=None):
    seeker_df = _cached_seeker_dataset(db_path, db_mod_time, industry, experience_level)
    if seeker_df.empty:
        return pd.DataFrame(columns=['position_level', 'median_salary'])

    seeker_df['position_level'] = seeker_df['position_level'].fillna('Unspecified')
    result = (
        seeker_df
        .groupby('position_level', observed=True, as_index=False)['market_salary']
        .median()
        .rename(columns={'market_salary': 'median_salary'})
        .round(0)
        .sort_values('median_salary', ascending=False)
    )
    return result


def fetch_seniority_ladder(db, industry=None, experience_level=None):
    """Return median pay by the experience ladder for a chosen industry."""
    return _fetch_seniority_ladder(db.db_path, _db_mod_time(db), industry, experience_level)


@st.cache_data(show_spinner='Loading pay-range data…')
def _fetch_pay_range_by_industry_level(db_path, db_mod_time, industry=None, experience_level=None, limit=10):
    seeker_df = _cached_seeker_dataset(db_path, db_mod_time, industry, experience_level)
    seeker_df = seeker_df.dropna(subset=['sector', 'experience_level'])
    if seeker_df.empty:
        return pd.DataFrame(columns=['sector', 'experience_level', 'pay_range'])

    result = (
        seeker_df
        .groupby(['sector', 'experience_level'], observed=True, as_index=False)
        .agg(pay_range=('market_salary', lambda s: np.round(s.quantile(0.9) - s.quantile(0.1), 0)))
        .sort_values('pay_range', ascending=False)
        .head(int(limit))
    )
    return result


def fetch_pay_range_by_industry_level(db, industry=None, experience_level=None, limit=10):
    """Return pay range width by sector and experience level."""
    return _fetch_pay_range_by_industry_level(db.db_path, _db_mod_time(db), industry, experience_level, limit)


@st.cache_data(show_spinner='Loading competition metrics…')
def _fetch_competition_metrics(db_path, db_mod_time, industry=None, experience_level=None, limit=10):
    seeker_df = _cached_seeker_dataset(db_path, db_mod_time, industry, experience_level)
    if seeker_df.empty:
        return pd.DataFrame(columns=['job_label', 'postings', 'competition_ratio', 'median_salary', 'competition_type'])

    title_metrics = (
        seeker_df
        .groupby('title', observed=True, as_index=False)
        .agg(
            postings=('title', 'size'),
            vacancies=('vacancies', 'sum'),
            median_salary=('market_salary', 'median')
        )
    )
    title_metrics['competition_ratio'] = np.where(
        title_metrics['vacancies'] == 0,
        np.nan,
        title_metrics['postings'] / title_metrics['vacancies'],
    )
    label_map = _cached_job_label_map(db_path, db_mod_time)
    title_metrics['job_label'] = title_metrics['title'].map(label_map)
    df = (
        title_metrics
        .groupby('job_label', observed=True, as_index=False)
        .agg(
            postings=('postings', 'sum'),
            competition_ratio=('competition_ratio', 'mean'),
            median_salary=('median_salary', 'mean')
        )
    )
    top_n = int(limit / 2) + (limit % 2)
    high = df.sort_values(['competition_ratio', 'postings'], ascending=[False, False]).head(top_n).copy()
    low = df.sort_values(['competition_ratio', 'postings'], ascending=[True, False]).head(int(limit / 2)).copy()
    high['competition_type'] = 'High'
    low['competition_type'] = 'Low'
    df = pd.concat([high, low], ignore_index=True)
    df = df.sort_values(['competition_type', 'competition_ratio', 'postings'], ascending=[False, False, False])
    return df


def fetch_competition_metrics(db, industry=None, experience_level=None, limit=10):
    """Return competition per opening for the selected filters."""
    return _fetch_competition_metrics(db.db_path, _db_mod_time(db), industry, experience_level, limit)


def make_unique_categorical(values, ordered=True):
    """Create a categorical series from values while avoiding duplicate category labels."""
    cleaned = pd.Series(values).astype('string').fillna('Unknown')
    categories = list(dict.fromkeys(cleaned.dropna().tolist()))
    return pd.Categorical(cleaned, categories=categories, ordered=ordered)


def render_seeker_view():
    """Render job seeker-focused dashboard with fairness and opportunity insights.
    No header - the nav chip above already names the board."""
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

    with col1:
        industry = filter_selectbox(
            "Industry:",
            _cached_sector_list(st.session_state.db.db_path, _db_mod_time(st.session_state.db)),
            "All Industries",
            key="seeker_industry"
        )
    with col2:
        exp = filter_selectbox(
            "Your Experience Level:",
            ["Entry Level", "Mid Level", "Senior"],
            "All Levels",
            key="seeker_exp"
        )
    with col3:
        salary_input = st.number_input(
            "Your Salary (SGD):",
            min_value=0,
            value=7000,
            step=500,
            key="seeker_salary"
        )
    with col4:
        st.write("")  # Spacing

    metrics = _cached_seeker_metrics(
        st.session_state.db.db_path,
        _db_mod_time(st.session_state.db),
        exp,
        industry,
    )
    percentile_df = _fetch_salary_percentile(
        st.session_state.db.db_path,
        _db_mod_time(st.session_state.db),
        industry,
        exp,
        salary_input,
    )
    ladder_df = _fetch_seniority_ladder(
        st.session_state.db.db_path,
        _db_mod_time(st.session_state.db),
        industry,
        exp,
    )
    pay_range_df = _fetch_pay_range_by_industry_level(
        st.session_state.db.db_path,
        _db_mod_time(st.session_state.db),
        industry,
        exp,
        limit=10,
    )
    competition_df = _fetch_competition_metrics(
        st.session_state.db.db_path,
        _db_mod_time(st.session_state.db),
        industry,
        exp,
        limit=10,
    )

    if not metrics['top_roles'].empty:
        metrics['top_roles'] = (
            metrics['top_roles']
            .groupby('job_label', observed=True, as_index=False)
            .agg(
                opportunities=('opportunities', 'sum'),
                avg_salary=('avg_salary', 'mean'),
                num_companies=('num_companies', 'sum')
            )
            .sort_values('opportunities', ascending=False)
        )
        metrics['top_roles']['avg_salary'] = metrics['top_roles']['avg_salary'].apply(format_currency_2dp)

    if not metrics['salary_benchmarks'].empty:
        # Some pandas builds may not expose DataFrame.applymap; use a
        # column-wise mapping which is more portable across pandas versions.
        for col in ['p25', 'median_entry', 'median_max', 'p90']:
            if col in metrics['salary_benchmarks'].columns:
                metrics['salary_benchmarks'][col] = metrics['salary_benchmarks'][col].map(format_currency_2dp)

    # Opportunities overview
    if not metrics['opportunities'].empty:
        row = metrics['opportunities'].iloc[0]
        create_metric_columns({
            "Total Opportunities": f"{int(row['total_opportunities']):,}",
            "Sectors Hiring": f"{int(row['sectors_hiring'])}",
            "Median Salary": format_currency(row['median_salary']),
            "Top Salary": format_currency(row['top_salary']),
        })

    st.subheader("Pay Fairness & Market Position")
    if not percentile_df.empty:
        percentile = percentile_df.iloc[0]['percentile']
        comparable_postings = int(percentile_df.iloc[0]['comparable_postings'])
        st.metric(
            "Your salary percentile",
            f"{percentile:.1f}%",
            help=f"Compared with {comparable_postings} comparable postings"
        )
        if pd.notna(percentile):
            if percentile >= 70:
                st.success("You are above the typical market rate for this slice.")
            elif percentile >= 40:
                st.info("You are around the middle of the market.")
            else:
                st.warning("You are below the typical market rate for this slice.")

    st.subheader("Seniority Ladder")
    if not ladder_df.empty:
        ladder_df = (
            ladder_df
            .assign(position_level=make_unique_categorical(ladder_df['position_level']))
            .sort_values('median_salary', ascending=False)
            .head(8)
            .assign(median_salary=lambda df: df['median_salary'].map(format_currency_2dp))
            .rename(columns={'position_level': 'Position Level', 'median_salary': 'Median Salary'})
        )
        st.table(ladder_df[['Position Level', 'Median Salary']])

    st.subheader("Pay Range Width by Industry & Level")
    if not pay_range_df.empty:
        chart_df = pay_range_df.copy().head(8)
        chart_df['industry_level'] = chart_df['sector'].astype(str) + " - " + chart_df['experience_level'].astype(str)
        chart_df['pay_range'] = pd.to_numeric(chart_df['pay_range'], errors='coerce')
        chart_df = (
            chart_df
            .assign(pay_range=lambda df: df['pay_range'].map(format_currency_2dp))
            .rename(columns={'industry_level': 'Industry / Level', 'pay_range': 'Pay Range'})
        )
        st.table(chart_df[['Industry / Level', 'Pay Range']])

    st.subheader("Competition Per Opening")
    if not competition_df.empty:
        competition_df['median_salary'] = competition_df['median_salary'].apply(format_currency_2dp)
        competition_df = competition_df.rename(columns={
            'job_label': 'Role',
            'postings': 'Postings',
            'competition_ratio': 'Competition / Opening',
            'median_salary': 'Median Salary ($)',
            'competition_type': 'Competition Type'
        })
        st.table(
            competition_df[['Role', 'Competition Type', 'Postings', 'Competition / Opening', 'Median Salary ($)']].head(8)
        )

    # Top roles for seeker
    st.subheader("Best Opportunities")
    if not metrics['top_roles'].empty:
        st.table(
            metrics['top_roles'].head(6).rename(columns={
                'job_label': 'Role',
                'opportunities': 'Postings',
                'avg_salary': 'Avg Salary ($)',
                'num_companies': 'Companies'
            })
        )

    # Salary benchmarks
    st.subheader("Salary Benchmarks")
    if not metrics['salary_benchmarks'].empty:
        st.table(
            metrics['salary_benchmarks'].head(6).rename(columns={
                'job_label': 'Role',
                'experience_level': 'Level',
                'p25': 'Entry ($)',
                'median_max': 'Market Rate ($)',
                'p90': 'Top 10% ($)'
            })
        )

    # Competitive skills
    st.subheader("High-Value Skills (Median Salary)")
    if not metrics['competitive_skills'].empty:
        skills_df = (
            metrics['competitive_skills']
            .head(10)
            .assign(median_salary=lambda df: df['avg_salary'].map(format_currency_2dp))
            .rename(columns={
                'skill': 'Skill',
                'opportunities': 'Opportunities',
                'median_salary': 'Median Salary ($)'
            })
        )
        st.table(skills_df[['Skill', 'Opportunities', 'Median Salary ($)']])
