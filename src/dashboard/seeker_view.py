"""
Job seeker's dashboard view.
"""
import pandas as pd
import streamlit as st
from src.dashboard.utils import (
    format_currency,
    format_currency_2dp,
    filter_selectbox,
    create_metric_columns,
)
from src.pipeline.feature_enrichment import derive_ssoc_job_label
from src.dashboard.theme import PAY_COLOR


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


def fetch_salary_percentile(db, industry=None, experience_level=None, salary=None):
    """Return the percentile and comparable posting count for a salary input."""
    where = build_where_clause(sector=industry, experience_level=experience_level)
    if salary is None:
        salary = 0
    sql = f"""
        WITH ranked AS (
            SELECT
                (salary_min + salary_max) / 2.0 AS market_salary
            FROM jobs
            {where}
        )
        SELECT
            ROUND(100 * (1 - (SELECT COUNT(*) FROM ranked WHERE market_salary < {float(salary)}) / NULLIF((SELECT COUNT(*) FROM ranked), 0)), 1) AS percentile,
            (SELECT COUNT(*) FROM ranked) AS comparable_postings
        FROM ranked
        LIMIT 1
    """
    return db.query(sql)


def fetch_pay_by_experience_years(db, industry=None):
    """Return median pay by required years of experience."""
    where = build_where_clause(sector=industry)
    sql = f"""
        SELECT
            seniority_years,
            ROUND(MEDIAN((salary_min + salary_max) / 2.0)) AS median_salary
        FROM jobs
        {where}
        AND seniority_years IS NOT NULL
        GROUP BY seniority_years
        ORDER BY seniority_years
    """
    return db.query(sql)


def fetch_seniority_ladder(db, industry=None):
    """Return median pay by the experience ladder for a chosen industry."""
    where = build_where_clause(sector=industry)
    sql = f"""
        SELECT
            COALESCE(position_level, 'Unspecified') AS position_level,
            ROUND(MEDIAN((salary_min + salary_max) / 2.0)) AS median_salary
        FROM jobs
        {where}
        GROUP BY position_level
        ORDER BY median_salary DESC
    """
    return db.query(sql)


def fetch_pay_range_by_industry_level(db, industry=None, limit=10):
    """Return pay range width by sector and experience level."""
    where = build_where_clause(sector=industry)
    sql = f"""
        SELECT
            sector,
            experience_level,
            ROUND(
                PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY (salary_min + salary_max) / 2.0)
                - PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY (salary_min + salary_max) / 2.0)
            ) AS pay_range
        FROM jobs
        {where}
        AND sector IS NOT NULL AND experience_level IS NOT NULL
        GROUP BY sector, experience_level
        ORDER BY pay_range DESC
        LIMIT {int(limit)}
    """
    return db.query(sql)


