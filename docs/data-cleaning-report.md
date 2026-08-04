# Data Conversion & Cleaning Report — `SGJobData.csv`

**Source:** `data/raw/SGJobData.csv` → `data/processed/jobs_raw.parquet`
**Shape as loaded:** 1,048,585 rows × 23 columns · 402.8 MB in memory (deep)
**Shape after cleaning:** 1,044,597 rows × 18 columns · ~218 MB (−46%)

All figures below are computed on the current `df`. Statistics that describe real
postings exclude the 3,988 ghost rows described in Section 2.

---

## 1. Column type conversions

Everything is currently loaded as `object` (strings) or wide default integers, because
`pd.read_csv` was called without a `dtype` map. The conversions below are all
**lossless** unless flagged.

### 1.1 Dates: `object` → `datetime64[ns]`

| Column | From | To | Loss? |
|---|---|---|---|
| `metadata_newPostingDate` | `object` | `datetime64[ns]` | None |
| `metadata_originalPostingDate` | `object` | `datetime64[ns]` | None |
| `metadata_expiryDate` | `object` | `datetime64[ns]` | None |

**Justification.** All three are uniformly `ISO-8601 YYYY-MM-DD`, length 10 on every
row, and `pd.to_datetime` parses 1,044,597/1,044,597 with zero coercions. As strings
they sort correctly by luck but cannot do date arithmetic, resampling, or
`.dt` accessors — every time-series chart in the dashboard needs real datetimes.

**No data loss.** Round-trip `to_datetime(...).dt.strftime('%Y-%m-%d')` reproduces the
original string exactly. Ranges are sane and internally consistent:

- `newPostingDate` 2023-02-24 → 2024-05-29
- `originalPostingDate` 2022-10-03 → 2024-05-29
- `expiryDate` 2023-04-04 → 2024-12-12
- `originalPostingDate > newPostingDate`: **0 violations**
- `expiryDate <= newPostingDate`: **0 violations**
- Listing lifespan: median 30 days, 1st pct 7 days, max 331 days — plausible

Because there is no time component, `datetime64[ns]` is adequate; do not localise to
a timezone (it would imply precision the source does not have).

### 1.2 Low-cardinality strings: `object` → `category`

| Column | Unique | From | To | Loss? |
|---|---|---|---|---|
| `employmentTypes` | 8 | `object` | `category` | None |
| `positionLevels` | 9 | `object` | `category` | None |
| `status_jobStatus` | 3 | `object` | `category` | None |
| `postedCompany_name` | 53,151 | `object` | `category` | None |

**Justification.** 8 and 9 distinct values over a million rows is the textbook case for
`category`: the string is stored once and each row holds an `int8` code. This is where
the bulk of the 185 MB saving comes from. `postedCompany_name` is a 5% cardinality
ratio (53k/1.04M) — still a clear win, and it makes `groupby('postedCompany_name')`
substantially faster, which the "top hiring companies" view depends on.

`positionLevels` and `employmentTypes` are **singular despite the plural names** — every
row holds exactly one value, not a list. Verified: 8 and 9 distinct whole-cell values,
no delimiters. No explosion needed.

**Consider ordering** `positionLevels` as an ordered categorical
(`Fresh/entry level < Non-executive < Junior Executive < Executive < Senior Executive <
Professional < Manager < Middle Management < Senior Management`). This makes
`sort_values` and ordinal charts correct by construction. Note the ordering is a
judgement call — `Professional` is a parallel technical track rather than a strict rung
above `Senior Executive` — so document whatever order you pick.

**No data loss** provided the conversion happens *after* row filtering; converting first
leaves unused categories behind (harmless but confusing in `value_counts`).

### 1.3 Integer downcasting

All verified safe against the observed min/max on real rows:

| Column | From | To | Observed range | Safe? |
|---|---|---|---|---|
| `minimumYearsExperience` | `int64` | `int8` | 0 – 88 | Yes |
| `metadata_repostCount` | `int64` | `int8` | 0 – 2 | Yes |
| `numberOfVacancies` | `int64` | `int16` | 1 – 999 | Yes |
| `metadata_totalNumberOfView` | `int64` | `int16` | 0 – 8,190 | Yes |
| `metadata_totalNumberJobApplication` | `int64` | `int16` | 0 – 1,342 | Yes |
| `salary_minimum` | `int64` | `int32` | 1 – 350,000 | Yes |
| `salary_maximum` | `int64` | `int32` | 1 – 25,330,000 | Yes |

