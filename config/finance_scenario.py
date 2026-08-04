"""Finance scenario parameters -- single source of truth.

``finance_scenario.json`` holds the workforce-cost assumptions Finance can
tune (employer burden rates, agency premium, days per month, the
cost-neutral tolerance band). The dashboard reads this file fresh on every
render and computes loaded costs at query time, so editing a value here
takes effect on the next dashboard rerun -- no pipeline reload needed.

``salary_planning_cap_quantile`` and ``min_cohort_postings`` are the
exception: they govern which rows the pipeline keeps (outlier capping, the
minimum sample size for a comparable segment), which requires a full-table
pass. Changing those still needs ``python -m src.pipeline.pipeline``.
"""

from __future__ import annotations

import json
from pathlib import Path

FINANCE_SCENARIO_PATH = Path(__file__).resolve().parent / "finance_scenario.json"

DEFAULT_FINANCE_SCENARIO = {
    "permanent_employer_burden_rate": 0.22,
    "contract_employer_burden_rate": 0.02,
    "contract_agency_premium_rate": 0.12,
    "days_per_month": 30.3,
    "cost_neutral_tolerance_rate": 0.03,
    "salary_planning_cap_quantile": 0.995,
    "min_cohort_postings": 30,
}


def load_finance_scenario() -> dict:
    """Read the finance scenario assumptions, falling back to defaults for
    any key the file doesn't set."""
    if FINANCE_SCENARIO_PATH.exists():
        with open(FINANCE_SCENARIO_PATH) as fh:
            overrides = json.load(fh)
        return {**DEFAULT_FINANCE_SCENARIO, **overrides}
    return dict(DEFAULT_FINANCE_SCENARIO)
