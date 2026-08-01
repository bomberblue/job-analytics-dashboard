"""
Data cleaning for the raw SGJobData extract.

Ported from notebooks/data_cleaning.ipynb, which documents the reasoning behind every
threshold and decision here (docs/data-cleaning-report-generated.md is the generated
report). The notebook imports these same functions and wraps each with its own
before/after snapshot for that report; this module has no reporting responsibility of
its own, only the transformations.

Pipeline order matters: junk rows first (so column statistics are computed on real
postings), then structure, then values, then dtypes. See clean_dataset() for the order.
"""
import json

import numpy as np
import pandas as pd

SALARY_FLOOR = 500          # monthly SGD; at or below this a salary is a placeholder, not a wage
SALARY_CEILING = 100_000    # monthly SGD; above this it is a data-entry error
INTERN_STIPEND_FLOOR = 300  # monthly SGD; below SALARY_FLOOR but a plausible internship stipend
SYNTHETIC_ID_RE = r'^RANDOM_JOB_'
EXPERIENCE_MAX = 100        # years; above this the value is not physically possible

# JOBS_SCHEMA columns that are dead in this extract - src/pipeline/feature_enrichment.py
# excludes these from JOBS_SCHEMA_COLUMNS for the same reason.
DEAD_COLUMNS = {
    'location': 'the extract is Singapore-only - zero variance',
    'salary_currency': "restates salary_type, itself constant 'Monthly' here and dropped by prune_dead_columns",
    'description': 'the source CSV has no description field at all',
    'requirements': 'the source CSV has no requirements field at all',
    'created_at': 'records when the pipeline ran, not a property of the posting; '
                  'DatabaseManager.insert_jobs stamps it at insert time',
}


def _all_blank(s):
    """True if every value is NaN or an empty / whitespace-only string - a column with no content."""
    if isinstance(s.dtype, pd.CategoricalDtype):
        return all(str(v).strip() == '' for v in s.cat.categories)
    if not (s.dtype == object or pd.api.types.is_string_dtype(s)):
        return False
    return s.astype('object').fillna('').astype(str).str.strip().eq('').all()


def remove_ghost_rows(df):
    """Drop structurally empty rows: every text column NaN and every numeric column exactly 0."""
    num_cols = list(df.select_dtypes(include='number').columns)
    bool_cols = list(df.select_dtypes(include='bool').columns)
    text_cols = [c for c in df.columns if c not in num_cols + bool_cols]

    na_per_row = df[text_cols].isna().sum(axis=1)
    ghost = (na_per_row == len(text_cols)) & (df[num_cols].fillna(0) == 0).all(axis=1)

    print(f"  → Removing {int(ghost.sum()):,} ghost rows (structurally empty)")
    return df.loc[~ghost].copy()


def remove_synthetic_rows(df):
    """Drop generated test rows whose metadata_jobPostId matches SYNTHETIC_ID_RE."""
    synthetic = df['metadata_jobPostId'].str.match(SYNTHETIC_ID_RE, na=False)
    print(f"  → Removing {int(synthetic.sum())} synthetic test rows")
    return df.loc[~synthetic].copy()


def prune_dead_columns(df):
    """Drop columns that are entirely empty or hold a single distinct value across the frame."""
    empty_cols = [c for c in df.columns if df[c].isna().all() or _all_blank(df[c])]
    constant_cols = [c for c in df.columns if c not in empty_cols and df[c].nunique(dropna=True) <= 1]
    print(f"  → Dropping {len(empty_cols)} empty and {len(constant_cols)} zero-variance columns")
    return df.drop(columns=empty_cols + constant_cols)


DATE_COLS = ['metadata_newPostingDate', 'metadata_originalPostingDate', 'metadata_expiryDate']


def parse_dates(df):
    """Convert DATE_COLS from str to datetime64, refusing any column where the round trip is lossy."""
    df = df.copy()
    for c in DATE_COLS:
        original = df[c]
        parsed = pd.to_datetime(original, errors='coerce')
        unparsed = int(parsed.isna().sum() - original.isna().sum())
        both_null = original.isna() & parsed.isna()
        matches = (parsed.dt.strftime('%Y-%m-%d') == original) | both_null
        lossless = bool(matches.all())
        assert unparsed == 0 and lossless, f'{c} would lose data - refusing to convert'
        df[c] = parsed
    print(f"  → Parsed {len(DATE_COLS)} date columns")
    return df


def split_categories(df):
    """Explode the categories JSON column into a (job posting, category) bridge table.

    Returns (df, job_category). df gains primary_category (first category) and
    n_categories; the categories column is dropped. job_category has columns
    metadata_jobPostId, category_id, category - one row per (posting, category) pair.
    """
    df = df.copy()
    parsed_cat = df['categories'].map(json.loads)
    n_per_row = parsed_cat.map(len)

    job_category = (pd.DataFrame({'metadata_jobPostId': df['metadata_jobPostId'], 'c': parsed_cat})
                      .explode('c', ignore_index=True))
    job_category = job_category.dropna(subset=['c'])
    job_category['category_id'] = job_category['c'].map(lambda d: d['id']).astype('int16')
    job_category['category'] = job_category['c'].map(lambda d: d['category']).astype('category')
    job_category = job_category.drop(columns='c')

    df['primary_category'] = parsed_cat.map(lambda v: v[0]['category'] if v else None)
    df['n_categories'] = n_per_row.astype('int8')
    df = df.drop(columns='categories')

    print(f"  → Split categories JSON into a {len(job_category):,}-row bridge table")
    return df, job_category