**Justification.** 8× memory reduction on the `int8` columns for zero information loss.

**Caveat — do the downcast last.** `int16` for `totalNumberOfView` has only 24k headroom
above the current max. If this pipeline is ever re-run on a refreshed extract with a
viral posting, it will silently overflow. Either use `int32` for the two `metadata_total*`
counters as cheap insurance, or assert the range before casting. I would use `int32`
for those two and keep `int8`/`int16` elsewhere where the semantic ceiling is real
(years of experience, repost count).

### 1.4 `average_salary`: keep `float64`, or drop it

`average_salary` is exactly `(salary_minimum + salary_maximum) / 2` for **all**
1,044,597 rows (verified with `np.allclose`). It is a derived column.

**Do not cast to `float32` — that one IS lossy.** Max absolute round-trip error is
**0.5**, because the 12 rows with multi-million salaries exceed float32's ~7 significant
digits. 6,397 rows carry a genuine `.5` fraction (odd min+max), so the error is not
cosmetic.

**Recommendation:** drop the column from the stored parquet and recompute it on read,
or keep it as `float64`. Storing a derived column invites it to drift out of sync with
its inputs after the salary fixes in Section 3.

### 1.5 `categories`: JSON string → normalised long table

`categories` holds a JSON array of `{"id": int, "category": str}` objects, e.g.

```
[{"id":13,"category":"Environment / Health"},{"id":25,"category":"Manufacturing"}]
```

- 43 distinct categories
- 1–5 categories per posting (1: 65%, 2: 18%, 3: 8%, 4: 3%, 5: 5%)
- Zero empty arrays

**Justification.** As a raw JSON string this column is unqueryable — you cannot filter
"all IT jobs" without a substring match that would also catch
`Information Technology` inside other text. Two viable targets:

1. **Long/bridge table** (recommended): `job_category(job_post_id, category_id, category)`,
   one row per (job, category) pair, ~1.9M rows. Correct many-to-many modelling, joins
   cleanly, and is what the dashboard's category filter wants.
2. **`primary_category`** = first element, kept on the wide table for convenience.

**This is where real data loss risk lives.** Do not "simplify" by keeping only the first
category — 35% of postings carry 2+ categories, so a first-only reduction discards
~850k category assignments and will systematically understate every category except the
alphabetically/insertion-first one. Keep the bridge table as the source of truth and
treat `primary_category` as a convenience denormalisation.

### 1.6 Columns to drop (zero information)

| Column | Reason |
|---|---|
| `occupationId` | **100% NaN**, 0 distinct values. Empty column. |
| `status_id` | Single value `0` on all rows. Zero variance. |
| `salary_type` | Single value `Monthly` on all rows. Fold into docs/column name instead. |
| `salary_na` | Single value `False` on all rows — and it is **wrong** (see §3.1). Drop and recompute. |

**Justification.** A constant column cannot correlate with anything, cannot be filtered
on meaningfully, and costs memory and cognitive load. `salary_type` being constant is
worth recording in the data dictionary ("all salaries are monthly SGD") rather than
repeated a million times.

Keep `metadata_isPostedOnBehalf` (`bool`, 94/6 split) — low variance but not zero, and
it flags recruiter-posted listings, which matters for company-level aggregation.

---

## 2. Ghost rows to be removed

**3,988 rows (0.38% of the file) — remove all of them.**

### Identification

```python
ghost = df['title'].isna()          # 3,988 rows
```

Any one of the 11 nullable text columns gives the identical row set — verified with
`.equals()` across all of them.

### Evidence that these are structurally empty records, not partially-missing postings

