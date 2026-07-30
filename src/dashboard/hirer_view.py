"""
Hirer's dashboard view.
"""
import streamlit as st
from src.dashboard.utils import format_currency, create_metric_columns


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
        create_metric_columns({
            "Total Postings": f"{int(row['total_postings']):,}",
            "Active Companies": f"{int(row['num_companies']):,}",
            "Unique Roles": f"{int(row['unique_roles']):,}",
            "Avg Salary": format_currency(row['avg_salary']),
        })

    # Top roles
    st.subheader("Top Hiring Roles")
    if not metrics['top_roles'].empty:
        cols = st.columns(3)
        for idx, (_, row) in enumerate(metrics['top_roles'].head(3).iterrows()):
            with cols[idx % 3]:
                st.write(f"**{row['title']}**")
                st.write(f"Postings: {int(row['postings'])}")
                st.write(f"Avg Salary: {format_currency(row['avg_salary'])}")
                st.write(f"Companies: {int(row['companies'])}")

    # Roles in demand
    st.subheader("Roles in Demand")
    if not metrics['top_roles'].empty:
        roles_data = metrics['top_roles'].head(10)

        col1, col2 = st.columns(2)

        with col1:
            st.bar_chart(
                roles_data.set_index('title')['postings'],
                use_container_width=True
            )

        with col2:
            st.write("**Top Paying Roles**")
            roles_data_sorted = roles_data.sort_values('avg_salary', ascending=False)
            for _, row in roles_data_sorted.head(5).iterrows():
                st.write(f"{row['title']}: {format_currency(row['avg_salary'])}")

    # Hiring trends (year -> month drill-down)
    st.subheader("Hiring Trends")

    if st.session_state.get('hirer_trend_sector') != sector:
        st.session_state.hirer_trend_sector = sector
        st.session_state.hirer_trend_year = None

    if st.session_state.get('hirer_trend_year') is None:
        yearly_trends = st.session_state.db.get_hiring_trends(sector=sector, granularity='year')
        if not yearly_trends.empty:
            st.caption("Postings by year — select a year to drill into monthly detail")
            st.bar_chart(
                yearly_trends.set_index('period')['postings'],
                use_container_width=True
            )
            years = yearly_trends['period'].tolist()
            selected_year = st.selectbox(
                "Drill down into a year:",
                ["Select a year..."] + [str(y) for y in years],
                key="hirer_trend_year_select"
            )
            if selected_year != "Select a year...":
                st.session_state.hirer_trend_year = int(selected_year)
                st.rerun()
    else:
        if st.button("⬅ Back to yearly view"):
            st.session_state.hirer_trend_year = None
            st.rerun()
        monthly_trends = st.session_state.db.get_hiring_trends(
            sector=sector, granularity='month', year=st.session_state.hirer_trend_year
        )
        if not monthly_trends.empty:
            st.caption(f"Postings by month — {st.session_state.hirer_trend_year}")
            st.bar_chart(
                monthly_trends.set_index('period')['postings'],
                use_container_width=True
            )
        else:
            st.info("No data for this year.")
