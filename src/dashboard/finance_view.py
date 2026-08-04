"""Finance Business Partner dashboard view."""

import altair as alt
import streamlit as st

from src.dashboard.utils import create_metric_columns, format_currency, format_percentage
from src.dashboard.theme import PAY_COLOR


REQUIRED_FINANCE_TABLES = [
    "finance_scenario_params",
    "finance_job_features",
    "finance_industry_budget_risk",
    "finance_permanent_contract_conversion_economics",
]


def _table_exists(db, table_name: str) -> bool:
    result = db.query(
        f"""
        SELECT COUNT(*) AS n
        FROM information_schema.tables
        WHERE table_name = '{table_name}'
        """
    )
    return int(result.iloc[0]["n"]) > 0


def _finance_tables_ready(db) -> bool:
    return all(_table_exists(db, table_name) for table_name in REQUIRED_FINANCE_TABLES)


def _render_missing_tables_message():
    st.error(
        "Finance feature tables are missing. Run 'python -m src.pipeline.pipeline' "
        "to materialize finance_* tables first."
    )


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def _fetch_years(db) -> list[int]:
    result = db.query(
        """
        SELECT DISTINCT EXTRACT(YEAR FROM posting_date)::INTEGER AS posting_year
        FROM finance_job_features
        WHERE posting_date IS NOT NULL
        ORDER BY posting_year DESC
        """
    )
    return result["posting_year"].dropna().astype(int).tolist()


def _build_where_clause(
    year: int,
    sector: str,
    sub_sector: str | None,
    skill_keyword: str | None,
    alias: str = "f",
) -> str:
    conditions = [
        f"EXTRACT(YEAR FROM {alias}.posting_date) = {int(year)}",
        f"{alias}.sector = '{_sql_escape(sector)}'",
    ]
    if sub_sector:
        conditions.append(f"{alias}.sub_sector = '{_sql_escape(sub_sector)}'")
    if skill_keyword:
        keyword = _sql_escape(skill_keyword.strip().lower())
        if keyword:
            conditions.append(
                f"""
                (
                    lower(COALESCE({alias}.title, '')) LIKE '%{keyword}%'
                    OR EXISTS (
                        SELECT 1 FROM jobs j
                        WHERE j.job_id = {alias}.job_id
                          AND lower(COALESCE(j.skills, '')) LIKE '%{keyword}%'
                    )
                )
                """
            )
    return "WHERE " + " AND ".join(conditions)


def _fetch_industries(db, year: int):
    result = db.query(
        f"""
        SELECT DISTINCT sector
        FROM finance_job_features
        WHERE sector IS NOT NULL
          AND EXTRACT(YEAR FROM posting_date) = {int(year)}
        ORDER BY sector
        """
    )
    return result["sector"].tolist()


def _fetch_sub_sectors(db, year: int, sector: str):
    result = db.query(
        f"""
        SELECT DISTINCT sub_sector
        FROM finance_job_features
        WHERE EXTRACT(YEAR FROM posting_date) = {int(year)}
          AND sector = '{_sql_escape(sector)}'
          AND sub_sector IS NOT NULL
        ORDER BY sub_sector
        """
    )
    return result["sub_sector"].tolist()


def _fetch_headline_metrics(db, year: int, sector: str, sub_sector: str | None, skill_keyword: str | None):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    return db.query(
        f"""
        SELECT
            COUNT(*) AS postings,
            SUM(vacancy_budget_exposure) AS total_budget_exposure,
            MEDIAN(vacancy_exposure_per_opening) AS median_exposure_per_opening,
            MEDIAN(loaded_monthly_cost_per_head) AS median_loaded_monthly_cost_per_head,
            SUM(CASE WHEN employment_cohort = 'Contract' THEN 1 ELSE 0 END) AS contract_postings,
            SUM(CASE WHEN employment_cohort = 'Permanent' THEN 1 ELSE 0 END) AS permanent_postings
        FROM finance_job_features f
        {where}
        """
    )


