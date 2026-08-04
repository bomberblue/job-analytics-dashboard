"""Finance Business Partner dashboard view."""

import altair as alt
import pandas as pd
import streamlit as st

from config.finance_scenario import load_finance_scenario
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


def _priced_job_features_sql(params: dict) -> str:
    """finance_job_features, with its loaded-cost columns recomputed from the
    CURRENT scenario parameters instead of whatever rates were baked in at
    the last pipeline run. Editing config/finance_scenario.json takes effect
    on the next dashboard rerun -- no pipeline reload needed."""
    burden_case = (
        "CASE WHEN employment_cohort = 'Permanent' THEN {perm} "
        "WHEN employment_cohort = 'Contract' THEN {contract} ELSE 0.0 END"
    ).format(
        perm=params["permanent_employer_burden_rate"],
        contract=params["contract_employer_burden_rate"],
    )
    premium_case = "CASE WHEN employment_cohort = 'Contract' THEN {a} ELSE 0.0 END".format(
        a=params["contract_agency_premium_rate"]
    )
    days_per_month = params["days_per_month"]
    return f"""
        (
            WITH rated AS (
                SELECT
                    * EXCLUDE (
                        employer_burden_rate, agency_premium_rate, total_cost_multiplier,
                        loaded_monthly_cost_per_head, loaded_monthly_cost_for_vacancies,
                        daily_loaded_cost_for_vacancies, vacancy_budget_exposure,
                        vacancy_exposure_per_opening
                    ),
                    {burden_case} AS employer_burden_rate,
                    {premium_case} AS agency_premium_rate
                FROM finance_job_features
            ),
            costed AS (
                SELECT
                    *,
                    planning_salary_midpoint_monthly * (1 + employer_burden_rate + agency_premium_rate)
                        AS loaded_monthly_cost_per_head
                FROM rated
            ),
            exposed AS (
                SELECT
                    *,
                    loaded_monthly_cost_per_head * number_of_vacancies AS loaded_monthly_cost_for_vacancies,
                    (loaded_monthly_cost_per_head * number_of_vacancies) / {days_per_month}
                        AS daily_loaded_cost_for_vacancies
                FROM costed
            )
            SELECT
                *,
                daily_loaded_cost_for_vacancies * posting_window_days AS vacancy_budget_exposure,
                CASE WHEN number_of_vacancies = 0 THEN NULL
                     ELSE (daily_loaded_cost_for_vacancies * posting_window_days) / number_of_vacancies
                END AS vacancy_exposure_per_opening
            FROM exposed
        )
    """


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


def _fetch_headline_metrics(db, params: dict, year: int, sector: str, sub_sector: str | None, skill_keyword: str | None):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    priced = _priced_job_features_sql(params)
    return db.query(
        f"""
        SELECT
            COUNT(*) AS postings,
            SUM(vacancy_budget_exposure) AS total_budget_exposure,
            MEDIAN(vacancy_exposure_per_opening) AS median_exposure_per_opening,
            MEDIAN(loaded_monthly_cost_per_head) AS median_loaded_monthly_cost_per_head,
            SUM(CASE WHEN employment_cohort = 'Contract' THEN 1 ELSE 0 END) AS contract_postings,
            SUM(CASE WHEN employment_cohort = 'Permanent' THEN 1 ELSE 0 END) AS permanent_postings
        FROM {priced} f
        {where}
        """
    )