| Property | Value |
|---|---|
| Rows where all 11 text columns are NaN | 3,988 (100% of the group) |
| Rows with a *partial* NaN pattern | **0** — the per-row NaN count is exactly 0 or 11, never in between |
| Sum of `abs()` of every numeric column on these rows | **0.0** — all ten numeric fields are exactly zero |
| `salary_minimum` / `salary_maximum` / `numberOfVacancies` == 0 | 3,988 (nowhere else in the file) |
| Index range | 197,478 – 606,701, non-contiguous (0.97% density in that window) |

Every non-ghost row has `numberOfVacancies >= 1`; a posting with zero vacancies, zero
salary, no title, no company and no ID is not a job. These are almost certainly blank
lines or failed-scrape rows emitted by the collection process, sprinkled through one
segment of the crawl.

### Justification for deletion rather than imputation

There is nothing to impute *from*. Every field is empty simultaneously — no title, no
company, no ID, no dates. Imputation would fabricate 3,988 synthetic job postings and
inflate every count-based metric on the dashboard. At 0.38% of the data, dropping them
costs nothing statistically.

### Ordering trap

Run this **before** any `dropna()` on the full frame and **before** dropping
`occupationId`, or note that `df.isna().any(axis=1)` currently returns **all
1,048,585 rows** because `occupationId` is 100% NaN. A naive `df.dropna()` today
returns an empty DataFrame. Drop `occupationId` first, then filter ghosts explicitly on
`title.notna()` — an explicit mask documents the intent better than a bare `dropna()`.

### Also review (do not auto-delete): 10 synthetic rows

Rows with `metadata_jobPostId` matching `^RANDOM_JOB_` (indices 1048575–1048584, the
last 10 rows of the file) are clearly generated test data — the IDs carry a 2025-11-15
generation timestamp and the salaries are nonsense (e.g. "Language Teacher",
$324,072–$20,862,169/month). They account for 8 of the 12 rows with
`salary_maximum > 1,000,000`.

**Recommendation: remove them.** They are not real MCF postings and they dominate the
salary tail. If they were deliberately appended for pipeline testing, exclude them by ID
prefix rather than by index so the filter survives a reload.

The 124 `ATS-`prefixed rows are legitimate (real companies, sane salaries) — an
alternative applicant-tracking-system source. Keep them, but consider adding a
`source` column derived from the ID prefix.

---

## 3. Data fixing, per column

### 3.1 `salary_minimum` / `salary_maximum` — the main quality problem

Distribution on real rows: median min $3,000, median max $4,500, but
`max(salary_maximum) = 25,330,000`.

**Fix A — undisclosed-salary sentinel (high confidence).**

| Pattern | Rows |
|---|---|
| `salary_minimum == 1 AND salary_maximum == 1` | 1,804 |
| `salary_maximum < 100` | 6,438 |
| `salary_maximum < 500` | 7,124 |

$1/month is not a wage; it is the placeholder a poster enters to satisfy a required
field. Set these to `NaN` (requires nullable `Int32`, or convert salary columns to
`float`) and flag them — **this is exactly what the broken `salary_na` column was
supposed to capture.** Recompute:

```python
salary_na = df['salary_maximum'] < 500        # or a threshold you defend
```

Choose the threshold explicitly. Singapore has no statutory minimum wage, and the
Progressive Wage Model floors sit around $1,400–$1,600/month for covered sectors, so
$500 is a conservative "cannot be a real monthly wage" line. 8,094 rows fall under $800.
Note the sub-$100 group skews Part Time / Contract / Temporary (1,994 / 1,567 / 1,012),
consistent with hourly-paid roles whose poster could not express an hourly rate in a
monthly-only field — so some of these are *mis-unit*, not *undisclosed*. Both cases
should be excluded from salary aggregates.

**Fix B — implausible upper tail (high confidence at the top, judgement below).**

| Threshold | Rows |
|---|---|
| `salary_maximum > 1,000,000` | 12 (8 are `RANDOM_JOB_` synthetics) |
| `salary_maximum > 100,000` | 279 |
| `salary_maximum > 50,000` | 475 |
| `salary_maximum > 30,000` | 1,389 |

