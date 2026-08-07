# 🚀 Job Analytics Dashboard - Project Structure Complete

> **Staleness note:** this file is checked against the code as of this
> update. It can still drift as the code changes — where this disagrees
> with `src/`, trust the code.

Your team project is now fully scaffolded and ready for development!

## 📋 What's Been Created

### 1. **Data Pipeline** (`src/pipeline/`)
- **data_cleaning.py** — Removes ghost/synthetic rows, fixes salary sentinels, normalizes text, flags duplicates
- **feature_enrichment.py** — Renames columns to the schema, standardizes experience levels, extracts skills, creates salary bands
- **finance_feature_pipeline.py** — Builds Finance Business Partner workforce-cost features (loaded cost per head, vacancy budget exposure, contract-vs-permanent conversion economics) from the cleaned `jobs` table and writes the `finance_*` tables
- **pipeline.py** — Orchestrates ETL: Extract CSV → Clean → Engineer → Load to DuckDB → Build finance feature tables (Stage 4)

### 2. **Database Layer** (`src/database/`)
- **schema.py** — DuckDB table definitions. Only `jobs` and the `finance_*` tables are ever populated; `salary_benchmarks`, `market_trends`, `skills_demand`, `role_statistics` are declared and created empty but nothing writes to them
- **database_manager.py** — `.query()` (used by Market Overview, Hirer, and Finance) and `.get_sector_list()` (used by Market Overview and Hirer). Seeker bypasses `DatabaseManager` entirely, opening its own cached raw `duckdb.connect()` instead. `.get_seeker_view()` and `.get_hiring_trends()` still exist but aren't called by any board

### 3. **Streamlit Dashboard** (`src/dashboard/`)
- **app.py** — Main dashboard with four boards (Market Overview, Hirer, Seeker, Finance Partner), switched from a nav-chip row
- **market_overview.py** — Market-wide board: pay trends, wage growth decomposition, industry/position composition, market concentration, two cross-view checks
- **finance_view.py** — Finance Business Partner board: recruitment mix/trend, contract-vs-permanent conversion economics, vacancy budget exposure concentration
- **utils.py** — Dashboard utilities (formatting, caching, helpers)

### 4. **Configuration** (`config/`)
- **settings.py** — Centralized business logic: experience levels, sectors, salary thresholds
- **finance_scenario.py** / **finance_scenario.json** — Finance cost assumptions (employer burden rates, agency premium, cost-neutral tolerance, `min_cohort_postings`). Read live by the dashboard on every render — editing the JSON changes every cost figure and `min_cohort_postings`-gated segment on the Finance board immediately. The one exception is `salary_planning_cap_quantile`, read only by the pipeline, which does need `python -m src.pipeline.pipeline` to take effect