# market_overview.py's fetch_contract_premium re-derives this same Contract-vs-
# Permanent cohort comparison at coarser (sector-only) grain for its cross-view
# correlation; mirror any change to the cohort definition or sample threshold
# there too.
def _conversion_base_sql(where: str) -> str:
    return f"""
        WITH filtered AS (
            SELECT
                f.job_id,
                f.sector,
                f.sub_sector,
                f.position_level,
                f.employment_cohort,
                f.loaded_monthly_cost_per_head,
                f.posting_window_days
            FROM finance_job_features f
            {where}
        ),
        cohort_benchmarks AS (
            SELECT
                sector,
                sub_sector,
                position_level,
                employment_cohort,
                COUNT(DISTINCT job_id) AS postings,
                MEDIAN(loaded_monthly_cost_per_head) AS median_loaded_monthly_cost,
                MEDIAN(posting_window_days) AS median_posting_window_days
            FROM filtered
            WHERE employment_cohort IN ('Permanent', 'Contract')
            GROUP BY sector, sub_sector, position_level, employment_cohort
        ),
        pivoted AS (
            SELECT
                sector,
                sub_sector,
                position_level,
                MAX(CASE WHEN employment_cohort = 'Contract' THEN postings END) AS postings_contract,
                MAX(CASE WHEN employment_cohort = 'Permanent' THEN postings END) AS postings_permanent,
                MAX(CASE WHEN employment_cohort = 'Contract' THEN median_loaded_monthly_cost END) AS median_loaded_monthly_cost_contract,
                MAX(CASE WHEN employment_cohort = 'Permanent' THEN median_loaded_monthly_cost END) AS median_loaded_monthly_cost_permanent,
                MAX(CASE WHEN employment_cohort = 'Contract' THEN median_posting_window_days END) AS median_posting_window_days_contract,
                MAX(CASE WHEN employment_cohort = 'Permanent' THEN median_posting_window_days END) AS median_posting_window_days_permanent
            FROM cohort_benchmarks
            GROUP BY sector, sub_sector, position_level
        )
        SELECT
            *,
            median_loaded_monthly_cost_contract - median_loaded_monthly_cost_permanent AS monthly_cost_delta_contract_minus_permanent,
            (median_loaded_monthly_cost_contract - median_loaded_monthly_cost_permanent)
                / NULLIF(median_loaded_monthly_cost_permanent, 0) AS contract_cost_delta_rate,
            CASE
                WHEN ((median_loaded_monthly_cost_contract - median_loaded_monthly_cost_permanent)
                    / NULLIF(median_loaded_monthly_cost_permanent, 0)) <= -0.03 THEN 'Savings'
                WHEN ((median_loaded_monthly_cost_contract - median_loaded_monthly_cost_permanent)
                    / NULLIF(median_loaded_monthly_cost_permanent, 0)) >= 0.03 THEN 'Cost premium'
                ELSE 'Cost neutral'
            END AS conversion_decision
        FROM pivoted
        WHERE postings_contract >= 30
          AND postings_permanent >= 30
          AND median_loaded_monthly_cost_contract IS NOT NULL
          AND median_loaded_monthly_cost_permanent IS NOT NULL
    """


def _fetch_conversion_decision_summary(db, year: int, sector: str, sub_sector: str | None, skill_keyword: str | None):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    base_sql = _conversion_base_sql(where)
    return db.query(
        f"""
        WITH conversion AS (
            {base_sql}
        )
        SELECT
            conversion_decision,
            COUNT(*) AS segments,
            AVG(contract_cost_delta_rate) AS avg_delta_rate,
            MEDIAN(monthly_cost_delta_contract_minus_permanent) AS median_monthly_delta
        FROM conversion
        GROUP BY conversion_decision
        ORDER BY segments DESC
        """
    )


def _fetch_conversion_candidates(
    db,
    year: int,
    sector: str,
    sub_sector: str | None,
    skill_keyword: str | None,
    decision: str,
    limit=15,
):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    base_sql = _conversion_base_sql(where)
    return db.query(
        f"""
        WITH conversion AS (
            {base_sql}
        )
        SELECT
            sector,
            sub_sector,
            position_level,
            postings_contract,
            postings_permanent,
            median_loaded_monthly_cost_contract,
            median_loaded_monthly_cost_permanent,
            monthly_cost_delta_contract_minus_permanent,
            contract_cost_delta_rate,
            conversion_decision
        FROM conversion
        WHERE conversion_decision = '{_sql_escape(decision)}'
        ORDER BY ABS(monthly_cost_delta_contract_minus_permanent) DESC
        LIMIT {int(limit)}
        """
    )


