"""
Feature enrichment for the cleaned job dataset.

Renames the cleaned dataset's source column names to the names used by ``src/pipeline/`` and the
``jobs`` table, and derives feature columns like seniority bands and skill counts -- so a cleaned frame
can feed the existing dashboard without a translation layer.

Operates purely on DataFrames.  How the cleaned dataset was produced, stored, or loaded is the
caller's concern; nothing here reads or writes files.

Two deliberate deviations from the current pipeline behaviour, both documented rather than silent:

1. ``job_id`` carries the real source posting id (``metadata_jobPostId``) instead of a fresh UUID,
   so enriched rows can still be joined back to the raw layer, to the category bridge table, and to
   the originating job board.  ``DatabaseManager.insert_jobs`` regenerates it as a UUID, which
   makes that impossible.
2. ``competitiveness_score`` divides by the 99th percentile of salary, not ``max()``.  Ceiling
   outliers are intentionally left in the data (flagged via ``salary_flag``, not nulled), so a
   ``max()`` denominator is dominated by them and compresses the median row's salary contribution
   to roughly 0.02 of the 50 points available.

Five ``JOBS_SCHEMA`` columns are absent from ``JOBS_SCHEMA_COLUMNS`` and are never built:
``location`` and ``salary_currency`` would be the same constant on every row (``'Singapore'`` /
``'SGD'`` -- the source is a Singapore-only, monthly-SGD extract), ``description`` and
``requirements`` would be empty strings because the source CSV carries no such fields, and
``created_at`` is a load-time audit stamp rather than a property of the posting -- writing it here
makes the parquet's bytes change on every execution with no change in the data.  A constant column
cannot be filtered on, cannot correlate with anything, and costs memory on every read.  Nothing
downstream breaks: ``DatabaseManager.insert_jobs`` back-fills ``salary_currency`` and
``created_at`` itself and filters ``columns_order`` to the columns actually present, and the two
text columns are nullable.

This module does not model that judgement, only the outcome -- *which* columns are worth
materialising is a property of the extract being cleaned, so it is the cleaning step that decides
it and asserts on it.  Here it is simply a shorter column list.

Two columns that the original pipeline produced are deliberately NOT reproduced here:

* ``days_posted`` -- it is ``now() - posting_date``, which measures when ingestion ran rather than
  any property of the posting, and would make the result change on every execution.
  ``listing_days`` (``expiry_date - posting_date``) is the deterministic equivalent and is already
  present on the cleaned frame.
* ``is_growth_role`` -- its definition (``count > median * 0.2``) marks essentially every role.

The extra columns computed here (``salary_band``, ``skill_count``, ``competitiveness_score``) are
not part of the ``jobs`` table schema — ``columns_order`` in ``database_manager.py`` filters them out
at load time.  They are produced here anyway because the enriched frame is meant to be usable
directly for analysis, not only as a database feed.
"""
import re

import numpy as np
import pandas as pd

__all__ = [
    'COMMON_SKILLS',
    'RENAME_MAP',
    'JOBS_SCHEMA_COLUMNS',
    'band_experience',
    'band_salary',
    'extract_skills_vectorised',
    'feature_enrichment',
    'schema_report',
]

# Skill vocabulary and matching rule - kept in sync with the extract_skills_vectorised
# boundary rule below (both use the same non-alphanumeric-boundary regex).
COMMON_SKILLS = [
    'Python', 'Java', 'JavaScript', 'SQL', 'R', 'C++', 'Go', 'Rust',
    'React', 'Angular', 'Vue', 'Django', 'Flask', 'Spring',
    'AWS', 'Azure', 'GCP', 'Kubernetes', 'Docker',
    'Machine Learning', 'AI', 'Data Science', 'Analytics',
    'Salesforce', 'SAP', 'Oracle', 'MySQL', 'PostgreSQL',
    'Agile', 'Scrum', 'DevOps', 'CI/CD',
    'Node.js', 'Express', 'FastAPI',
]

# Cleaned dataset's source column name -> src/pipeline/ column name.
RENAME_MAP = {
    'metadata_jobPostId':                 'job_id',
    'postedCompany_name':                 'company',
    'primary_category':                   'sector',
    'salary_minimum':                     'salary_min',
    'salary_maximum':                     'salary_max',
    'average_salary':                     'salary_midpoint',
    'minimumYearsExperience':             'seniority_years',
    'positionLevels':                     'position_level',
    'employmentTypes':                    'job_type',
    'metadata_newPostingDate':            'posting_date',
    'metadata_expiryDate':                'expiry_date',
    'metadata_totalNumberOfView':         'views',
    'metadata_totalNumberJobApplication': 'applications',
    'numberOfVacancies':                  'vacancies',
    'metadata_repostCount':               'repost_count',
}

# The JOBS_SCHEMA columns this module produces, in src/database/schema.py order, for the loader's
# convenience.  location, salary_currency, description, requirements and created_at are absent by
# design -- they would be constant or empty (see the module docstring), and omitting them from the
# list rather than skipping them at build time means nothing can read it and reintroduce them.
# The full table definition still lives in src/database/schema.py.
JOBS_SCHEMA_COLUMNS = [
    'job_id', 'title', 'company', 'sector', 'sub_sector',
    'salary_min', 'salary_max', 'experience_level',
    'seniority_years', 'position_level', 'job_type', 'posting_date',
    'expiry_date', 'views', 'applications', 'vacancies', 'repost_count',
    'skills',
]


def _bool(mask):
    """np.select needs plain bool arrays; comparisons on nullable Int/Float dtypes give pd.NA."""
    return mask.fillna(False).to_numpy(dtype=bool)


