"""
Main Streamlit dashboard application.
Entry point for the job analytics dashboard.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
from config.settings import STREAMLIT_CONFIG, DB_FILE
from src.database.database_manager import DatabaseManager
from src.dashboard.hirer_view import render_hirer_view
from src.dashboard.seeker_view import render_seeker_view
from src.dashboard.market_overview import render_market_overview_view

# Each board is one entry: adding a new one only means adding a line here.
VIEWS = {
    "Hirer": render_hirer_view,
    "Seeker": render_seeker_view,
    "Market Overview": render_market_overview_view,
}


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


def ensure_data():
    """Download jobs.duckdb from R2 if it's missing (fresh Streamlit Cloud deploy)."""
    if DB_FILE.exists():
        return

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{st.secrets['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=st.secrets["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=st.secrets["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    with st.spinner("Downloading job data..."):
        client.download_file(st.secrets["R2_BUCKET"], "jobs.duckdb", str(DB_FILE))


def initialize_session():
    """Initialize session state."""
    if 'db' not in st.session_state:
        ensure_data()
        st.session_state.db = DatabaseManager()
    if 'view_mode' not in st.session_state:
        st.session_state.view_mode = next(iter(VIEWS))


def render_header():
    """Render main header."""
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("📊 Singapore Jobs Analytics")
        st.markdown("*Market insights for hirers and job seekers*")
    with col2:
        view_mode = st.radio(
            "Select View:",
            list(VIEWS),
            horizontal=True
        )
        st.session_state.view_mode = view_mode


def main():
    """Main application entry point."""
    initialize_session()
    
    render_header()
    
    st.divider()
    
    # Route to appropriate view
    VIEWS[st.session_state.view_mode]()
    
    # Footer
    st.divider()
    st.markdown("""
    ---
    **About this Dashboard**
    
    This analytics dashboard provides insights into Singapore's job market. 
    - **Hirers** can identify market trends and top roles
    - **Job Seekers** can benchmark salaries, find opportunities, and understand market competitiveness
    """)


if __name__ == "__main__":
    st.set_page_config(**STREAMLIT_CONFIG)
    main()