def _fetch_exposure_by_position_level(db, year: int, sector: str, sub_sector: str | None, skill_keyword: str | None, limit=12):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    return db.query(
        f"""
        SELECT
            position_level,
            COUNT(*) AS postings,
            SUM(number_of_vacancies) AS vacancies,
            MEDIAN(posting_window_days) AS median_posting_window_days,
            SUM(vacancy_budget_exposure) AS total_vacancy_budget_exposure,
            MEDIAN(vacancy_exposure_per_opening) AS median_exposure_per_opening
        FROM finance_job_features f
        {where}
        GROUP BY position_level
        HAVING SUM(number_of_vacancies) > 0
        ORDER BY total_vacancy_budget_exposure DESC
        LIMIT {int(limit)}
        """
    )


def _fetch_slowest_expensive_segments(db, year: int, sector: str, sub_sector: str | None, skill_keyword: str | None, limit=15):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    return db.query(
        f"""
        SELECT
            sector,
            sub_sector,
            position_level,
            employment_cohort,
            COUNT(*) AS postings,
            SUM(number_of_vacancies) AS vacancies,
            MEDIAN(posting_window_days) AS median_posting_window_days,
            SUM(vacancy_budget_exposure) AS total_vacancy_budget_exposure,
            MEDIAN(vacancy_exposure_per_opening) AS median_exposure_per_opening
        FROM finance_job_features f
        {where}
        GROUP BY sector, sub_sector, position_level, employment_cohort
        HAVING SUM(number_of_vacancies) > 0
        ORDER BY total_vacancy_budget_exposure DESC
        LIMIT {int(limit)}
        """
    )


def _fetch_scenario(db):
    return db.query("SELECT * FROM finance_scenario_params")


def _safe_pct(numerator, denominator):
    if denominator in (0, None):
        return None
    return 100.0 * numerator / denominator


