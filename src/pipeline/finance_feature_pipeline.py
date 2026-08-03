"""Finance feature pipeline.

Builds Finance Business Partner workforce-cost and budget-risk features in
Python/Pandas from the processed ``jobs`` table, then writes only final
DataFrames into DuckDB feature tables.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import duckdb

from config.settings import DUCKDB_FILE


PERMANENT_EMPLOYER_BURDEN_RATE = 0.17
CONTRACT_EMPLOYER_BURDEN_RATE = 0.02
CONTRACT_AGENCY_PREMIUM_RATE = 0.12
DAYS_PER_MONTH = 30.3
COST_NEUTRAL_TOLERANCE_RATE = 0.03
SALARY_PLANNING_CAP_QUANTILE = 0.995
MIN_COHORT_POSTINGS = 30


def _build_scenario_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "permanent_employer_burden_rate": PERMANENT_EMPLOYER_BURDEN_RATE,
                "contract_employer_burden_rate": CONTRACT_EMPLOYER_BURDEN_RATE,
                "contract_agency_premium_rate": CONTRACT_AGENCY_PREMIUM_RATE,
                "days_per_month": DAYS_PER_MONTH,
                "cost_neutral_tolerance_rate": COST_NEUTRAL_TOLERANCE_RATE,
                "salary_planning_cap_quantile": SALARY_PLANNING_CAP_QUANTILE,
                "min_cohort_postings": MIN_COHORT_POSTINGS,
            }
        ]
    )


def _classify_employment_cohort(job_type: pd.Series) -> pd.Series:
    text = job_type.fillna("").str.lower()
    is_permanent = text.str.contains("permanent|full time|full-time", regex=True)
    is_contract = text.str.contains("contract|temporary|freelance|flexi", regex=True)
    return pd.Series(
        np.select([is_permanent, is_contract], ["Permanent", "Contract"], default="Other"),
        index=job_type.index,
    )


def _assign_pwm_candidate(df: pd.DataFrame) -> pd.Series:
    rules = [
        ("Cleaning", r"\b(?:cleaner|cleaning|housekeep(?:er|ing))\b", ["Environment / Health", "General Work", "Hospitality"]),
        ("Security", r"\b(?:security officer|security guard|security supervisor|guard)\b", ["Security and Investigation"]),
        ("Landscape", r"\b(?:landscap(?:e|ing)|gardener|horticultur)\b", ["Environment / Health", "General Work"]),
        ("Lift and escalator", r"\b(?:lift|escalator)\b", ["Repair and Maintenance", "Engineering"]),
        ("Retail", r"\b(?:retail|cashier|shop assistant)\b", ["Sales / Retail"]),
        ("Food services", r"\b(?:barista|waiter|waitress|kitchen|service crew|cook)\b", ["F&B"]),
        ("Waste management", r"\b(?:waste|refuse|recycl)\b", ["Environment / Health", "General Work"]),
    ]

    candidate = pd.Series(pd.NA, index=df.index, dtype="object")
    title_text = df["title"].fillna("")
    for sector, pattern, industries in rules:
        mask = (
            candidate.isna()
            & title_text.str.contains(pattern, case=False, regex=True)
            & df["sector"].isin(industries)
        )
        candidate.loc[mask] = sector
    return candidate


def _build_finance_job_features(jobs: pd.DataFrame) -> pd.DataFrame:
    df = jobs.copy()

    df["sector"] = df["sector"].fillna("Unclassified")
    df["sub_sector"] = df["sub_sector"].fillna("Unspecified")
    df["employment_type"] = df["job_type"]
    df["salary_minimum"] = df["salary_min"]
    df["salary_maximum"] = df["salary_max"]
    df["salary_midpoint_monthly"] = (df["salary_minimum"] + df["salary_maximum"]) / 2.0
    df["salary_type"] = "Monthly"
    df["number_of_vacancies"] = df["vacancies"].fillna(0)

    floor = df["salary_midpoint_monthly"].quantile(1 - SALARY_PLANNING_CAP_QUANTILE)
    cap = df["salary_midpoint_monthly"].quantile(SALARY_PLANNING_CAP_QUANTILE)
    df["salary_low_outlier_flag"] = df["salary_midpoint_monthly"].lt(floor).fillna(False)
    df["salary_high_outlier_flag"] = df["salary_midpoint_monthly"].gt(cap).fillna(False)
    df["planning_salary_midpoint_monthly"] = df["salary_midpoint_monthly"].clip(lower=floor, upper=cap)

    posting_window = (df["expiry_date"] - df["posting_date"]).dt.days
    df["posting_window_days"] = posting_window.clip(lower=0)
    df["new_posting_lag_days"] = pd.NA

    df["employment_cohort"] = _classify_employment_cohort(df["employment_type"])
    df["employer_burden_rate"] = np.select(
        [df["employment_cohort"].eq("Permanent"), df["employment_cohort"].eq("Contract")],
        [PERMANENT_EMPLOYER_BURDEN_RATE, CONTRACT_EMPLOYER_BURDEN_RATE],
        default=0.0,
    )
    df["agency_premium_rate"] = np.where(df["employment_cohort"].eq("Contract"), CONTRACT_AGENCY_PREMIUM_RATE, 0.0)
    df["total_cost_multiplier"] = 1 + df["employer_burden_rate"] + df["agency_premium_rate"]

    df["loaded_monthly_cost_per_head"] = df["planning_salary_midpoint_monthly"] * df["total_cost_multiplier"]
    df["loaded_monthly_cost_for_vacancies"] = df["loaded_monthly_cost_per_head"] * df["number_of_vacancies"]
    df["daily_loaded_cost_for_vacancies"] = df["loaded_monthly_cost_for_vacancies"] / DAYS_PER_MONTH
    df["vacancy_budget_exposure"] = df["daily_loaded_cost_for_vacancies"] * df["posting_window_days"]

    safe_vacancies = df["number_of_vacancies"].replace(0, np.nan)
    df["vacancy_exposure_per_opening"] = df["vacancy_budget_exposure"] / safe_vacancies

    df["pwm_sector_candidate"] = _assign_pwm_candidate(df)
    df["pwm_monthly_floor"] = pd.Series(pd.NA, index=df.index, dtype="Float64")
    df["pwm_salary_check_status"] = np.where(
        df["pwm_sector_candidate"].notna(),
        "policy_floor_not_configured",
        "not_a_pwm_sector_candidate",
    )
    df["salary_frequency_interpretation"] = "monthly_as_declared"
    df["salary_frequency_review_required"] = False

    return df[
        [
            "job_id",
            "title",
            "company",
            "sector",
            "sub_sector",
            "position_level",
            "employment_type",
            "salary_minimum",
            "salary_maximum",
            "salary_midpoint_monthly",
            "salary_type",
            "posting_date",
            "expiry_date",
            "number_of_vacancies",
            "repost_count",
            "posting_window_days",
            "new_posting_lag_days",
            "employment_cohort",
            "salary_low_outlier_flag",
            "salary_high_outlier_flag",
            "planning_salary_midpoint_monthly",
            "employer_burden_rate",
            "agency_premium_rate",
            "total_cost_multiplier",
            "loaded_monthly_cost_per_head",
            "loaded_monthly_cost_for_vacancies",
            "daily_loaded_cost_for_vacancies",
            "vacancy_budget_exposure",
            "vacancy_exposure_per_opening",
            "pwm_sector_candidate",
            "pwm_monthly_floor",
            "pwm_salary_check_status",
            "salary_frequency_interpretation",
            "salary_frequency_review_required",
        ]
    ]


def _build_industry_budget_risk(finance_jobs: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        finance_jobs.groupby("sector", as_index=False)
        .agg(
            postings=("job_id", "nunique"),
            vacancies=("number_of_vacancies", "sum"),
            median_posting_window_days=("posting_window_days", "median"),
            p90_posting_window_days=("posting_window_days", lambda s: s.quantile(0.90)),
            total_vacancy_budget_exposure=("vacancy_budget_exposure", "sum"),
            median_exposure_per_opening=("vacancy_exposure_per_opening", "median"),
        )
        .sort_values("total_vacancy_budget_exposure", ascending=False)
        .reset_index(drop=True)
    )
    grouped["budget_exposure_rank"] = np.arange(1, len(grouped) + 1)
    return grouped


def _build_conversion_economics(finance_jobs: pd.DataFrame) -> pd.DataFrame:
    cohort = (
        finance_jobs[finance_jobs["employment_cohort"].isin(["Permanent", "Contract"])]
        .groupby(["sector", "position_level", "employment_cohort"], as_index=False)
        .agg(
            postings=("job_id", "nunique"),
            median_loaded_monthly_cost=("loaded_monthly_cost_per_head", "median"),
            median_posting_window_days=("posting_window_days", "median"),
        )
    )

    if cohort.empty:
        return pd.DataFrame(
            columns=[
                "sector",
                "position_level",
                "postings_contract",
                "postings_permanent",
                "median_loaded_monthly_cost_contract",
                "median_loaded_monthly_cost_permanent",
                "median_posting_window_days_contract",
                "median_posting_window_days_permanent",
                "monthly_cost_delta_contract_minus_permanent",
                "contract_cost_delta_rate",
                "conversion_decision",
            ]
        )

    pivot = cohort.pivot(
        index=["sector", "position_level"],
        columns="employment_cohort",
        values=["postings", "median_loaded_monthly_cost", "median_posting_window_days"],
    )

    pivot.columns = [f"{metric}_{cohort_name.lower()}" for metric, cohort_name in pivot.columns]
    out = pivot.reset_index()

    required_cols = [
        "median_loaded_monthly_cost_contract",
        "median_loaded_monthly_cost_permanent",
        "postings_contract",
        "postings_permanent",
    ]
    for col in required_cols:
        if col not in out.columns:
            out[col] = np.nan

    out = out.dropna(subset=["median_loaded_monthly_cost_contract", "median_loaded_monthly_cost_permanent"])
    out = out[
        (out["postings_contract"] >= MIN_COHORT_POSTINGS)
        & (out["postings_permanent"] >= MIN_COHORT_POSTINGS)
    ].copy()

    if out.empty:
        return out

    out["monthly_cost_delta_contract_minus_permanent"] = (
        out["median_loaded_monthly_cost_contract"] - out["median_loaded_monthly_cost_permanent"]
    )
    out["contract_cost_delta_rate"] = (
        out["monthly_cost_delta_contract_minus_permanent"] / out["median_loaded_monthly_cost_permanent"]
    )
    out["conversion_decision"] = np.select(
        [
            out["contract_cost_delta_rate"] <= -COST_NEUTRAL_TOLERANCE_RATE,
            out["contract_cost_delta_rate"] >= COST_NEUTRAL_TOLERANCE_RATE,
        ],
        ["Savings", "Cost premium"],
        default="Cost neutral",
    )

    return out.sort_values("monthly_cost_delta_contract_minus_permanent")


def _write_table(conn: duckdb.DuckDBPyConnection, table_name: str, df: pd.DataFrame) -> None:
    normalized = df.copy()

    # DuckDB + Python 3.14 has shown instability with some pandas nullable
    # extension dtypes in registered DataFrames; persist plain NumPy/object
    # dtypes and Python None/NaN instead.
    for col in normalized.columns:
        series = normalized[col]
        if pd.api.types.is_integer_dtype(series.dtype) and series.isna().any():
            normalized[col] = series.astype("float64")
        elif pd.api.types.is_string_dtype(series.dtype) or pd.api.types.is_categorical_dtype(series.dtype):
            normalized[col] = series.astype("object")
        elif pd.api.types.is_bool_dtype(series.dtype) and series.isna().any():
            normalized[col] = series.astype("object")

    normalized = normalized.where(pd.notna(normalized), None)

    conn.register("tmp_df", normalized)
    conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM tmp_df")
    conn.unregister("tmp_df")


def materialize_finance_feature_tables(db_path: str | None = None) -> dict[str, int]:
    """Build finance feature tables from ``jobs`` with Python transformations.

    Returns row counts for each materialized table.
    """
    if db_path is None:
        db_path = DUCKDB_FILE

    conn = duckdb.connect(db_path)
    try:
        jobs = conn.execute(
            """
            SELECT
                job_id,
                title,
                company,
                sector,
                sub_sector,
                position_level,
                job_type,
                salary_min,
                salary_max,
                posting_date,
                expiry_date,
                vacancies,
                repost_count
            FROM jobs
            """
        ).df()

        scenario_df = _build_scenario_df()
        finance_jobs_df = _build_finance_job_features(jobs)
        industry_risk_df = _build_industry_budget_risk(finance_jobs_df)
        conversion_df = _build_conversion_economics(finance_jobs_df)

        _write_table(conn, "finance_scenario_params", scenario_df)
        _write_table(conn, "finance_job_features", finance_jobs_df)
        _write_table(conn, "finance_industry_budget_risk", industry_risk_df)
        _write_table(conn, "finance_permanent_contract_conversion_economics", conversion_df)

        return {
            "finance_scenario_params": len(scenario_df),
            "finance_job_features": len(finance_jobs_df),
            "finance_industry_budget_risk": len(industry_risk_df),
            "finance_permanent_contract_conversion_economics": len(conversion_df),
        }
    finally:
        conn.close()