# market_overview.py's fetch_contract_premium re-derives this same Contract-vs-
# Permanent cohort comparison at coarser (sector-only) grain for its cross-view
# correlation; mirror any change to the cohort definition or sample threshold
# there too.
def _conversion_base_sql(where: str, params: dict) -> str:
    priced = _priced_job_features_sql(params)
    tolerance = params["cost_neutral_tolerance_rate"]
    min_postings = int(params["min_cohort_postings"])
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
            FROM {priced} f
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
                    / NULLIF(median_loaded_monthly_cost_permanent, 0)) <= -{tolerance} THEN 'Savings'
                WHEN ((median_loaded_monthly_cost_contract - median_loaded_monthly_cost_permanent)
                    / NULLIF(median_loaded_monthly_cost_permanent, 0)) >= {tolerance} THEN 'Cost premium'
                ELSE 'Cost neutral'
            END AS conversion_decision
        FROM pivoted
        WHERE postings_contract >= {min_postings}
          AND postings_permanent >= {min_postings}
          AND median_loaded_monthly_cost_contract IS NOT NULL
          AND median_loaded_monthly_cost_permanent IS NOT NULL
    """


def _fetch_conversion_decision_summary(db, params: dict, year: int, sector: str, sub_sector: str | None, skill_keyword: str | None):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    base_sql = _conversion_base_sql(where, params)
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
    params: dict,
    year: int,
    sector: str,
    sub_sector: str | None,
    skill_keyword: str | None,
    decision: str,
    limit=15,
):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    base_sql = _conversion_base_sql(where, params)
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


def _fetch_exposure_by_position_level(db, params: dict, year: int, sector: str, sub_sector: str | None, skill_keyword: str | None, limit=12):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    priced = _priced_job_features_sql(params)
    return db.query(
        f"""
        SELECT
            position_level,
            COUNT(*) AS postings,
            SUM(number_of_vacancies) AS vacancies,
            MEDIAN(posting_window_days) AS median_posting_window_days,
            SUM(vacancy_budget_exposure) AS total_vacancy_budget_exposure,
            MEDIAN(vacancy_exposure_per_opening) AS median_exposure_per_opening
        FROM {priced} f
        {where}
        GROUP BY position_level
        HAVING SUM(number_of_vacancies) > 0
        ORDER BY total_vacancy_budget_exposure DESC
        LIMIT {int(limit)}
        """
    )


def _fetch_slowest_expensive_segments(db, params: dict, year: int, sector: str, sub_sector: str | None, skill_keyword: str | None, limit=15):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    priced = _priced_job_features_sql(params)
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
        FROM {priced} f
        {where}
        GROUP BY sector, sub_sector, position_level, employment_cohort
        HAVING SUM(number_of_vacancies) > 0
        ORDER BY total_vacancy_budget_exposure DESC
        LIMIT {int(limit)}
        """
    )


def _employment_segment_case(alias: str = "f") -> str:
    return f"""
        CASE
            WHEN regexp_matches(lower(COALESCE({alias}.employment_type, '')), 'permanent|full[ -]?time') THEN 'Permanent'
            WHEN regexp_matches(lower(COALESCE({alias}.employment_type, '')), 'contract') THEN 'Contract'
            WHEN regexp_matches(lower(COALESCE({alias}.employment_type, '')), 'temp|temporary|part[ -]?time|intern|attachment|freelance|flexi') THEN 'Temp'
            ELSE 'Other'
        END
    """


def _fetch_recruitment_type_overview(db, params: dict, year: int, sector: str, sub_sector: str | None, skill_keyword: str | None):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    type_case = _employment_segment_case("f")
    priced = _priced_job_features_sql(params)
    return db.query(
        f"""
        WITH typed AS (
            SELECT
                {type_case} AS recruitment_type,
                f.job_id,
                f.number_of_vacancies,
                f.planning_salary_midpoint_monthly,
                f.posting_window_days,
                f.vacancy_budget_exposure
            FROM {priced} f
            {where}
        )
        SELECT
            recruitment_type,
            COUNT(*) AS postings,
            SUM(number_of_vacancies) AS vacancies,
            MEDIAN(planning_salary_midpoint_monthly) AS median_salary_midpoint,
            MEDIAN(posting_window_days) AS median_posting_window_days,
            SUM(vacancy_budget_exposure) AS total_budget_exposure
        FROM typed
        WHERE recruitment_type IN ('Permanent', 'Contract', 'Temp')
        GROUP BY recruitment_type
        ORDER BY CASE recruitment_type
            WHEN 'Permanent' THEN 1
            WHEN 'Contract' THEN 2
            WHEN 'Temp' THEN 3
            ELSE 4
        END
        """
    )


def _fetch_recruitment_type_monthly_trend(db, params: dict, year: int, sector: str, sub_sector: str | None, skill_keyword: str | None):
    where = _build_where_clause(year, sector, sub_sector, skill_keyword)
    priced = _priced_job_features_sql(params)
    return db.query(
        f"""
        WITH typed AS (
            SELECT
                date_trunc('month', f.posting_date) AS posting_month,
                f.employment_type AS recruitment_type,
                f.number_of_vacancies,
                f.vacancy_budget_exposure
            FROM {priced} f
            {where}
              AND f.posting_date IS NOT NULL
              AND f.employment_type IS NOT NULL
        )
        SELECT
            posting_month,
            recruitment_type,
            COUNT(*) AS postings,
            SUM(number_of_vacancies) AS vacancies,
            SUM(vacancy_budget_exposure) AS total_budget_exposure
        FROM typed
        GROUP BY posting_month, recruitment_type
        ORDER BY posting_month, recruitment_type
        """
    )


def _fetch_scenario(params: dict):
    return pd.DataFrame([params])


def _safe_pct(numerator, denominator):
    if denominator in (0, None):
        return None
    return 100.0 * numerator / denominator


