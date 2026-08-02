"""
Data access layer for the dashboard.

Chart code consumes the plain DataFrames returned here and never touches
storage. `_load_jobs()` is the single seam where the backend is chosen --
parquet today; a duckdb branch slots in beside it without touching any
consumer.

Cohort definitions and constants mirror notebooks/hirer_layer1_analysis.ipynb
and hirer_layer2_analysis.ipynb -- see those for the reasoning.
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

DATA_SOURCE = os.environ.get('JOBS_DATA_SOURCE', 'parquet')
PARQUET_PATH = Path(__file__).resolve().parents[2] / 'data' / 'processed' / 'jobs_enriched.parquet'

MIN_N = 30                  # smallest cell we will quote a figure from
CRAWL_DATE = '2023-07-01'   # inferred counter-freeze boundary -- layer 1 notebook s.1

YR_BINS = [-1, 0, 1, 2, 3, 5, 8, 100]
YR_LABELS = ['0', '1', '2', '3', '4-5', '6-8', '9+']

PAY_BINS = [-1, 2999, 4999, 7999, 1e12]
PAY_LABELS = ['Entry (< $3k)', 'Mid ($3-5k)', 'Senior ($5-8k)', 'Executive (> $8k)']

EXP_ORDER = ['Entry Level', 'Mid Level', 'Senior']


def _load_jobs() -> pd.DataFrame:
    """The backend seam. Add a duckdb branch here when that source lands."""
    if DATA_SOURCE == 'parquet':
        return pd.read_parquet(PARQUET_PATH)
    raise ValueError(f'unknown JOBS_DATA_SOURCE: {DATA_SOURCE!r}')


# cache_resource, not cache_data: cache_data would deep-copy the 1M-row frame
# on every access. The frame is shared read-only; consumers must not mutate it.
@st.cache_resource(show_spinner='Loading job postings…')
def _market() -> pd.DataFrame:
    """Deduplicated market with the derived columns every chart needs."""
    df = _load_jobs()
    mkt = df.drop_duplicates(subset='dup_group_id', keep='first').copy()
    mkt['salary_midpoint'] = mkt.salary_midpoint.astype('float64')
    mkt['counters_complete'] = mkt.expiry_date <= pd.Timestamp(CRAWL_DATE)
    mkt['yrs_bucket'] = pd.cut(mkt.seniority_years, YR_BINS, labels=YR_LABELS)
    mkt['pay_band'] = pd.cut(mkt.salary_midpoint, PAY_BINS, labels=PAY_LABELS)
    return mkt


def _layer2_cohort() -> pd.DataFrame:
    """Counters complete + 30-day listings: the pool where response is measurable."""
    mkt = _market()
    return mkt[mkt.counters_complete & (mkt.listing_days == 30)]


# --- configuration the hirer picks -------------------------------------------

@st.cache_data
def sector_list() -> list:
    return sorted(_market().sector.dropna().unique().tolist())


@st.cache_data
def position_levels() -> list:
    """Ordered by that level's median required experience, as layer 2 s.7 ranks them."""
    mkt = _market()
    return (mkt.groupby('position_level', observed=True).seniority_years
               .median().sort_values().index.astype(str).tolist())


@st.cache_data
def experience_levels() -> list:
    present = set(_market().experience_level.dropna().unique())
    return [e for e in EXP_ORDER if e in present]


def pay_band_for(salary: float | None) -> str | None:
    """Which pay band a planned salary falls in (cut on midpoint -- layer 2 s.1.5)."""
    if salary is None or pd.isna(salary):
        return None
    return str(pd.cut([float(salary)], PAY_BINS, labels=PAY_LABELS)[0])


def yrs_bucket_for(years: int | None) -> str | None:
    if years is None:
        return None
    return str(pd.cut([int(years)], YR_BINS, labels=YR_LABELS)[0])


# --- 1. salary benchmarks (layer 1 s.3) --------------------------------------

def _benchmark(frame: pd.DataFrame, keys: list) -> pd.DataFrame:
    """Salary percentiles per cell, suppressing cells too small to quote."""
    out = frame.groupby(keys, observed=True).agg(
        n=('salary_midpoint', 'size'),
        mid_p25=('salary_midpoint', lambda s: s.quantile(.25)),
        mid_p50=('salary_midpoint', 'median'),
        mid_p75=('salary_midpoint', lambda s: s.quantile(.75)),
    ).round(0)
    return out[out.n >= MIN_N]


GRAIN_NAMES = {'sector': 'sector', 'position_level': 'level',
               'experience_level': 'experience'}

# The order in which dimensions are surrendered when a cell is too thin.
# Experience goes first: position_level already encodes seniority, so it is the
# most redundant of the three. Sector goes next. position_level is held longest
# because it separates pay far more sharply than industry does -- an
# Executive-across-all-sectors benchmark still means something, whereas a
# whole-sector one blends fresh grads with managers and quotes a spread too wide
# to price against.
DROP_ORDER = ['experience_level', 'sector', 'position_level']


@st.cache_data
def _benchmark_table(keys: tuple) -> pd.DataFrame:
    sal = _market()
    return _benchmark(sal[sal.salary_flag == 'ok'], list(keys))


@st.cache_data
def _salary_global() -> dict:
    sal = _market()
    sal = sal[sal.salary_flag == 'ok']
    return {'n': len(sal),
            'mid_p25': sal.salary_midpoint.quantile(.25),
            'mid_p50': sal.salary_midpoint.median(),
            'mid_p75': sal.salary_midpoint.quantile(.75)}