def render_finance_view():
    """Render Finance Business Partner view for workforce-cost and budget risk."""
    st.header("💼 Finance Business Partner View")
    st.caption(
        "Translate workforce mix and hiring-speed decisions into dollars, so Finance can "
        "approve or challenge contract-vs-permanent budget shifts."
    )

    db = st.session_state.db
    if not _finance_tables_ready(db):
        _render_missing_tables_message()
        return

    years = _fetch_years(db)
    if not years:
        st.info("No posting year values available in finance_job_features.")
        return

    industries = _fetch_industries(db, years[0])
    if not industries:
        st.info("No sector values available in finance_job_features for the selected year.")
        return

    col1, col2, col3, col4 = st.columns([1.2, 2, 2, 2])
    with col1:
        selected_year = st.selectbox(
            "Year",
            years,
            key="finance_year_focus",
            help="Select year first to scope all finance comparisons."
        )
    with col2:
        sectors_for_year = _fetch_industries(db, selected_year)
        if not sectors_for_year:
            st.info("No sector values available for the selected year.")
            return
        selected_sector = st.selectbox(
            "Sector Focus",
            sectors_for_year,
            key="finance_industry_focus",
            help="FP&A decisions in this view are scoped to one sector at a time."
        )
    with col3:
        sub_sectors = _fetch_sub_sectors(db, selected_year, selected_sector)
        sub_sector_options = ["All Sub-sectors"] + sub_sectors
        selected_sub_sector_raw = st.selectbox(
            "Sub-sector Focus",
            sub_sector_options,
            key="finance_sub_sector_focus",
            help="Optional drill-down to a specific sub-sector within the selected sector."
        )
        selected_sub_sector = None if selected_sub_sector_raw == "All Sub-sectors" else selected_sub_sector_raw
    with col4:
        skill_keyword = st.text_input(
            "Optional Skill/Keyword Focus",
            key="finance_skill_focus",
            placeholder="e.g. python, sap, security"
        ).strip()

    if selected_sub_sector and skill_keyword:
        st.caption(
            f"Scoped to year {selected_year}, sector '{selected_sector}', sub-sector '{selected_sub_sector}', "
            f"and keyword '{skill_keyword}'."
        )
    elif selected_sub_sector:
        st.caption(f"Scoped to year {selected_year}, sector '{selected_sector}', and sub-sector '{selected_sub_sector}'.")
    elif skill_keyword:
        st.caption(f"Scoped to year {selected_year}, sector '{selected_sector}', and keyword '{skill_keyword}'.")
    else:
        st.caption(f"Scoped to year {selected_year} and sector '{selected_sector}'.")

    headline = _fetch_headline_metrics(db, selected_year, selected_sector, selected_sub_sector, skill_keyword)
    row = headline.iloc[0]
    total_postings = int(row["postings"]) if row["postings"] is not None else 0
    if total_postings == 0:
        st.info("No rows match the selected sector/sub-sector/keyword filter.")
        return

    contract_postings = int(row["contract_postings"] or 0)
    permanent_postings = int(row["permanent_postings"] or 0)
    contract_share = _safe_pct(contract_postings, total_postings)

    create_metric_columns(
        {
            "Postings in Finance Model": f"{total_postings:,}",
            "Estimated Vacancy Cost Exposure": format_currency(row["total_budget_exposure"]),
            "Median Exposure per Opening": format_currency(row["median_exposure_per_opening"]),
            "Contract Share of Postings": format_percentage(contract_share),
        }
    )

    st.subheader("Decision 1: Where Contract Conversion Saves vs. Costs")
    st.caption(
        "Compares matched sector and position-level segments to identify whether contract "
        "staffing is a savings, cost premium, or cost neutral."
    )

    summary = _fetch_conversion_decision_summary(db, selected_year, selected_sector, selected_sub_sector, skill_keyword)
    if summary.empty:
        st.info("No conversion segments meet the sample threshold yet.")
    else:
        if selected_sub_sector:
            st.caption(
                "Segment definition: one Position Level within the selected Sector and Sub-sector. "
                "Comparable segments require at least 30 Contract postings and 30 Permanent postings."
            )
        else:
            st.caption(
                "Segment definition: one Sector x Sub-sector x Position Level combination. "
                "Comparable segments require at least 30 Contract postings and 30 Permanent postings."
            )

        display = summary.copy()
        display["avg_delta_rate"] = display["avg_delta_rate"].apply(format_percentage)
        display["median_monthly_delta"] = display["median_monthly_delta"].apply(format_currency)
        st.dataframe(
            display.rename(
                columns={
                    "conversion_decision": "Decision",
                    "segments": "Comparable Segments",
                    "avg_delta_rate": "Avg Cost Delta Rate",
                    "median_monthly_delta": "Median Monthly Delta (Contract - Permanent)",
                }
            ),
            width="stretch",
            hide_index=True,
        )

        st.caption("Top Savings Candidates")
        savings = _fetch_conversion_candidates(db, selected_year, selected_sector, selected_sub_sector, skill_keyword, "Savings")
        if savings.empty:
            st.info("No savings candidates in current dataset.")
        else:
            savings_show = savings.copy()
            savings_show["contract_cost_delta_rate"] = savings_show["contract_cost_delta_rate"].apply(format_percentage)
            savings_show["monthly_cost_delta_contract_minus_permanent"] = savings_show[
                "monthly_cost_delta_contract_minus_permanent"
            ].apply(format_currency)
            st.dataframe(
                savings_show.rename(
                    columns={
                        "sector": "Sector",
                        "sub_sector": "Sub-sector",
                        "position_level": "Position Level",
                        "postings_contract": "Contract Postings",
                        "postings_permanent": "Permanent Postings",
                        "monthly_cost_delta_contract_minus_permanent": "Monthly Delta",
                        "contract_cost_delta_rate": "Delta Rate",
                    }
                ),
                width="stretch",
                hide_index=True,
            )

        st.caption("Top Cost Premium Risks")
        premium = _fetch_conversion_candidates(db, selected_year, selected_sector, selected_sub_sector, skill_keyword, "Cost premium")
        if premium.empty:
            st.info("No cost premium candidates in current dataset.")
        else:
            premium_show = premium.copy()
            premium_show["contract_cost_delta_rate"] = premium_show["contract_cost_delta_rate"].apply(format_percentage)
            premium_show["monthly_cost_delta_contract_minus_permanent"] = premium_show[
                "monthly_cost_delta_contract_minus_permanent"
            ].apply(format_currency)
            st.dataframe(
                premium_show.rename(
                    columns={
                        "sector": "Sector",
                        "sub_sector": "Sub-sector",
                        "position_level": "Position Level",
                        "postings_contract": "Contract Postings",
                        "postings_permanent": "Permanent Postings",
                        "monthly_cost_delta_contract_minus_permanent": "Monthly Delta",
                        "contract_cost_delta_rate": "Delta Rate",
                    }
                ),
                width="stretch",
                hide_index=True,
            )

    st.subheader("Decision 2: Where Vacancy Cost Exposure Concentrates by Position Level")
    top_positions = _fetch_exposure_by_position_level(db, selected_year, selected_sector, selected_sub_sector, skill_keyword, limit=12)
    if top_positions.empty:
        st.info("No exposure records available for this filter.")
    else:
        top_positions = top_positions.sort_values("total_vacancy_budget_exposure", ascending=False).reset_index(drop=True)

        st.caption(
            "This view uses the same Year / Sector / Sub-sector / Keyword filters as Decision 1, "
            "but groups the matching postings by Position Level. The keyword narrows the scope; it is not the grouping dimension."
        )
        chart_data = top_positions[["position_level", "total_vacancy_budget_exposure"]].copy()
        chart = (
            alt.Chart(chart_data)
            .mark_bar(color=PAY_COLOR)
            .encode(
                x=alt.X(
                    "position_level:N",
                    sort="-y",
                    title="Position Level",
                    axis=alt.Axis(labelAngle=-45, labelLimit=0, labelPadding=12),
                ),
                y=alt.Y("total_vacancy_budget_exposure:Q", title="Estimated Vacancy Cost Exposure"),
                tooltip=[
                    alt.Tooltip("position_level:N", title="Position Level"),
                    alt.Tooltip("total_vacancy_budget_exposure:Q", title="Estimated Vacancy Cost Exposure", format=","),
                ],
            )
        )
        st.altair_chart(chart, width="stretch")
        st.caption(
            "Formula: Estimated Vacancy Cost Exposure = estimated loaded monthly cost per opening ÷ 30.3 × posting window days × number of vacancies."
        )

        show = top_positions.copy()
        show["total_vacancy_budget_exposure"] = show["total_vacancy_budget_exposure"].apply(format_currency)
        show["median_exposure_per_opening"] = show["median_exposure_per_opening"].apply(format_currency)
        st.dataframe(
            show.rename(
                columns={
                    "position_level": "Position Level",
                    "postings": "Postings",
                    "vacancies": "Vacancies",
                    "median_posting_window_days": "Median Posting Window (Days)",
                    "total_vacancy_budget_exposure": "Estimated Vacancy Cost Exposure",
                    "median_exposure_per_opening": "Median Exposure per Opening",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    st.subheader("Operational Watchlist: Slow-to-Fill Segments with High Exposure")
    watchlist = _fetch_slowest_expensive_segments(db, selected_year, selected_sector, selected_sub_sector, skill_keyword, limit=15)
    if watchlist.empty:
        st.info("No segment-level exposure watchlist available.")
    else:
        watch = watchlist.copy()
        watch["total_vacancy_budget_exposure"] = watch["total_vacancy_budget_exposure"].apply(format_currency)
        watch["median_exposure_per_opening"] = watch["median_exposure_per_opening"].apply(format_currency)
        st.dataframe(
            watch.rename(
                columns={
                    "sector": "Sector",
                    "sub_sector": "Sub-sector",
                    "position_level": "Position Level",
                    "employment_cohort": "Cohort",
                    "postings": "Postings",
                    "vacancies": "Vacancies",
                    "median_posting_window_days": "Median Posting Window (Days)",
                    "total_vacancy_budget_exposure": "Total Budget Exposure",
                    "median_exposure_per_opening": "Median Exposure per Opening",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    st.subheader("Scenario Inputs")
    scenario = _fetch_scenario(db)
    if not scenario.empty:
        st.caption(
            "Scenario inputs are display-only assumptions used to build the finance tables; they are not editable in the dashboard."
        )
        st.dataframe(scenario, width="stretch", hide_index=True)
