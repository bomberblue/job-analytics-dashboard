"""
Job seeker's dashboard view.
"""
import streamlit as st
from src.dashboard.utils import (
    create_metric_columns,
    filter_selectbox,
    format_currency,
)


def render_seeker_view():
    """Render job seeker-focused dashboard."""
    st.header("🔍 Job Seeker's Dashboard")

    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        exp = filter_selectbox(
            "Your Experience Level:",
            ["Entry Level", "Mid Level", "Senior"],
            "All Levels",
            key="seeker_exp"
        )
    with col2:
        sector = filter_selectbox(
            "Preferred Sector:",
            st.session_state.db.get_sector_list(),
            "All Sectors",
            key="seeker_sector"
        )
    with col3:
        st.write("")  # Spacing

    metrics = st.session_state.db.get_seeker_view(experience_level=exp, sector=sector)

    # Opportunities overview
    if not metrics['opportunities'].empty:
        row = metrics['opportunities'].iloc[0]
        create_metric_columns({
            "Total Opportunities": f"{int(row['total_opportunities']):,}",
            "Sectors Hiring": f"{int(row['sectors_hiring'])}",
            "Median Salary": format_currency(row['median_salary']),
            "Top Salary": format_currency(row['top_salary']),
        })

    # Top roles for seeker
    st.subheader("Best Opportunities")
    if not metrics['top_roles'].empty:
        st.dataframe(
            metrics['top_roles'].head(10).rename(columns={
                'title': 'Role',
                'opportunities': 'Postings',
                'avg_salary': 'Avg Salary',
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
                'title': 'Role',
                'experience_level': 'Level',
                'p25': 'Entry',
                'median_max': 'Market Rate',
                'p90': 'Top 10%'
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
            use_container_width=True
        )