The extremes are unambiguous data-entry errors: `MCF-2023-0659775` "Accounts Executive"
at $2,800–$25,330,000, `MCF-2023-0165468` "Clinic assistant" at $1,500–$10,000,000.
The pattern — sane minimum, absurd maximum — points at a missing decimal or a pasted
annual/aggregate figure.

Recommended treatment: **null out `salary_maximum` above a documented ceiling rather
than winsorising.** Winsorising invents a value; nulling admits ignorance and lets
`mean()` skip the row. A ceiling of $100,000/month keeps genuine C-suite listings
(the 99.9th percentile is $35,000) while removing 279 rows of noise. Do **not** use the
plain 1.5×IQR rule here — the 3×IQR upper fence is only $13,300 and would discard
24,530 legitimate senior roles.

**Fix C — recompute `average_salary` after A and B**, so it reflects the cleaned inputs.
Currently it inherits every bad value (max $12,666,400).

**Consistency check that passes:** `salary_minimum > salary_maximum` in **0** rows, and
`salary_minimum == 0` / `salary_maximum == 0` in 0 real rows. No swap correction needed.

### 3.2 `title` — whitespace normalisation

- 4,445 rows have leading/trailing whitespace
- 377,084 distinct raw titles → 365,602 after `.str.lower().str.strip()`

**Fix:** `df['title'].str.strip().str.replace(r'\s+', ' ', regex=True)`. Preserve original
case for display; add a `title_normalised` (lowercased) column for grouping and for the
keyword/skill extraction that the analysis layer will do. 11,482 titles collapse under
case-folding alone — without it, "Software Engineer" and "software engineer" are counted
as different roles in every top-titles chart.

### 3.3 `postedCompany_name` — near-clean

- 53,151 distinct → 53,150 after upper + whitespace-collapse (one collision)
- Zero rows with leading/trailing whitespace

**Fix:** minimal. Add a `company_normalised` key
(`.str.upper().str.replace(r'\s+',' ',regex=True).str.strip()`) for joins and grouping,
and keep the raw name for display. Legal-suffix variation (`PTE. LTD.` / `PTE LTD` /
`PTE.LTD.`) is the real fragmentation risk for company-level aggregation — worth a
suffix-stripping pass if the dashboard ranks employers, but that is entity resolution,
not cleaning, and should be a separate documented step with spot-checked output.

### 3.4 `categories` — parse, do not fix

Fully well-formed: every row parses as JSON, no empty arrays, 43 stable category labels.
The only action is the structural conversion in §1.5.

### 3.5 `minimumYearsExperience` — leave, but cap for display

Range 0–88; the tail is 50 (3 rows), 55, 56, 58, 59, 60, 61, 62, 63, 76, 87, 88 — a few
dozen rows total. 88 years of required experience is impossible, but these are almost
certainly a typo'd or misused field on the poster's side, not a pipeline defect.

**Fix:** keep the raw value; add a display cap (e.g. bucket `20+`) rather than editing
data. Anything above ~50 could reasonably be set to `NaN` — under 20 rows either way, so
the choice does not move any aggregate.

### 3.6 `numberOfVacancies` — leave

Range 1–999, 308 rows above 100. Bulk hiring drives (F&B, security, cleaning) genuinely
post hundreds of vacancies. 999 looks like a UI cap rather than a true count; note it in
the data dictionary and avoid summing this column into a "total jobs available" headline
without a caveat.

### 3.7 Duplicate postings — investigate, do not blind-drop

- `metadata_jobPostId` duplicates: **0** — the primary key is clean
- Same `(company, title, newPostingDate)`: **48,942** rows
- Same `(company, title, newPostingDate, salary_min, salary_max)`: **39,731** rows

**Do not deduplicate on the composite key.** A company posting 5 identical
"Service Crew" roles on the same day with distinct MCF IDs is normal recruiting
behaviour, not a data error, and `numberOfVacancies` is tracked separately. Flag the
group size as a feature if you want to study it; keep every row.

---

## 4. Data filling, per column

The headline is that **there is very little to fill** — after the ghost rows are removed,
zero explicit NaNs remain anywhere in the frame. The filling work is about *implicit*
missingness encoded as `0`.

### 4.1 Fill nothing on the text columns

