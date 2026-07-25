"""
Main Streamlit dashboard application.
Entry point for the job analytics dashboard.
"""
import streamlit as st
import pandas as pd
from config.settings import STREAMLIT_CONFIG
from src.database.database_manager import DatabaseManager
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# Configure page
st.set_page_config(**STREAMLIT_CONFIG)

# Custom CSS
st.markdown("""
<style>
    .main {
        max-width: 1400px;
    }
    .metric-card {
        padding: 20px;
        border-radius: 10px;
        background-color: #f0f2f6;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)


def initialize_session():
    """Initialize session state."""
    if 'db' not in st.session_state:
        st.session_state.db = DatabaseManager()
    if 'view_mode' not in st.session_state:
        st.session_state.view_mode = "Hirer"


def render_header():
    """Render main header."""
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("📊 Singapore Jobs Analytics")
        st.markdown("*Market insights for hirers and job seekers*")
    with col2:
        view_mode = st.radio(
            "Select View:",
            ["Hirer", "Seeker"],
            horizontal=True
        )
        st.session_state.view_mode = view_mode


def render_hirer_view():
    """Render hirer-focused dashboard."""
    st.header("👔 Hirer's Dashboard")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Market Overview")
    with col2:
        sector_filter = st.selectbox(
            "Filter by Sector:",
            ["All Sectors"] + st.session_state.db.get_sector_list(),
            key="hirer_sector"
        )
    
    sector = None if sector_filter == "All Sectors" else sector_filter
    metrics = st.session_state.db.get_hirer_view(sector=sector)
    
    # Market overview metrics
    if not metrics['market_overview'].empty:
        row = metrics['market_overview'].iloc[0]
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Postings", f"{int(row['total_postings']):,}")
        with col2:
            st.metric("Active Companies", f"{int(row['num_companies']):,}")
        with col3:
            st.metric("Unique Roles", f"{int(row['unique_roles']):,}")
        with col4:
            avg_salary = row['avg_salary']
            st.metric("Avg Salary", f"${int(avg_salary):,}" if pd.notna(avg_salary) else "N/A")
    
    # Top roles
    st.subheader("Top Hiring Roles")
    if not metrics['top_roles'].empty:
        cols = st.columns(3)
        for idx, (_, row) in enumerate(metrics['top_roles'].head(3).iterrows()):
            with cols[idx % 3]:
                st.write(f"**{row['title']}**")
                st.write(f"Postings: {int(row['postings'])}")
                st.write(f"Avg Salary: ${int(row['avg_salary']):,}" if pd.notna(row['avg_salary']) else "N/A")
                st.write(f"Companies: {int(row['companies'])}")
    
    # Skills in demand
    st.subheader("Skills in Demand")
    if not metrics['skills_in_demand'].empty:
        skills_data = metrics['skills_in_demand'].head(10)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.bar_chart(
                skills_data.set_index('skill')['demand_count'],
                use_container_width=True
            )
        
        with col2:
            st.write("**Skill Premium (Salary Impact)**")
            skills_data_sorted = skills_data.sort_values('avg_salary', ascending=False)
            for _, row in skills_data_sorted.head(5).iterrows():
                st.write(f"{row['skill']}: ${int(row['avg_salary']):,}")
    
    # Hiring trends
    st.subheader("Hiring Trends (Last 30 Days)")
    if not metrics['hiring_trends'].empty:
        trend_data = metrics['hiring_trends'].sort_values('posting_date')
        st.line_chart(
            trend_data.set_index('posting_date')['postings'],
            use_container_width=True
        )


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
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Opportunities", f"{int(row['total_opportunities']):,}")
        with col2:
            st.metric("Sectors Hiring", f"{int(row['sectors_hiring'])}")
        with col3:
            st.metric("Median Salary", f"${int(row['median_salary']):,}" if pd.notna(row['median_salary']) else "N/A")
        with col4:
            st.metric("Top Salary", f"${int(row['top_salary']):,}" if pd.notna(row['top_salary']) else "N/A")
    
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
    st.subheader("High-Value Skills (Salary Premium)")
    if not metrics['competitive_skills'].empty:
        skills_chart = metrics['competitive_skills'].head(10)
        st.bar_chart(
            skills_chart.set_index('skill')['salary_premium'],
            use_container_width=True
        )


def main():
    """Main application entry point."""
    initialize_session()
    
    render_header()
    
    st.divider()
    
    # Route to appropriate view
    if st.session_state.view_mode == "Hirer":
        render_hirer_view()
    else:
        render_seeker_view()
    
    # Footer
    st.divider()
    st.markdown("""
    ---
    **About this Dashboard**
    
    This analytics dashboard provides insights into Singapore's job market. 
    - **Hirers** can identify market trends, top roles, and in-demand skills
    - **Job Seekers** can benchmark salaries, find opportunities, and understand market competitiveness
    """)


if __name__ == "__main__":
    main()
