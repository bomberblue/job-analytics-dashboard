"""
Job seeker's dashboard view.
"""
import streamlit as st
from src.dashboard.utils import format_currency, create_metric_columns


def render_seeker_view():
    """Render job seeker-focused dashboard."""
    st.header("🔍 Job Seeker's Dashboard")

    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        exp_level = st.selectbox(
            "Your Experience Level:",
            ["All Levels", "Entry Level", "Mid Level", "Senior"],
            key="seeker_exp"
        )
    with col2:
        sector_filter = st.selectbox(
            "Preferred Sector:",
            ["All Sectors"] + st.session_state.db.get_sector_list(),
            key="seeker_sector"
        )
    with col3:
        st.write("")  # Spacing

    exp = None if exp_level == "All Levels" else exp_level
    sector = None if sector_filter == "All Sectors" else sector_filter

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
