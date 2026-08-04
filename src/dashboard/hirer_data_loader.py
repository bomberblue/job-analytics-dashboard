"""
Data access layer for the hirer view.

The seeker and market-overview views read DatabaseManager directly; this module
serves hirer_view.py alone, which is why the cohort definitions below can follow
the hirer notebooks without having to suit every consumer.

Chart code consumes the plain DataFrames returned here and never touches
storage. `_load_jobs()` is the single seam where the backend is chosen -- the
`jobs` table in DuckDB by default, with the enriched parquet kept as a fallback
for anyone without a built database. Everything above that seam is backend-
agnostic pandas, so the two sources cannot drift apart in what they report.

Cohort definitions and constants mirror notebooks/hirer_layer1_analysis.ipynb
and hirer_layer2_analysis.ipynb -- see those for the reasoning.
"""
import os

import duckdb
import numpy as np
import pandas as pd
import streamlit as st

from config.settings import DATA_PROCESSED, ENGAGEMENT_COUNTER_FREEZE_DATE
from src.database.database_manager import DatabaseManager

DATA_SOURCE = os.environ.get('JOBS_DATA_SOURCE', 'duckdb')
JOBS_TABLE = 'jobs'
PARQUET_PATH = DATA_PROCESSED / 'jobs_enriched.parquet'

# Holds a path, not a connection -- DatabaseManager opens and closes one per
# query, so a module-level instance keeps no file lock between loads.
_DB = DatabaseManager()

# The slice of the enriched schema this module actually reads. Naming it keeps
# the 1M-row frame down to the columns in use instead of all 33, and makes a
# missing column fail loudly at load rather than as a KeyError mid-chart.
MARKET_COLUMNS = [
    'dup_group_id',
    'sector', 'position_level', 'experience_level', 'seniority_years',
    'salary_midpoint', 'salary_flag',
    'expiry_date', 'listing_days',
    'views', 'applications', 'vacancies',
    'repost_count', 'is_repost',
]

# Low-cardinality text the parquet stores dictionary-encoded. DuckDB hands back
# plain VARCHAR, so restore the category dtype on that path -- otherwise the
# same frame costs several hundred MB more from one backend than the other.
CATEGORICAL_COLUMNS = ['sector', 'position_level', 'experience_level', 'salary_flag']

MIN_N = 30                  # smallest cell we will quote a figure from
CRAWL_DATE = ENGAGEMENT_COUNTER_FREEZE_DATE  # inferred counter-freeze boundary -- layer 1 notebook s.1

YR_BINS = [-1, 0, 1, 2, 3, 5, 8, 100]
YR_LABELS = ['0', '1', '2', '3', '4-5', '6-8', '9+']

PAY_BINS = [-1, 2999, 4999, 7999, 1e12]
PAY_LABELS = ['Entry (< $3k)', 'Mid ($3-5k)', 'Senior ($5-8k)', 'Executive (> $8k)']

EXP_ORDER = ['Entry Level', 'Mid Level', 'Senior']


def _load_jobs() -> pd.DataFrame:
    """The backend seam: MARKET_COLUMNS for every posting, in insertion order.

    Deliberately does NOT deduplicate. `_market()` owns that, so one rule runs
    over whichever backend loaded the rows. Both backends hand them back in the
    order the cleaning notebook wrote them -- the parquet by file order, DuckDB
    because `load_enriched` inserts that file and a plain scan preserves
    insertion order -- which is what makes `keep='first'` downstream pick the
    same posting either way.
    """
    if DATA_SOURCE == 'duckdb':
        cols = ', '.join(MARKET_COLUMNS)
        try:
            mkt = _DB.query(f'SELECT {cols} FROM {JOBS_TABLE}', read_only=True)
        except (duckdb.BinderException, duckdb.CatalogException, duckdb.IOException) as e:
            # Two failures land here and neither explains itself. `jobs` also
            # gets written by DataPipeline.insert_jobs(), which rebuilds it on
            # the narrower JOBS_SCHEMA and drops every enrichment column below;
            # and a pipeline mid-write holds the file lock, so the read cannot
            # open it at all. Both are answered by the same two suggestions.
            raise RuntimeError(
                f'Cannot read `{JOBS_TABLE}` from {_DB.db_path}: {e}\n'
                'Refresh it with `python -m src.pipeline.load_enriched` (or wait '
                'for a running pipeline to finish), or set JOBS_DATA_SOURCE=parquet '
                'to read the enriched parquet directly.'
            ) from e
        for col in CATEGORICAL_COLUMNS:
            mkt[col] = mkt[col].astype('category')
        return mkt
    if DATA_SOURCE == 'parquet':
        return pd.read_parquet(PARQUET_PATH, columns=MARKET_COLUMNS)
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

