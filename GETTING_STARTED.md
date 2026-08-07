# 🚀 Job Analytics Dashboard - Project Structure Complete

> **Staleness note:** the Finance Business Partner sections below reflect
> the current code. Hirer/Seeker details elsewhere in this doc may lag
> what's actually in `src/dashboard/` — trust the code over this doc where
> they disagree.

Your team project is now fully scaffolded and ready for development!

## 📋 What's Been Created

### 1. **Data Pipeline** (`src/pipeline/`)
- **data_cleaning.py** — Removes ghost/synthetic rows, fixes salary sentinels, normalizes text, flags duplicates
- **feature_enrichment.py** — Renames columns to the schema, standardizes experience levels, extracts skills, creates salary bands
- **finance_feature_pipeline.py** — Builds Finance Business Partner workforce-cost features (loaded cost per head, vacancy budget exposure, contract-vs-permanent conversion economics) from the cleaned `jobs` table and writes the `finance_*` tables
- **pipeline.py** — Orchestrates ETL: Extract CSV → Clean → Engineer → Load to DuckDB → Build finance feature tables (Stage 4)

### 2. **Database Layer** (`src/database/`)
- **schema.py** — DuckDB table definitions (jobs, salary_benchmarks, market_trends, skills_demand)
- **database_manager.py** — Query builder with `.get_seeker_view()`, `.get_hiring_trends()`, `.get_sector_list()`

### 3. **Streamlit Dashboard** (`src/dashboard/`)
- **app.py** — Main dashboard with role-based views (Hirer, Seeker, Finance Partner), switched from a nav-chip row
- **finance_view.py** — Finance Business Partner board: recruitment mix/trend, contract-vs-permanent conversion economics, vacancy budget exposure concentration
- **utils.py** — Dashboard utilities (formatting, caching, helpers)

### 4. **Configuration** (`config/`)
- **settings.py** — Centralized business logic: experience levels, sectors, salary thresholds
- **finance_scenario.py** / **finance_scenario.json** — Finance cost assumptions (employer burden rates, agency premium, cost-neutral tolerance). Read live by the dashboard on every render — editing the JSON changes every cost figure on the Finance board immediately, no pipeline rerun needed (except for the two sample-size/outlier-capping parameters, which do need `python -m src.pipeline.pipeline`)

