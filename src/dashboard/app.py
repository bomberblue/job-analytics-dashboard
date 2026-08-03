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
from src.dashboard.finance_view import render_finance_view

# Each board is one entry: adding a new one only means adding a line here.
VIEWS = {
    "Market Overview": render_market_overview_view,
    "Hirer": render_hirer_view,
    "Seeker": render_seeker_view,
    "Finance Partner": render_finance_view ,
}


# Streamlit reserves 6rem above the first element in wide layout, more than the
# charts can spare. There is no native setting for it, so it is trimmed here.
# The floor is the toolbar: it overlays the page at 60px tall, so anything under
# 3.75rem slides beneath it and the first row gets clipped.
st.html("""
<style>
    .block-container, [data-testid="stMainBlockContainer"] {
        max-width: 1400px;
        padding-top: 4.5rem;
        padding-bottom: 2rem;
    }
</style>
""")


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
    """Title and view switch on one line, so the charts start higher up."""
    col1, col2 = st.columns([2, 3], vertical_alignment="center")
    with col1:
        st.markdown("#### 📊 Singapore Jobs Analytics")
    with col2:
        selected = st.segmented_control(
            "Select view", list(VIEWS),
            default=st.session_state.view_mode,
            label_visibility="collapsed",
            key="view_switch",
        )
    # Clicking the active segment clears the selection; stay on the current board.
    st.session_state.view_mode = selected or st.session_state.view_mode


def main():
    """Main application entry point."""
    initialize_session()

    render_header()

    st.divider()

    # Route to appropriate view
    VIEWS[st.session_state.view_mode]()

    st.divider()
    st.markdown("""
    ---
    **About this Dashboard**
    
    This analytics dashboard provides insights into Singapore's job market. 
    - **Hirers** can identify market trends and top roles
    - **Job Seekers** can benchmark salaries, find opportunities, and understand market competitiveness
    - **Finance Partners** can evaluate workforce-cost mix and vacancy budget risk
    """)


if __name__ == "__main__":
    st.set_page_config(**STREAMLIT_CONFIG)
    main()