# The sector list is NOT here: DatabaseManager.get_sector_list() is the one
# implementation, and both views call it. Deduplication does not change the set
# of sectors, so there was never a reason for this module to derive its own.

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
               'experience_level': 'experience', 'yrs_bucket': 'years'}

# The order in which dimensions are surrendered when a cell is too thin.
# Experience goes first: position_level already encodes seniority, so it is the
# most redundant of the four -- doubly so now that yrs_bucket states the same
# thing at a finer grain. Sector goes next. yrs_bucket is surrendered before
# position_level, because carrying a fourth dimension leaves only 60% of cells
# above MIN_N against 77% for three, so the years ask is the one that most often
# has to be given up to quote a figure at all. position_level is held longest
# because it separates pay far more sharply than industry does -- an
# Executive-across-all-sectors benchmark still means something, whereas a
# whole-sector one blends fresh grads with managers and quotes a spread too wide
# to price against.
DROP_ORDER = ['experience_level', 'sector', 'yrs_bucket', 'position_level']


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
                  experience_level: str | None = None,
                  yrs_bucket: str | None = None) -> dict:
    """Benchmark for one configuration, degrading gracefully when a cell is thin.

    Any dimension may be None, meaning "don't narrow on this" -- the benchmark
    is then computed across that whole dimension rather than filtered to one
    value. Degradation surrenders one dimension at a time in DROP_ORDER, so
    every rung between the full combination and the whole market is tried
    before falling back to all postings. The grain is always reported so the
    hirer can see how specific the comparison actually is -- which matters more
    with years in the ladder, since it is the dimension most often dropped.
    """
    specified = [(k, v) for k, v in (('sector', sector),
                                     ('position_level', position_level),
                                     ('experience_level', experience_level),
                                     ('yrs_bucket', yrs_bucket))
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

def _first_cycle(sector: str | None = None) -> pd.DataFrame:
    """Volume outcomes use first-cycle postings only -- layer 2 s.1.3."""
    cohort = _layer2_cohort()
    first = cohort[(cohort.repost_count == 0) & cohort.pay_band.notna()]
    return first[first.sector == sector] if sector else first


# These functions never substitute the whole market for a sector that asked for
# itself. A thin cell is dropped and shows as a gap, because a gap says "not
# enough postings here" -- true, and visible -- whereas all-sector figures under
# a sector heading say something false and say it silently. The caller renders
# an empty result as a message rather than an empty chart.


def _response_table(frame: pd.DataFrame) -> pd.DataFrame:
    under_filled = frame.applications < frame.vacancies
    out = frame.groupby('pay_band', observed=True).agg(
        n=('applications', 'size'),
        apps_p10=('applications', lambda s: s.quantile(.10)),
        apps_p50=('applications', 'median'),
        apps_p90=('applications', lambda s: s.quantile(.90)),
    )
    out['under_filled'] = under_filled.groupby(frame.pay_band, observed=True).mean()
    out = out[out.n >= MIN_N]
    return out.loc[[b for b in PAY_LABELS if b in out.index]]


@st.cache_data
def response_by_pay_band(sector: str | None = None) -> pd.DataFrame:
    """Median applications (P10-P90) and under-filled risk per pay band.

    Bands under MIN_N are dropped, so a sector shows only the bands it can
    actually support -- possibly none.
    """
    return _response_table(_first_cycle(sector))


# --- 7. reach vs conversion (layer 2 s.4) ------------------------------------

def _funnel_table(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame['conversion'] = frame.applications / frame.views.replace(0, np.nan)

    out = frame.groupby('pay_band', observed=True).agg(
        n=('views', 'size'),
        views_p50=('views', 'median'),
        conversion_p50=('conversion', 'median'),
    )
    out['conversion_pct'] = out.conversion_p50 * 100
    out = out[out.n >= MIN_N]
    return out.loc[[b for b in PAY_LABELS if b in out.index]]


@st.cache_data
def funnel_by_pay_band(sector: str | None = None) -> pd.DataFrame:
    """Median views (reach) against median applications/views (conversion).

    Same contract as response_by_pay_band(): the sector's own bands, or none.
    """
    return _funnel_table(_first_cycle(sector))


# --- 8. repost risk (layer 2 s.5-6) ------------------------------------------

def _repost_table(pool: pd.DataFrame) -> pd.DataFrame:
    rates = pd.crosstab(pool.pay_band, pool.yrs_bucket,
                        values=pool.is_repost, aggfunc='mean') * 100
    counts = pd.crosstab(pool.pay_band, pool.yrs_bucket)
    rates = rates.where(counts >= MIN_N)
    rates.index = rates.index.astype(str)
    rates.columns = rates.columns.astype(str)
    # Reindex to the full grid rather than take what crosstab returns: it drops
    # year buckets that are empty across every band, which would quietly hand
    # back a narrower chart for exactly the sectors whose gaps matter most. Every
    # sector is drawn on the same 4 x 7 axes, so they can be read against each
    # other and a hole is visible as a hole.
    return rates.reindex(index=PAY_LABELS, columns=YR_LABELS)


@st.cache_data
def repost_matrix(sector: str | None = None) -> pd.DataFrame:
    """Repost rate (%) by pay band x required years, cells under MIN_N blanked.

    Must always be shown split by pay band: the unsplit view inverts the sign
    (Simpson's paradox -- layer 2 notebook s.5). All four bands and all seven
    year buckets are kept as rows and columns even when a sector fills none of
    them, so the grid keeps its shape and the gaps are legible as gaps -- a
    sector whose postings cluster in one corner should look like one.
    """
    pool = _layer2_cohort()
    return _repost_table(pool[pool.sector == sector] if sector else pool)


@st.cache_data
def layer2_size(sector: str | None = None) -> int:
    """Row count behind the repost charts, for the caption that qualifies them."""
    pool = _layer2_cohort()
    return len(pool[pool.sector == sector] if sector else pool)


def _contrast_table(pool: pd.DataFrame) -> pd.DataFrame:
    pool = pool[pool.pay_band.notna()]
    hi_exp = (pool.seniority_years.clip(0, 15) >= 3)

    out = (pool.groupby([pool.pay_band, hi_exp], observed=True)
               .is_repost.agg(['mean', 'size']).unstack() * 1)
    # A thin sector can miss one side of the split entirely, and the columns are
    # then absent rather than empty -- name them before reading them.
    for stat in ('mean', 'size'):
        for side in (False, True):
            if (stat, side) not in out.columns:
                out[(stat, side)] = np.nan

    res = pd.DataFrame({
        'repost_lt3': out[('mean', False)] * 100,
        'repost_gte3': out[('mean', True)] * 100,
        'n': out[('size', False)].fillna(0) + out[('size', True)].fillna(0),
    })
    # Both sides must clear MIN_N: the row states a difference between them, so
    # one thin side makes the comparison, not just one number, unreadable.
    readable = ((out[('size', False)] >= MIN_N) & (out[('size', True)] >= MIN_N))
    res = res[readable.fillna(False)]
    res.index = res.index.astype(str)
    return res.loc[[b for b in PAY_LABELS if b in res.index]]


@st.cache_data
def repost_contrast(sector: str | None = None) -> pd.DataFrame:
    """Repost rate below vs at-or-above 3 years required, within each pay band.

    The >=3yr contrast layer 2 s.6 tests; supplies the numbers behind the
    danger-zone warning. A band missing from the result is a band this sector
    cannot support, and the warning simply does not fire for it -- silence is
    the honest output there, not the whole market's number in its place.
    """
    pool = _layer2_cohort()
    return _contrast_table(pool[pool.sector == sector] if sector else pool)


@st.cache_data
def cohort_sizes() -> dict:
    """Row counts for the captions that qualify each chart."""
    return {
        'market': len(_market()),
        'layer2': len(_layer2_cohort()),
        'first_cycle': len(_first_cycle()),
    }