`categories`, `title`, `employmentTypes`, `positionLevels`, `postedCompany_name`,
`salary_type`, `status_jobStatus`, and the three date columns have **0 NaN** once the
3,988 ghost rows are dropped. No imputation required or justified.

### 4.2 `metadata_totalNumberJobApplication` — 660,363 zeros (63%)

**Do not fill.** Leave as `0`, but treat as ambiguous in analysis.

Zero is genuinely bimodal here: it means "nobody applied" for many listings and "the
counter was not populated at scrape time" for others, and the data gives no way to tell
them apart. Mean-filling would fabricate applications; NaN-ing all 660k would discard the
majority of the column. Add a documented caveat and, where the analysis needs it,
restrict application-rate metrics to rows with `metadata_totalNumberOfView > 0`.

### 4.3 `metadata_totalNumberOfView` — 183,109 zeros (17%)

**Do not fill.** Same reasoning. A posting with 0 views and 0 applications is internally
consistent; note that 17% is low enough that view-based analysis on the non-zero subset
is defensible. Compute an `application_rate = applications / views` only where
`views > 0` — otherwise you get division by zero across 183k rows.

### 4.4 `minimumYearsExperience` — 118,439 zeros (11%)

**Do not fill — `0` is a real value here.** "No prior experience required" is the
expected value for `Fresh/entry level` and `Non-executive` postings, which together are
250k rows. Cross-tabulate against `positionLevels` to confirm the zeros concentrate at
the junior end before relying on this; if they were scattered uniformly across
`Senior Management`, that would indicate a default rather than a value.

### 4.5 Salary columns — fill with `NaN`, not with statistics

Per §3.1, ~7,100 low-sentinel rows and ~279 high-error rows should become `NaN`.

**Do not impute them by median, by group median, or by regression.** Salary is the
dashboard's dependent variable — the thing being measured. Filling missing salaries with
a group median manufactures the very distribution the analysis is trying to observe, and
tightens the variance in a way that will make every confidence interval wrong. Exclude
them from salary aggregates and report the coverage rate (~99.3%) alongside every
salary figure.

If a complete-case column is required downstream (e.g. for a model that cannot accept
NaN), add an explicit `salary_imputed` boolean so the imputation is never invisible.

### 4.6 Derived columns to add rather than fill

| New column | Definition | Why |
|---|---|---|
| `salary_na` | `salary_maximum.isna()` after §3.1 | Replaces the broken all-`False` original |
| `average_salary` | `(min + max) / 2`, recomputed | Currently derived from uncleaned inputs |
| `listing_days` | `expiryDate - newPostingDate` | Median 30, already validated non-negative |
| `is_repost` | `repostCount > 0` | 42,730 rows; cleaner than the 0/1/2 code for filtering |
| `source` | ID prefix (`MCF` / `ATS`) | Distinguishes the 124 ATS rows from the 1.04M MCF rows |
| `primary_category` | First element of parsed `categories` | Convenience for single-category views |

---

## Summary of the pipeline

```
read_csv (1,048,585 × 23)
  ├─ drop columns:  occupationId, status_id, salary_type, salary_na          → 19 cols
  ├─ drop rows:     title.isna()                          −3,988             → 1,044,597
  ├─ drop rows:     jobPostId startswith 'RANDOM_JOB_'    −10                → 1,044,587
  ├─ parse dates:   3 cols → datetime64[ns]
  ├─ fix salary:    max<500 → NaN (~7.1k) · max>100,000 → NaN (~271)
  ├─ recompute:     average_salary, salary_na
  ├─ normalise:     title strip/collapse · company_normalised
  ├─ explode:       categories JSON → job_category bridge table (~1.9M rows)
  ├─ categorise:    employmentTypes, positionLevels, status_jobStatus, postedCompany_name
  └─ downcast:      int8/int16/int32 per §1.3
                                          → ~218 MB (−46%), 0 NaN outside salary
```

**Total rows removed: 3,998 (0.38%). No column with real content is dropped. The only
lossy step in the whole pipeline is the deliberate nulling of implausible salaries,
which is documented, flagged, and reversible from the raw file.**