def _format_conversion_candidates_table(df):
    """Rename conversion-candidate columns to dashboard labels and group the
    loaded-cost columns under a shared "Loaded Cost (Monthly)" header."""
    show = df.copy()
    show["contract_cost_delta_rate"] = show["contract_cost_delta_rate"].apply(lambda v: format_percentage(v * 100))
    show["monthly_cost_delta_contract_minus_permanent"] = show[
        "monthly_cost_delta_contract_minus_permanent"
    ].apply(format_currency)

    show = show.rename(
        columns={
            "sector": "Sector",
            "sub_sector": "Sub-sector",
            "position_level": "Position Level",
            "postings_contract": "Contract Postings",
            "postings_permanent": "Permanent Postings",
            "median_loaded_monthly_cost_contract": "Contract",
            "median_loaded_monthly_cost_permanent": "Permanent",
            "monthly_cost_delta_contract_minus_permanent": "Delta",
            "contract_cost_delta_rate": "Delta Rate",
            "conversion_decision": "Decision",
        }
    )

    loaded_cost_columns = {"Contract", "Permanent", "Delta", "Delta Rate"}
    show.columns = pd.MultiIndex.from_tuples(
        [("Loaded Cost (Monthly)", c) if c in loaded_cost_columns else ("", c) for c in show.columns]
    )
    return show