def fetch_competition_metrics(db, industry=None, experience_level=None, limit=10):
    """Return competition per opening for the selected filters."""
    where = build_where_clause(sector=industry, experience_level=experience_level)
    sql = f"""
        SELECT
            title,
            COUNT(*) AS postings,
            ROUND(COUNT(*) / NULLIF(SUM(vacancies), 0), 2) AS competition_ratio,
            ROUND(MEDIAN((salary_min + salary_max) / 2.0)) AS median_salary
        FROM jobs
        {where}
        GROUP BY title
    """
    df = db.query(sql)
    if not df.empty:
        df['job_label'] = df['title'].apply(lambda t: derive_ssoc_job_label(t, None, None))
        df = (
            df
            .groupby('job_label', observed=True, as_index=False)
            .agg(
                job_label=('job_label', 'first'),
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


def make_unique_categorical(values, ordered=True):
    """Create a categorical series from values while avoiding duplicate category labels."""
    cleaned = pd.Series(values).astype('string').fillna('Unknown')
    categories = list(dict.fromkeys(cleaned.dropna().tolist()))
    return pd.Categorical(cleaned, categories=categories, ordered=ordered)


def render_seeker_view():
    """Render job seeker-focused dashboard with fairness and opportunity insights."""
    st.header("🔍 Job Seeker's Dashboard")

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

    with col1:
        industry = filter_selectbox(
            "Industry:",
            st.session_state.db.get_sector_list(),
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

    metrics = st.session_state.db.get_seeker_view(experience_level=exp, sector=industry)
    percentile_df = fetch_salary_percentile(st.session_state.db, industry=industry, experience_level=exp, salary=salary_input)
    experience_years_df = fetch_pay_by_experience_years(st.session_state.db, industry=industry)
    ladder_df = fetch_seniority_ladder(st.session_state.db, industry=industry)
    pay_range_df = fetch_pay_range_by_industry_level(st.session_state.db, industry=industry, limit=10)
    competition_df = fetch_competition_metrics(st.session_state.db, industry=industry, experience_level=exp, limit=10)

    if not metrics['top_roles'].empty:
        metrics['top_roles']['job_label'] = metrics['top_roles']['title'].apply(
            lambda t: derive_ssoc_job_label(t, None, None)
        )
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
        metrics['salary_benchmarks']['job_label'] = metrics['salary_benchmarks']['title'].apply(
            lambda t: derive_ssoc_job_label(t, None, None)
        )
        metrics['salary_benchmarks'] = (
            metrics['salary_benchmarks']
            .groupby(['job_label', 'experience_level'], observed=True, as_index=False)
            .agg(
                experience_level=('experience_level', 'first'),
                median_entry=('median_entry', 'mean'),
                median_max=('median_max', 'mean'),
                p90=('p90', 'max'),
                count_samples=('count_samples', 'sum')
            )
            .sort_values('median_max', ascending=False)
        )
        # Some pandas builds may not expose DataFrame.applymap; use a
        # column-wise mapping which is more portable across pandas versions.
        for col in ['median_entry', 'median_max', 'p90']:
            if col in metrics['salary_benchmarks'].columns:
                metrics['salary_benchmarks'][col] = metrics['salary_benchmarks'][col].map(format_currency_2dp)
        valid_labels = (
            metrics['salary_benchmarks']
            .groupby('job_label')['count_samples']
            .transform('sum')
            >= 200
        )
        metrics['salary_benchmarks'] = metrics['salary_benchmarks'][valid_labels]

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

    st.subheader("Pay by Years of Experience Required")
    if not experience_years_df.empty:
        st.line_chart(
            experience_years_df.set_index('seniority_years')['median_salary'],
            color=PAY_COLOR,
            use_container_width=True
        )

    st.subheader("Seniority Ladder")
    if not ladder_df.empty:
        ladder_df['position_level'] = make_unique_categorical(ladder_df['position_level'])
        st.bar_chart(
            ladder_df.set_index('position_level')['median_salary'],
            color=PAY_COLOR,
            use_container_width=True
        )

    st.subheader("Pay Range Width by Industry & Level")
    if not pay_range_df.empty:
        chart_df = pay_range_df.copy()
        chart_df['industry_level'] = chart_df['sector'].astype(str) + " - " + chart_df['experience_level'].astype(str)
        chart_df['pay_range'] = pd.to_numeric(chart_df['pay_range'], errors='coerce')
        st.bar_chart(
            chart_df.set_index('industry_level')['pay_range'],
            color=PAY_COLOR,
            use_container_width=True
        )

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
        st.dataframe(
            competition_df[['Role', 'Competition Type', 'Postings', 'Competition / Opening', 'Median Salary ($)']],
            use_container_width=True,
            hide_index=True
        )

    # Top roles for seeker
    st.subheader("Best Opportunities")
    if not metrics['top_roles'].empty:
        st.dataframe(
            metrics['top_roles'].head(10).rename(columns={
                'role': 'Role',
                'opportunities': 'Postings',
                'avg_salary': 'Avg Salary ($)',
                'num_companies': 'Companies'
            }),
            use_container_width=True,
            hide_index=True
        )

    # Salary benchmarks
    st.subheader("Salary Benchmarks")
    if not metrics['salary_benchmarks'].empty:
        st.dataframe(
            metrics['salary_benchmarks'].head(10).rename(columns={
                'role': 'Role',
                'experience_level': 'Level',
                'p25': 'Entry ($)',
                'median_max': 'Market Rate ($)',
                'p90': 'Top 10% ($)'
            }),
            use_container_width=True,
            hide_index=True
        )

    # Competitive skills
    st.subheader("High-Value Skills (Avg Salary)")
    if not metrics['competitive_skills'].empty:
        skills_chart = metrics['competitive_skills'].head(10)
        st.bar_chart(
            skills_chart.set_index('skill')['avg_salary'],
            color=PAY_COLOR,
            use_container_width=True
        )