def fix_salaries(df):
    """Null out placeholder salaries below SALARY_FLOOR (paired), flag - not null - anything
    above SALARY_CEILING, and carve out plausible internship stipends from the floor rule."""
    df = df.copy()
    df['salary_minimum'] = df['salary_minimum'].astype('Int32')
    df['salary_maximum'] = df['salary_maximum'].astype('Int32')

    low_min = (df['salary_minimum'] < SALARY_FLOOR).fillna(True)
    low_max = (df['salary_maximum'] < SALARY_FLOOR).fillna(True)
    high_max = (df['salary_maximum'] > SALARY_CEILING).fillna(False)

    is_internship = df['employmentTypes'] == 'Internship/Attachment'
    intern_stipend = (is_internship
                      & low_min & low_max
                      & (df['salary_minimum'] >= INTERN_STIPEND_FLOOR).fillna(False)
                      & (df['salary_maximum'] >= INTERN_STIPEND_FLOOR).fillna(False))

    below_floor = (low_min | low_max) & ~intern_stipend

    df.loc[below_floor, ['salary_minimum', 'salary_maximum']] = pd.NA
    df['salary_flag'] = pd.Series(np.select(
        [below_floor, intern_stipend, high_max],
        ['undisclosed', 'low_stipend', 'outlier'],
        default='ok',
    ), index=df.index).astype('category')
    df['average_salary'] = ((df['salary_minimum'] + df['salary_maximum']) / 2).astype('Float64')

    print(f"  → Salary fix: {int(below_floor.sum()):,} nulled, "
          f"{int(intern_stipend.sum())} internship stipends kept, "
          f"{int(high_max.sum())} outliers flagged")
    return df


def cap_experience(df):
    """Null out minimumYearsExperience values above EXPERIENCE_MAX (impossible values). 0 is kept."""
    df = df.copy()
    years = df['minimumYearsExperience']
    impossible = years > EXPERIENCE_MAX
    df['minimumYearsExperience'] = years.astype('Int16').mask(impossible, pd.NA)
    print(f"  → Capped {int(impossible.sum())} impossible experience values")
    return df


INVISIBLE = '[' + ''.join(map(chr, [0x200B, 0x200E, 0x200F, 0x2060, 0xFEFF])) + ']'


def _repair(s):
    """Drop zero-width characters, collapse whitespace runs, trim the ends."""
    return (s.str.replace(INVISIBLE, '', regex=True)
             .str.replace(r'\s+', ' ', regex=True)
             .str.strip())


def normalize_text(df):
    """Repair title and postedCompany_name in place: strip zero-width chars, collapse
    whitespace. postedCompany_name is also upper-cased to merge its one casing outlier."""
    df = df.copy()
    df['title'] = _repair(df['title'])
    df['postedCompany_name'] = _repair(df['postedCompany_name'].str.upper())
    print("  → Normalized title and postedCompany_name text")
    return df


def add_derived_columns(df):
    """Add listing_days, is_repost and source. No values are imputed - zeros are left as-is."""
    df = df.copy()
    df['listing_days'] = (df['metadata_expiryDate'] - df['metadata_newPostingDate']).dt.days.astype('int16')
    df['is_repost'] = df['metadata_repostCount'] > 0
    df['source'] = df['metadata_jobPostId'].str.extract(r'^([A-Za-z]+)')[0]
    print("  → Added listing_days, is_repost, source")
    return df


def flag_duplicates(df):
    """Flag (not drop) rows that share company/title/employment/level/category/salary/vacancies
    and posting date. dup_group_id/-size/is_same_day_dup let downstream analysis decide."""
    df = df.copy()
    title_key = df['title'].str.lower()
    same_day = pd.DataFrame({
        'title': title_key,
        'company': df['postedCompany_name'],
        'employment': df['employmentTypes'],
        'level': df['positionLevels'],
        'category': df['primary_category'],
        'salary_min': df['salary_minimum'],
        'salary_max': df['salary_maximum'],
        'vacancies': df['numberOfVacancies'],
        'posted': df['metadata_newPostingDate'],
    })
    group_id = same_day.groupby(list(same_day.columns), dropna=False, observed=True).ngroup()
    df['dup_group_id'] = group_id.astype('int32')
    df['dup_group_size'] = group_id.map(group_id.value_counts()).astype('int16')
    df['is_same_day_dup'] = df['dup_group_size'] > 1
    print(f"  → Flagged {int(df['is_same_day_dup'].sum()):,} same-day duplicate rows "
          f"in {int(df.loc[df['is_same_day_dup'], 'dup_group_id'].nunique()):,} groups")
    return df