def render_finance_view():
    """Render Finance Business Partner view for workforce-cost and budget risk.
    No header - the nav chip above already names the board."""
    st.caption(
        "Translate workforce mix and hiring-speed decisions into dollars, so Finance can "
        "approve or challenge contract-vs-permanent budget shifts."
    )

    db = st.session_state.db
    if not _finance_tables_ready(db):
        _render_missing_tables_message()
        return

    # Loaded fresh on every rerun: editing config/finance_scenario.json changes
    # every cost figure below on the next interaction, no pipeline reload needed.
    params = load_finance_scenario()

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
            "Sector",
            sectors_for_year,
            key="finance_industry_focus",
            help="FP&A decisions in this view are scoped to one sector at a time."
        )
    with col3:
        sub_sectors = _fetch_sub_sectors(db, selected_year, selected_sector)
        sub_sector_options = ["All Sub-sectors"] + sub_sectors
        selected_sub_sector_raw = st.selectbox(
            "Sub-sector",
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

    headline = _fetch_headline_metrics(db, params, selected_year, selected_sector, selected_sub_sector, skill_keyword)
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

    tab_recruitment, tab_decision_1, tab_decision_2 = st.tabs(
        [
            "Recruitment Trend",
            "Decision 1: Contract Conversion",
            "Decision 2: Exposure Concentration",
        ]
    )

    with tab_recruitment:
        st.subheader("Recruitment Mix Overview for Segment of Interest")
        st.caption(
            "Shows Permanent, Contract, and Temp recruitment mix for the current Year / Sector / "
            "Sub-sector / Keyword scope."
        )

        overview = _fetch_recruitment_type_overview(db, params, selected_year, selected_sector, selected_sub_sector, skill_keyword)
        if overview.empty:
            st.info("No Permanent/Contract/Temp postings found in the selected scope.")
        else:
            total_type_postings = int(overview["postings"].sum())
            mix = overview.copy()
            mix["postings_share_pct"] = mix["postings"].apply(
                lambda v: _safe_pct(v, total_type_postings)
            )

            create_metric_columns(
                {
                    "Permanent Postings": f"{int(mix.loc[mix['recruitment_type'] == 'Permanent', 'postings'].sum()):,}",
                    "Contract Postings": f"{int(mix.loc[mix['recruitment_type'] == 'Contract', 'postings'].sum()):,}",
                    "Temp Postings": f"{int(mix.loc[mix['recruitment_type'] == 'Temp', 'postings'].sum()):,}",
                    "Tracked Mix Coverage": format_percentage(_safe_pct(total_type_postings, total_postings)),
                }
            )

            mix_show = mix.copy()
            mix_show["postings_share_pct"] = mix_show["postings_share_pct"].apply(format_percentage)
            mix_show["median_salary_midpoint"] = mix_show["median_salary_midpoint"].apply(format_currency)
            mix_show["total_budget_exposure"] = mix_show["total_budget_exposure"].apply(format_currency)
            st.dataframe(
                mix_show.rename(
                    columns={
                        "recruitment_type": "Recruitment Type",
                        "postings": "Postings",
                        "postings_share_pct": "Share of Scoped Postings",
                        "vacancies": "Vacancies",
                        "median_salary_midpoint": "Median Salary Midpoint",
                        "median_posting_window_days": "Median Posting Window (Days)",
                        "total_budget_exposure": "Estimated Vacancy Cost Exposure",
                    }
                ),
                width="stretch",
                hide_index=True,
            )

        st.subheader("Recruitment Trend by Type (Monthly)")
        trend = _fetch_recruitment_type_monthly_trend(db, params, selected_year, selected_sector, selected_sub_sector, skill_keyword)
        if trend.empty:
            st.info("No monthly trend data available for recruitment types in this scope.")
        else:
            # Fixed hue order (validated 8-slot categorical palette), assigned by entity
            # so a type keeps its color regardless of which others are shown/filtered.
            type_colors = {
                "Permanent": "#2a78d6",
                "Full Time": "#eb6834",
                "Contract": "#1baf7a",
                "Temporary": "#eda100",
                "Part Time": "#e87ba4",
                "Internship/Attachment": "#008300",
                "Freelance": "#4a3aa7",
                "Flexi-work": "#e34948",
            }
            present_types = set(trend["recruitment_type"])
            type_domain = [t for t in type_colors if t in present_types]
            # Any employment_type not in the fixed palette above folds into a neutral slot.
            type_domain += sorted(present_types - set(type_colors))
            for t in type_domain:
                type_colors.setdefault(t, "#9e9e9e")
            default_types = [t for t in ("Permanent", "Contract") if t in type_domain]

            st.caption("Click a recruitment type below to show or hide its line. Permanent and Contract are shown by default.")
            selected_types = st.pills(
                "Recruitment types shown",
                type_domain,
                selection_mode="multi",
                default=default_types,
                key="finance_recruitment_trend_types",
                label_visibility="collapsed",
            )

            if not selected_types:
                st.info("Select at least one recruitment type to display the trend.")
            else:
                shown_types = [t for t in type_domain if t in set(selected_types)]
                trend_filtered = trend[trend["recruitment_type"].isin(shown_types)]
                type_range = [type_colors[t] for t in shown_types]
                trend_chart = (
                    alt.Chart(trend_filtered)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("posting_month:T", title="Posting Month"),
                        y=alt.Y("postings:Q", title="Postings"),
                        color=alt.Color(
                            "recruitment_type:N",
                            title="Recruitment Type",
                            scale=alt.Scale(domain=shown_types, range=type_range),
                        ),
                        tooltip=[
                            alt.Tooltip("posting_month:T", title="Posting Month"),
                            alt.Tooltip("recruitment_type:N", title="Recruitment Type"),
                            alt.Tooltip("postings:Q", title="Postings", format=","),
                            alt.Tooltip("vacancies:Q", title="Vacancies", format=","),
                            alt.Tooltip("total_budget_exposure:Q", title="Vacancy Cost Exposure", format=","),
                        ],
                    )
                )
                st.altair_chart(trend_chart, width="stretch")

            trend_show = trend.copy()
            trend_show["total_budget_exposure"] = trend_show["total_budget_exposure"].apply(format_currency)
            st.dataframe(
                trend_show.rename(
                    columns={
                        "posting_month": "Posting Month",
                        "recruitment_type": "Recruitment Type",
                        "postings": "Postings",
                        "vacancies": "Vacancies",
                        "total_budget_exposure": "Estimated Vacancy Cost Exposure",
                    }
                ),
                width="stretch",
                hide_index=True,
            )

    with tab_decision_1:
        st.subheader("Decision 1: Where Contract Conversion Saves vs. Costs")
        st.caption(
            "Compares matched sector and position-level segments to identify whether contract "
            "staffing is a savings, cost premium, or cost neutral."
        )

        summary = _fetch_conversion_decision_summary(db, params, selected_year, selected_sector, selected_sub_sector, skill_keyword)
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
            display["avg_delta_rate"] = display["avg_delta_rate"].apply(lambda v: format_percentage(v * 100))
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
            savings = _fetch_conversion_candidates(db, params, selected_year, selected_sector, selected_sub_sector, skill_keyword, "Savings")
            if savings.empty:
                st.info("No savings candidates in current dataset.")
            else:
                st.dataframe(
                    _format_conversion_candidates_table(savings),
                    width="stretch",
                    hide_index=True,
                )

            st.caption("Top Cost Premium Risks")
            premium = _fetch_conversion_candidates(db, params, selected_year, selected_sector, selected_sub_sector, skill_keyword, "Cost premium")
            if premium.empty:
                st.info("No cost premium candidates in current dataset.")
            else:
                st.dataframe(
                    _format_conversion_candidates_table(premium),
                    width="stretch",
                    hide_index=True,
                )

    with tab_decision_2:
        st.subheader("Decision 2: Where Vacancy Cost Exposure Concentrates by Position Level")
        top_positions = _fetch_exposure_by_position_level(db, params, selected_year, selected_sector, selected_sub_sector, skill_keyword, limit=12)
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
        watchlist = _fetch_slowest_expensive_segments(db, params, selected_year, selected_sector, selected_sub_sector, skill_keyword, limit=15)
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

    #st.subheader("Scenario Inputs")
    # scenario = _fetch_scenario(params)
    # st.caption(
    #    "Read live from config/finance_scenario.json on every load; every cost figure above reflects "
    #        "these values immediately. Not editable from within the dashboard itself."
    # )
    # st.dataframe(scenario, width="stretch", hide_index=True)