def band_experience(years):
    """Band numeric years of experience: <=1 -> Entry Level, <=4 -> Mid Level, else Senior.

    Missing years become "Unknown", matching clean_dataset()'s cap_experience(), which
    passes the raw (NaN-bearing) column here.
    """
    return pd.Series(
        np.select([_bool(years.isna()), _bool(years <= 1), _bool(years <= 4)],
                  ['Unknown',           'Entry Level',     'Mid Level'], default='Senior'),
        index=years.index, dtype='object')


def band_salary(max_sal):
    """Band a salary maximum: <3000 Entry, <5000 Mid, <8000 Senior, else Executive; NaN -> Unknown."""
    return pd.Series(
        np.select([_bool(max_sal.isna()), _bool(max_sal < 3000),
                   _bool(max_sal < 5000), _bool(max_sal < 8000)],
                  ['Unknown', 'Entry (< $3k)', 'Mid ($3-5k)', 'Senior ($5-8k)'],
                  default='Executive (> $8k)'),
        index=max_sal.index, dtype='object')


def extract_skills_vectorised(text):
    """Extract skills from text using consistent boundary rule, one pass per skill in COMMON_SKILLS.

    Returns ``(skills_series, skill_count_array)``.

    The boundary is ``(?<![a-zA-Z0-9])``/``(?![a-zA-Z0-9])`` rather than ``\\b`` so that skills
    containing symbols ("C++", "CI/CD", "Node.js") still match.

    Note: the source data has no description or requirements text at all -- which is why neither is
    in ``JOBS_SCHEMA_COLUMNS`` -- so callers pass titles only.  That limitation is inherited from
    the source, not introduced here, but it means ``skill_count`` is a title-keyword signal rather
    than a requirements analysis.
    """
    hits = {}
    for skill in COMMON_SKILLS:
        pattern = r'(?<![a-zA-Z0-9])' + re.escape(skill) + r'(?![a-zA-Z0-9])'
        hits[skill] = text.str.contains(pattern, case=False, regex=True, na=False)

    mask = pd.DataFrame(hits, index=text.index)
    arr, cols = mask.to_numpy(), np.array(mask.columns)
    skills = [', '.join(cols[row]) if row.any() else 'Not Specified' for row in arr]
    return pd.Series(skills, index=text.index), arr.sum(axis=1).astype('int8')


def feature_enrichment(df, job_category=None):
    """Rename the cleaned dataset's columns to the src/pipeline/ names and derive feature columns.

    Parameters
    ----------
    df : pd.DataFrame
        The cleaned dataset, still using its source column names (the keys of ``RENAME_MAP``).
        Assumed already free of dead columns -- the cleaning step is what guarantees that.
    job_category : pd.DataFrame, optional
        The category bridge table, one row per (posting, category) pair with columns
        ``metadata_jobPostId``, ``category_id`` and ``category``.  When supplied, ``sub_sector`` is
        populated from each posting's *second* category -- a column the pipeline leaves NULL.  Row
        order within a posting must match the order the categories were originally listed in.

    Returns
    -------
    pd.DataFrame
        A NEW frame; ``df`` is not modified.  Contains every ``JOBS_SCHEMA_COLUMNS`` entry plus any
        provenance columns the cleaning step carried (``salary_flag``, ``dup_group_size``, ...).
    """
    out = df.rename(columns=RENAME_MAP).copy()

    # --- sub_sector: second category from the bridge table (pipeline leaves this NULL) ---
    if job_category is not None:
        second_position = job_category.groupby('metadata_jobPostId', observed=True).cumcount() == 1
        second = job_category[second_position].set_index('metadata_jobPostId')['category']
        out['sub_sector'] = out['job_id'].map(second).astype('category')
    else:
        out['sub_sector'] = pd.Series(pd.NA, index=out.index, dtype='object')

    # --- banded labels, matching the pipeline's thresholds exactly ---
    out['experience_level'] = band_experience(out['seniority_years']).astype('category')
    out['salary_band'] = band_salary(out['salary_max']).astype('category')

    # The pipeline does seniority_years = min_years_experience.fillna(0).astype(int). Kept as-is,
    # including the mismatch with experience_level above, which reads missing years as "Unknown".
    out['seniority_years'] = out['seniority_years'].fillna(0).astype('int8')

    # --- skills (titles only -- no description column exists) ---
    out['skills'], out['skill_count'] = extract_skills_vectorised(out['title'])

    # days_posted is deliberately not reproduced -- see the module docstring. listing_days already
    # carries the deterministic equivalent.

    # --- competitiveness_score: p99 denominator, NOT max() (see deviation 2) ---
    if 'salary_flag' in out.columns:
        salary_basis = out.loc[out['salary_flag'] == 'ok', 'salary_midpoint']
    else:
        salary_basis = out['salary_midpoint']
    sal_p99 = salary_basis.quantile(.99)
    skill_max = max(int(out['skill_count'].max()), 1)
    out['competitiveness_score'] = (
        (out['salary_midpoint'] / sal_p99 * 50).clip(upper=50).astype('Float64').fillna(25)
        + (out['skill_count'] / skill_max * 50)
    ).clip(0, 100).astype('Float64')

    return out


def schema_report(enriched):
    """Compare an enriched frame against the schema.

    Returns ``{'missing': [...], 'extra': [...]}``.  ``missing`` must be empty for the frame to be
    loadable into the ``jobs`` table; ``extra`` is the provenance superset and is expected.
    """
    return {
        'missing': [c for c in JOBS_SCHEMA_COLUMNS if c not in enriched.columns],
        'extra': [c for c in enriched.columns if c not in JOBS_SCHEMA_COLUMNS],
    }
