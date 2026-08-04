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

    /* Scoped to the nav chips' own container (render_nav()'s st.container(key=
       "nav_chips")), not every button in the app - a button added elsewhere
       later shouldn't silently inherit sizing meant for chip-length sentences. */
    .st-key-nav_chips button {
        height: auto;
        min-height: 3.4rem;
        padding: 0.65rem 1rem;
        font-size: 0.95rem;
        white-space: normal;
        line-height: 1.35;
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
    """Just the title - the chip row below is the only nav now."""
    st.markdown("#### 📊 Singapore Jobs Analytics")


# (view, chip label) - one per VIEWS entry, same order. Asserted below rather
# than left as a comment, so a board added/renamed/reordered in VIEWS without
# a matching NAV_CHIPS update fails loudly instead of silently mis-navigating.
NAV_CHIPS = [
    ("Market Overview", "📈 Market Overview — market trends and pay dynamics"),
    ("Hirer", "🧑‍💼 Hirers — pay benchmarks & response diagnostics"),
    ("Seeker", "🔍 Job Seekers — pay checks & competitiveness"),
    ("Finance Partner", "💼 Finance Business Partner — cost mix & budget risk"),
]
assert [view for view, _ in NAV_CHIPS] == list(VIEWS), (
    f"NAV_CHIPS must list VIEWS's keys, in order: "
    f"got {[v for v, _ in NAV_CHIPS]}, expected {list(VIEWS)}"
)


def _select_view(view):
    st.session_state.view_mode = view


def render_nav():
    """The four chips are the whole nav - no separate view switch. The active
    view's chip is disabled rather than just styled differently: clicking it
    would be a no-op anyway, and a disabled button is Streamlit's plainest way
    to say "you're already here"."""
    st.caption("This analytics dashboard provides insights into Singapore's job market:")
    with st.container(key="nav_chips"):
        cols = st.columns(len(NAV_CHIPS))
        for col, (view, label) in zip(cols, NAV_CHIPS):
            with col:
                st.button(
                    label, key=f"nav_chip_{view}", use_container_width=True,
                    on_click=_select_view, args=(view,),
                    disabled=(view == st.session_state.view_mode),
                )


def main():
    """Main application entry point."""
    initialize_session()

    render_header()
    render_nav()

    # Separates the nav row from the board below. Hirer's own tab strip draws
    # a second rule right under this one - a minor redundancy on that one
    # board, left as-is rather than special-cased, since the other three boards
    # have no header or tabs of their own and need this divider to have any
    # separation at all.
    st.divider()

    # Route to appropriate view
    VIEWS[st.session_state.view_mode]()


if __name__ == "__main__":
    st.set_page_config(**STREAMLIT_CONFIG)
    main()