### 5. **Data Directories** (`data/`)
- **raw/** — Place your SGJobData.csv here
- **processed/** — DuckDB database will be created here

### 6. **Supporting Files**
- **requirements.txt** — Python packages (pandas, duckdb, streamlit, etc.)
- **environment.yml** — Conda environment definition
- **PROJECT_STRUCTURE.md** — Detailed architecture documentation
- **tests/** — Unit test template (test_pipeline.py)
- **notebooks/** — EDA exploration template

---

## 🎯 Business Logic

### Market Overview 📈
Helps anyone answer "what is the market doing" before drilling into a specific decision:
- **Market Pulse:** headline metrics, industry momentum, salary trend, wage-growth decomposition
- **Market Composition:** top categories, employment-type mix, seasonality
- **Market Structure:** concentration among top companies
- **Cross-View Insight:** does pay actually track how hard a role is to fill, and where do repost risk and vacancy budget exposure concentrate together by industry

**Queries:** `src/dashboard/market_overview.py` — one `fetch_*` function per chart, each via `db.query()`, plus `db.get_sector_list()`

### Hirer View 👔
Helps a hirer decide whether the vacancy they're about to post is priced and configured sensibly, five tabs driven by one persistent vacancy config (sector, position level, experience level, planned salary, minimum years):
- **Salary benchmark:** what comparable postings pay
- **Experience norms:** how much experience postings at this level typically ask for
- **Applicant response:** applications and under-fill risk by pay band
- **Reach vs conversion:** whether a low-paying posting's problem is views or conversion
- **Repost risk:** which pay-band/experience-ask combinations get reposted most

**Queries:** `src/dashboard/hirer_data_loader.py` (deduplicated market cohorts), plus `db.get_sector_list()`

### Seeker View 🔍
Helps a candidate judge one specific offer against the market:
- **Pay fairness & market position:** salary percentile for their pay against comparable postings
- **Pay by experience / seniority ladder:** how pay moves with years of experience
- **Competition per opening:** how contested a role or industry is
- **Best opportunities & salary benchmarks:** where pay is strong and competition is low

**Queries:** `src/dashboard/seeker_view.py` — its own cached functions against a preloaded deduplicated-market DataFrame, not `database_manager.py`'s `get_seeker_view()` (unused)

### Finance Business Partner View 💼
Helps FP&A translate workforce-mix and hiring-speed decisions into dollars:
- **Recruitment Trend:** Permanent/Contract/Temp mix and how it's moving month over month
- **Decision 1 — Contract Conversion:** which sector × sub-sector × position-level segments would save money, cost more, or be cost-neutral if converted between contract and permanent (requires ≥30 postings per cohort to be comparable)
- **Decision 2 — Exposure Concentration:** where estimated vacancy budget exposure concentrates by position level, plus a watchlist of slow-to-fill, high-exposure segments

**Queries:** `finance_view.py` queries `finance_job_features` directly with `db.query()` — it does **not** go through `database_manager.py`'s `get_*_view()` pattern, because loaded cost is re-priced live from `config/finance_scenario.json` on every render rather than read as-stored.

---

## 🔄 Data Pipeline Flow

```
SGJobData.csv (raw)
    ↓
[Stage 1: insert_raw_jobs()]
    • Loads the CSV completely unmodified into raw_jobs_flat (audit trail)
    ↓
[Stage 2a: data_cleaning.py]
    • Drop ghost rows and synthetic test rows
    • Null out placeholder salaries, flag statistical outliers
    • Normalize title/company text, strip zero-width characters
    • Flag same-day duplicate postings (doesn't drop them)
    ↓
[Stage 2b: feature_enrichment.py]
    • Rename columns to match the jobs table schema
    • Standardize experience levels
    • Extract skills (title-keyword matches only -- no description field exists)
    • Calculate salary midpoints & bands
    ↓
[Stage 3: insert_jobs()]
    • Loads the cleaned, enriched frame into the jobs table
    ↓
[Stage 4: finance_feature_pipeline.py]
    • Classify employment_cohort (Permanent / Contract / Other)
    • Price loaded monthly cost per head (salary × burden & agency premium rates)
    • Compute vacancy budget exposure and contract-vs-permanent conversion economics
    ↓
[DuckDB]
    raw_jobs_flat (unmodified source rows, for lineage)
    jobs (cleaned + enriched, what every board reads)
    finance_* (scenario_params, job_features, industry_budget_risk,
               permanent_contract_conversion_economics)

    (role_statistics, salary_benchmarks, market_trends, skills_demand are
     also declared in schema.py, but nothing in the pipeline writes to them)
```

---

## 📊 Dashboard Features

### Market Overview Dashboard
- **Filters:** Sector, position level
- **Tabs:** Market Pulse · Market Composition · Market Structure · Cross-View Insight
- **Data:** All tabs re-run their `fetch_*` queries on every filter change

### Hirer Dashboard
- **Filters:** Sector, position level, experience level, planned salary, minimum years — shown per-tab, only the ones that tab actually reads (`TAB_CONTROLS` in `hirer_view.py`)
- **Tabs:** Salary benchmark · Experience norms · Applicant response · Reach vs conversion · Repost risk
- **Data:** Benchmarked against a deduplicated market cohort (`hirer_data_loader.py`)

### Seeker Dashboard
- **Filters:** Industry, experience level, your salary
- **Sections:** Pay fairness & market position, pay by years of experience, seniority ladder, pay-range width by industry/level, competition per opening, best opportunities, salary benchmarks, high-value skills

### Finance Partner Dashboard
- **Filters:** Year, Sector, Sub-sector, optional skill/keyword focus
- **Metrics:** 4 headline KPIs — postings in finance model, estimated vacancy cost exposure, median exposure per opening, contract share of postings
- **Tabs:** Recruitment Trend (mix + monthly trend chart) · Decision 1: Contract Conversion (savings/cost-premium/cost-neutral segments) · Decision 2: Exposure Concentration (bar chart by position level + slow-to-fill watchlist)
- **Live-editable:** cost assumptions in `config/finance_scenario.json` change every dollar figure on next page interaction, no pipeline rerun required

---

## 🔧 Module Responsibilities

| Component | Owner | Key Operations |
|-----------|-------|-----------------|
| **Pipeline** | Data Eng | Extract CSV, clean, feature engineer, load |
| **Database** | Analytics | Build queries, aggregations, benchmarks |
| **Dashboard** | Frontend | UI/UX, filters, visualizations |
| **Config** | All | Business logic (sectors, categories, thresholds) |
| **Testing** | QA | Unit tests, pipeline validation |

---

## 📈 Key Metrics Architecture

Hirer has no `metrics[...]` dict, just standalone functions. Seeker has both:
five standalone functions for its first five sections, plus one `metrics`
dict (from `_cached_seeker_metrics()`) for the last three.

### For Hirers — `src/dashboard/hirer_data_loader.py`
```python
salary_lookup(sector, position_level, experience_level, yrs_bucket)  # benchmark for this config
config_norms(sector)          # experience asked, by position level
response_by_pay_band(sector)  # applications + under-fill risk, by pay band
funnel_by_pay_band(sector)    # views vs. conversion, by pay band
repost_matrix(sector)         # repost rate by pay band x years required
repost_contrast(sector)       # repost rate below vs. at/above 3 years required
```

### For Seekers — `src/dashboard/seeker_view.py`
```python
fetch_salary_percentile(db, industry, experience_level, salary)      # your pay's percentile
fetch_pay_by_experience_years(db, industry)                          # pay vs. years of experience
fetch_seniority_ladder(db, industry, experience_level)
fetch_pay_range_by_industry_level(db, industry, experience_level)
fetch_competition_metrics(db, industry, experience_level)             # applicants per opening

# _cached_seeker_metrics() -- powers Best Opportunities, Salary Benchmarks,
# High-Value Skills. Bypasses DatabaseManager: opens its own cached raw
# duckdb.connect(), not db.query().
metrics['opportunities']        # opportunity count
metrics['top_roles']            # roles behind Best Opportunities
metrics['salary_benchmarks']    # p25 (real quantile), median_entry/median_max (mean), p90 (max) -- by job label + experience level
metrics['competitive_skills']   # High-Value Skills
```

### For Finance (FP&A Focus)
```python
# finance_view.py queries finance_job_features directly (not via
# database_manager.py) so loaded cost reflects the live scenario file.
_fetch_headline_metrics            # postings, total budget exposure, median exposure/opening, contract share
_fetch_recruitment_type_overview   # Permanent/Contract/Temp mix + median cost + budget exposure
_fetch_conversion_decision_summary # segments classified Savings / Cost premium / Cost neutral
_fetch_exposure_by_position_level  # total vacancy budget exposure ranked by position level
_fetch_slowest_expensive_segments  # watchlist: high posting-window days x high exposure
```

---

## 🎓 Learning Outcomes

Upon completion, your team will have:
✅ Handled real-world messy data (1M+ rows)  
✅ Built an ETL pipeline (Extract → Transform → Load)  
✅ Used DuckDB for analytical queries  
✅ Created a multi-view interactive dashboard  
✅ Collaborated across data, analytics, and engineering roles  
✅ Presented data-driven business insights  

---

## 🚨 Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| "Module not found" error | Run from project root: `cd job-analytics-dashboard` |
| Database is empty | Check pipeline ran without errors; verify SGJobData.csv exists |
| Dashboard shows "No data" | Restart Streamlit; check DB connection in `app.py` |
| Salary parsing fails | Adjust regex in `data_cleaning.py` if format differs |
| Slow queries | Add indexes or use `LIMIT` clause for testing |

---

## 📚 Next Steps

1. **Immediate (Today)**
   - Set up conda environment
   - Copy data to `data/raw/`
   - Run pipeline: `python src/pipeline/pipeline.py`

2. **Tomorrow**
   - Explore data: Run `notebooks/exploration_template.py`
   - Validate metrics in `database_manager.py`

3. **This Week**
   - Build Hirer view dashboard
   - Build Seeker view dashboard
   - Add unit tests

4. **Next Week**
   - Polish UI/UX
   - Create presentation slides
   - Dry run presentation

---

## 💡 Pro Tips

1. **Start with sample data** (50k rows) before full 1M row load
2. **Test each module independently** before integration
3. **Use Git branches** for parallel work: `git checkout -b feature/your-task`
4. **Document as you go** — add docstrings to functions
5. **Daily syncs** (5 min) to unblock team members
6. **Push daily** to avoid merge conflicts

---

## 📞 Support

- **Architecture question?** → See [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
- **Code example?** → Check `notebooks/exploration_template.py`
- **Stuck on a bug?** → Check `tests/test_pipeline.py` for similar patterns

---

## ✅ Success Checklist

Before presenting:
- [ ] Pipeline runs without errors
- [ ] DuckDB contains cleaned data with features
- [ ] Dashboard loads without errors
- [ ] Market Overview shows all 4 tabs (Market Pulse, Market Composition, Market Structure, Cross-View Insight)
- [ ] Hirer view shows all 5 tabs (Salary benchmark, Experience norms, Applicant response, Reach vs conversion, Repost risk)
- [ ] Seeker view shows its pay-fairness, seniority, competition, and best-opportunities sections
- [ ] Finance Partner view shows all 3 tabs (Recruitment Trend, Decision 1, Decision 2) and `finance_*` tables are populated
- [ ] Filters work correctly (sector/position level, a vacancy config for Hirer, industry/experience/salary for Seeker, and Finance's year/sector/sub-sector/keyword)
- [ ] Charts render properly
- [ ] README is up-to-date
- [ ] Tests pass
- [ ] Git history is clean (meaningful commits)

---

**🎉 Ready to build! Your data pipeline infrastructure is set up and ready for implementation.**

Questions? Start with [README.md](README.md) or your instructor!