def salary_lookup(sector: str | None = None, position_level: str | None = None,
                  experience_level: str | None = None) -> dict:
    """Benchmark for one configuration, degrading gracefully when a cell is thin.

    Any dimension may be None, meaning "don't narrow on this" -- the benchmark
    is then computed across that whole dimension rather than filtered to one
    value. Degradation surrenders one dimension at a time in DROP_ORDER, so
    every rung between the full combination and the whole market is tried
    before falling back to all postings. The grain is always reported so the
    hirer can see how specific the comparison actually is.
    """
    specified = [(k, v) for k, v in (('sector', sector),
                                     ('position_level', position_level),
                                     ('experience_level', experience_level))
                 if v is not None]

    ladder = []
    rung = specified
    while rung:
        ladder.append(rung)
        present = {k for k, _ in rung}
        drop = next(k for k in DROP_ORDER if k in present)
        rung = [(k, v) for k, v in rung if k != drop]

    for rung in ladder:
        keys = tuple(k for k, _ in rung)
        values = tuple(v for _, v in rung)
        table = _benchmark_table(keys)
        index = values[0] if len(values) == 1 else values
        if index in table.index:
            grain = ' + '.join(GRAIN_NAMES[k] for k in keys)
            return {'grain': grain, **table.loc[index].to_dict()}

    grain = 'all postings' if not specified else 'all postings (no comparable cell)'
    return {'grain': grain, **_salary_global()}


# --- 3. configuration norms (layer 1 s.4) ------------------------------------

@st.cache_data
def config_norms(sector: str | None = None) -> pd.DataFrame:
    """Row-% crosstab: which years-of-experience asks each position level uses.

    Levels with fewer than MIN_N postings are dropped rather than shown on
    percentages too thin to mean anything.
    """
    mkt = _market()
    # Row order fixed by whole-market seniority so the sector filter never
    # reshuffles the rows.
    level_order = position_levels()
    if sector:
        mkt = mkt[mkt.sector == sector]
    counts = pd.crosstab(mkt.position_level, mkt.yrs_bucket)
    norms = pd.crosstab(mkt.position_level, mkt.yrs_bucket, normalize='index') * 100
    norms = norms[counts.sum(axis=1) >= MIN_N]
    norms.index = norms.index.astype(str)
    return norms.loc[[lv for lv in level_order if lv in norms.index]]


# --- 6. response by pay band (layer 2 s.3) -----------------------------------

def _first_cycle() -> pd.DataFrame:
    """Volume outcomes use first-cycle postings only -- layer 2 s.1.3."""
    cohort = _layer2_cohort()
    return cohort[(cohort.repost_count == 0) & cohort.pay_band.notna()]


@st.cache_data
def response_by_pay_band() -> pd.DataFrame:
    """Median applications (P10-P90) and under-filled risk per pay band."""
    first = _first_cycle()
    under_filled = first.applications < first.vacancies

    out = first.groupby('pay_band', observed=True).agg(
        n=('applications', 'size'),
        apps_p10=('applications', lambda s: s.quantile(.10)),
        apps_p50=('applications', 'median'),
        apps_p90=('applications', lambda s: s.quantile(.90)),
    )
    out['under_filled'] = under_filled.groupby(first.pay_band, observed=True).mean()
    return out.loc[[b for b in PAY_LABELS if b in out.index]]


# --- 7. reach vs conversion (layer 2 s.4) ------------------------------------

@st.cache_data
def funnel_by_pay_band() -> pd.DataFrame:
    """Median views (reach) against median applications/views (conversion)."""
    first = _first_cycle().copy()
    first['conversion'] = first.applications / first.views.replace(0, np.nan)

    out = first.groupby('pay_band', observed=True).agg(
        n=('views', 'size'),
        views_p50=('views', 'median'),
        conversion_p50=('conversion', 'median'),
    )
    out['conversion_pct'] = out.conversion_p50 * 100
    return out.loc[[b for b in PAY_LABELS if b in out.index]]


# --- 8. repost risk (layer 2 s.5-6) ------------------------------------------

@st.cache_data
def repost_matrix() -> pd.DataFrame:
    """Repost rate (%) by pay band x required years, cells under MIN_N blanked.

    Must always be shown split by pay band: the unsplit view inverts the sign
    (Simpson's paradox -- layer 2 notebook s.5).
    """
    pool = _layer2_cohort()
    rates = pd.crosstab(pool.pay_band, pool.yrs_bucket,
                        values=pool.is_repost, aggfunc='mean') * 100
    counts = pd.crosstab(pool.pay_band, pool.yrs_bucket)
    rates = rates.where(counts >= MIN_N)
    rates.index = rates.index.astype(str)
    return rates.loc[[b for b in PAY_LABELS if b in rates.index]]


@st.cache_data
def repost_contrast() -> pd.DataFrame:
    """Repost rate below vs at-or-above 3 years required, within each pay band.

    The >=3yr contrast layer 2 s.6 tests; supplies the numbers behind the
    danger-zone warning.
    """
    pool = _layer2_cohort()
    pool = pool[pool.pay_band.notna()]
    hi_exp = (pool.seniority_years.clip(0, 15) >= 3)

    out = (pool.groupby([pool.pay_band, hi_exp], observed=True)
               .is_repost.agg(['mean', 'size']).unstack() * 1)
    res = pd.DataFrame({
        'repost_lt3': out[('mean', False)] * 100,
        'repost_gte3': out[('mean', True)] * 100,
        'n': out[('size', False)] + out[('size', True)],
    })
    res.index = res.index.astype(str)
    return res.loc[[b for b in PAY_LABELS if b in res.index]]


@st.cache_data
def cohort_sizes() -> dict:
    """Row counts for the captions that qualify each chart."""
    return {
        'market': len(_market()),
        'layer2': len(_layer2_cohort()),
        'first_cycle': len(_first_cycle()),
    }