### 5. **Data Directories** (`data/`)
- **raw/** — Place your SGJobData.csv here
- **processed/** — DuckDB database will be created here

### 6. **Supporting Files**
- **requirements.txt** — Python packages (pandas, duckdb, streamlit, etc.)
- **environment.yml** — Conda environment definition
- **TEAM_GUIDE.md** — Instructions for 5-person team collaboration
- **PROJECT_STRUCTURE.md** — Detailed architecture documentation
- **tests/** — Unit test template (test_pipeline.py)
- **notebooks/** — EDA exploration template

---

## 🎯 Business Logic

### Hirer View 👔
Helps recruitment teams understand **market demand**:
- **Market Overview:** Total postings, active companies, avg salary
- **Top Roles:** Which positions have most openings?
- **Skills in Demand:** What technical skills are most sought?
- **Hiring Trends:** How is hiring volume changing over time?

**Queries:** `src/dashboard/hirer_data_loader.py` (deduplicated market cohorts), plus `db.get_sector_list()`

### Seeker View 🔍
Helps job seekers understand **market opportunities**:
- **Opportunities:** How many jobs match your profile?
- **Top Roles:** Which roles are actively hiring?
- **Salary Benchmarks:** What are realistic salary ranges?
- **Competitive Skills:** Which skills command salary premiums?

**Queries:** `db.get_seeker_view(experience_level=None, sector=None)`

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
[data_cleaning.py]
    • Drop ghost rows and synthetic test rows
    • Null out placeholder salaries, flag statistical outliers
    • Normalize title/company text, strip zero-width characters
    • Flag same-day duplicate postings (doesn't drop them)
    ↓
[feature_enrichment.py]
    • Rename columns to match the jobs table schema
    • Standardize experience levels (junior → Entry Level)
    • Extract skills (Python, SQL, AWS, etc.)
    • Calculate salary midpoints & bands
    ↓
[finance_feature_pipeline.py]
    • Classify employment_cohort (Permanent / Contract / Other)
    • Price loaded monthly cost per head (salary × burden & agency premium rates)
    • Compute vacancy budget exposure and contract-vs-permanent conversion economics
    ↓
[DuckDB]
    jobs (main table)
    ├─ salary_benchmarks (P25, P50, P75, P90)
    ├─ market_trends (historical by date/sector/role)
    ├─ skills_demand (skill popularity & salary impact)
    ├─ role_statistics (aggregated metrics)
    └─ finance_* (scenario_params, job_features, industry_budget_risk,
                  permanent_contract_conversion_economics)
```

---

## 💻 Quick Start for Team

### Person 1: Environment Setup
```bash
cd /path/to/job-analytics-dashboard
conda env create -f environment.yml
conda activate job-analytics
```

### Person 2: Data Preparation
```bash
mkdir -p data/raw
cp ~/path/to/SGJobData.csv data/raw/
```

### Person 3: Run Pipeline
```bash
python src/pipeline/pipeline.py
# Run with smaller dataset first: nrows=50000
```

### Person 4: Verify Database
```bash
# Launch Jupyter or Python shell
from src.database.database_manager import DatabaseManager
db = DatabaseManager()
jobs = db.query("SELECT COUNT(*) FROM jobs")
print(jobs)  # Should show row count
```

### Person 5: Launch Dashboard
```bash
streamlit run src/dashboard/app.py
# Opens http://localhost:8501
```

---

## 📊 Dashboard Features

### Hirer Dashboard
- **Filters:** Sector selection dropdown
- **Metrics:** 4 top-level KPIs (postings, companies, roles, salary)
- **Charts:** Top 3 roles summary, skills demand bar chart, hiring trend line
- **Data:** All queryable by sector

### Seeker Dashboard
- **Filters:** Experience level + sector multi-select
- **Metrics:** 4 opportunity KPIs
- **Tables:** Top opportunities, salary benchmarks
- **Charts:** High-value skills with salary premium

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

### For Hirers (Recruitment Focus)
```python
metrics['market_overview']      # 4 KPIs
metrics['top_roles']            # Top 10 roles by posting count
metrics['skills_in_demand']     # Top 15 skills
metrics['hiring_trends']        # Last 30 days trend
```

### For Seekers (Job Search Focus)
```python
metrics['opportunities']        # 4 opportunity KPIs
metrics['top_roles']            # Top 10 by opportunities
metrics['salary_benchmarks']    # P25, P50, P75, P90 by role
metrics['competitive_skills']   # Top 15 by salary premium
```

### For Finance (FP&A Focus)
```python
# finance_view.py queries finance_job_features directly (not via
# database_manager.py) so loaded cost reflects the live scenario file.
headline_metrics            # postings, total budget exposure, median exposure/opening, contract share
recruitment_type_overview   # Permanent/Contract/Temp mix + median cost + budget exposure
conversion_decision_summary # segments classified Savings / Cost premium / Cost neutral
exposure_by_position_level  # total vacancy budget exposure ranked by position level
slowest_expensive_segments  # watchlist: high posting-window days x high exposure
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
- **Team coordination?** → See [TEAM_GUIDE.md](TEAM_GUIDE.md)
- **Code example?** → Check `notebooks/exploration_template.py`
- **Stuck on a bug?** → Check `tests/test_pipeline.py` for similar patterns

---

## ✅ Success Checklist

Before presenting:
- [ ] Pipeline runs without errors
- [ ] DuckDB contains cleaned data with features
- [ ] Dashboard loads without errors
- [ ] Hirer view shows all 4 metric sections
- [ ] Seeker view shows all 4 metric sections
- [ ] Finance Partner view shows all 3 tabs (Recruitment Trend, Decision 1, Decision 2) and `finance_*` tables are populated
- [ ] Filters work correctly (sector, experience level, and Finance's year/sector/sub-sector/keyword)
- [ ] Charts render properly
- [ ] README and TEAM_GUIDE are up-to-date
- [ ] Tests pass
- [ ] Git history is clean (meaningful commits)

---

**🎉 Ready to build! Your data pipeline infrastructure is set up and ready for implementation.**

Questions? Start with [TEAM_GUIDE.md](TEAM_GUIDE.md) or your instructor!
