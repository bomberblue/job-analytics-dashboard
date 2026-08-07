# Job Analytics Dashboard

**A Singapore job market analytics platform with role-based dashboards for hirers, job seekers, and finance business partners.**

> **Staleness note:** this file is checked against the code as of this
> update. It can still drift as the code changes — where this disagrees
> with `src/`, trust the code — see the top-level `README.md` for the
> up-to-date board list.

## 📋 Project Structure

```
job-analytics-dashboard/
├── data/
│   ├── raw/                 # Raw CSV data (SGJobData.csv)
│   └── processed/           # DuckDB database files
├── src/
│   ├── pipeline/           # ETL pipeline
│   │   ├── data_cleaning.py           # Data cleaning logic
│   │   ├── feature_enrichment.py      # Feature engineering
│   │   ├── finance_feature_pipeline.py # Finance cost/budget-risk features
│   │   └── pipeline.py               # Orchestrator: Stage 1 raw load, 2 clean+enrich, 3 processed load, 4 finance
│   ├── database/           # Database layer
│   │   ├── schema.py            # DuckDB schema definitions
│   │   └── database_manager.py  # DB operations
│   ├── audit/
│   │   └── data_audit.py        # Raw/processed data-quality and lineage checks
│   └── dashboard/          # Streamlit UI
│       ├── app.py               # Main dashboard app (nav-chip router)
│       ├── market_overview.py   # Market Overview board
│       ├── hirer_view.py        # Hirer board
│       ├── seeker_view.py       # Seeker board
│       ├── finance_view.py      # Finance Business Partner board
│       ├── hirer_data_loader.py # Deduplicated market cohorts for Hirer
│       ├── charts.py            # Shared chart helpers
│       ├── theme.py             # Shared color/theme constants
│       └── utils.py             # Dashboard utilities
├── config/
│   ├── settings.py              # Global configuration
│   ├── finance_scenario.py      # Loads finance cost assumptions
│   └── finance_scenario.json    # Editable: burden rates, agency premium, tolerance
├── notebooks/              # Jupyter notebooks for exploration
├── tests/                  # Unit tests
├── requirements.txt        # Python dependencies
├── environment.yml         # Conda environment
└── README.md              # This file
```

## 🚀 Quick Start

### 1. Setup Environment

**Option A: Using Conda**
```bash
conda env create -f environment.yml
conda activate job-analytics
```

**Option B: Using pip**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Prepare Data

Move your `SGJobData.csv` to the correct location:
```bash
mkdir -p data/raw
cp /path/to/SGJobData.csv data/raw/
```

### 3. Run ETL Pipeline

Transform raw CSV into DuckDB:
```bash
python src/pipeline/pipeline.py
```

This will:
- ✓ Load the raw CSV
- ✓ Drop ghost/synthetic rows, fix salary sentinels, normalize text, flag duplicates
- ✓ Rename columns to the schema, categorize experience levels, extract skills
- ✓ Load into DuckDB

### 4. Launch Dashboard

```bash
streamlit run src/dashboard/app.py
```

Visit `http://localhost:8501` in your browser.

---

## 📊 Dashboard Features

### 📈 Market Overview
Helps anyone answer "what is the market doing" before drilling into a
specific decision.

**Tabs:** Market Pulse (headline metrics, industry momentum, salary trend,
wage-growth decomposition) · Market Composition (top categories,
employment-type mix, seasonality) · Market Structure (concentration among
top companies) · Cross-View Insight (does pay track how hard a role is to
fill, and where do repost risk and vacancy budget exposure concentrate
together by industry)

**Filters:** Sector, position level

---

### 👔 Hirer View
Helps a hirer decide whether the vacancy they're about to post is priced
and configured sensibly, driven by one persistent vacancy config.

**Tabs:** Salary benchmark (what comparable postings pay) · Experience
norms (how much experience postings at this level typically ask for) ·
Applicant response (applications and under-fill risk by pay band) · Reach
vs conversion (views vs. conversion problem) · Repost risk (which
pay-band/experience-ask combinations get reposted most)

**Filters:** Sector, position level, experience level, planned salary,
minimum years — each tab only shows the ones it actually reads

---

### 🔍 Seeker View
Helps a candidate judge one specific offer against the market.

**Sections:** Pay fairness & market position (salary percentile against
comparable postings) · Pay by years of experience · Seniority ladder ·
Pay-range width by industry & level · Competition per opening · Best
opportunities · Salary benchmarks · High-value skills

**Filters:** Industry, experience level, your salary

---

### 💼 Finance Business Partner View
Helps FP&A translate workforce-mix and hiring-speed decisions into dollars.

**Metrics:**
- Estimated vacancy cost exposure and median exposure per opening
- Contract share of postings
- Recruitment mix (Permanent/Contract/Temp) and its monthly trend
- Contract-vs-permanent conversion economics by segment

**Use Cases:**
- Approve or challenge shifting budgeted headcount to contract staffing
- Identify which sector × position-level segments would genuinely save money if converted (vs. cost premium or cost-neutral)
- Find where vacancy budget exposure concentrates, and which slow-to-fill segments are also the most expensive
- Tune cost assumptions (employer burden, agency premium) live via `config/finance_scenario.json` without rerunning the pipeline

---

## 🔄 Data Pipeline

### Input
- **Source:** `SGJobData.csv` (~1M rows)
- **Fields:** Job title, company, salary, experience, skills, description, etc.

### Processing Steps

0. **Raw Load** (`src/pipeline/pipeline.py`'s `load_raw()`, Stage 1)
   - Loads the CSV completely unmodified into `raw_jobs_flat`, for audit/lineage

1. **Data Cleaning** (`src/pipeline/data_cleaning.py`, Stage 2a)
   - Drop ghost rows (structurally empty) and synthetic test rows
   - Null out placeholder salaries below a floor, flag statistical outliers
   - Normalize title/company text, strip zero-width characters
   - Flag same-day duplicate postings (doesn't drop them)

2. **Feature Enrichment** (`src/pipeline/feature_enrichment.py`, Stage 2b)
   - Rename columns to match the `jobs` table schema
   - Categorize experience levels, extract skills via title-keyword matching (no description field exists to match against)
   - Calculate salary midpoints and bands
   - Also computes `skill_count`/`salary_band`/`competitiveness_score` for notebook analysis, but these are filtered out before the database write below — they're not in the `jobs` table

3. **Database Loading** (`src/database/database_manager.py`'s `insert_jobs()`, Stage 3)
   - Drops and recreates the `jobs` table, then a plain bulk insert
   - No analytical views or indexes are created

### Output
- **Database:** `data/processed/jobs.duckdb`
- **Tables actually written:**
  - `raw_jobs_flat` - unmodified source rows, for lineage (Stage 1)
  - `jobs` - cleaned + enriched, what every board reads (Stage 3)
  - `finance_scenario_params` - cost assumptions used for this pipeline run (Stage 4)
  - `finance_job_features` - per-posting loaded cost, vacancy exposure, employment cohort (Stage 4)
  - `finance_industry_budget_risk` - offline snapshot, exposure ranked by sector (Stage 4)
  - `finance_permanent_contract_conversion_economics` - offline snapshot, Savings/Cost premium/Cost neutral by segment (Stage 4)
- **Declared in `schema.py` but never populated** — created empty, nothing writes to them, no board reads them:
  - `salary_benchmarks`, `market_trends`, `skills_demand`, `role_statistics`

---

## 📈 Key Analyses

See "Dashboard Features" above for what each board actually shows — this
section previously duplicated that with different, inaccurate detail (e.g.
"Time-to-fill metrics" and "Regional variations" aren't things any board
computes; the data is Singapore-only, and reposting/under-fill are the
closest proxies the Hirer board actually has for "hard to fill"). Reporting
is by 43 industries (parsed from a JSON category field) and 9 position
levels, not by the ~365k raw job titles, which are too fragmented to group
directly.

---

## 🔧 Configuration

Edit `config/settings.py` to customize:

- **Data Thresholds:** Salary min/max filters, duplicate detection
- **Categories:** Experience levels, sectors, job types
- **Dashboard:** Page title, layout, initial state
- **Business Logic:** Hirer/seeker metrics, filters

---

## 🧪 Testing

Run unit tests:
```bash
pytest tests/
```

---

## 📝 Development Workflow

1. Create feature branch: `git checkout -b feature/your-feature`
2. Make changes and test locally
3. Run pipeline: `python src/pipeline/pipeline.py`
4. Test dashboard: `streamlit run src/dashboard/app.py`
5. Commit and push: `git push origin feature/your-feature`
6. Create pull request with description

---

## 🚀 Deployment (Future)

Deployment options:
- **Streamlit Cloud:** Connect repo directly
- **Docker:** Containerize the app
- **Cloud Functions:** Serverless pipeline runs
- **Database:** Migrate to cloud DuckDB or PostgreSQL

---

## 📚 Next Steps

- [ ] Implement advanced filtering (multi-select, date ranges)
- [ ] Add export functionality (CSV, PDF reports)
- [ ] Create admin panel for data refresh
- [ ] Build predictive models (salary prediction, demand forecasting)
- [ ] Add more visualizations (geographic heatmaps, skill trees)
- [ ] Implement caching strategy for performance
- [ ] Set up automated pipeline runs (daily/weekly)

---

## ❓ FAQ

**Q: How often is data updated?**  
A: Currently manual. Automate via scheduled tasks for production.

**Q: Can I add more data sources?**  
A: Yes! Extend `data_cleaning.py` to handle new CSV formats.

**Q: How do I add new metrics?**  
A: Add a `fetch_*` function with its own SQL to the relevant board's module (e.g. `market_overview.py`, `hirer_data_loader.py`) and call it from that board's `render_*` function — each board owns its own queries rather than going through a shared `database_manager.py` aggregator.

**Q: How do I change Finance's cost assumptions?**  
A: Edit `config/finance_scenario.json` (employer burden rates, agency premium, cost-neutral tolerance, `min_cohort_postings`) — the dashboard reads it live on every render, no pipeline rerun needed; `min_cohort_postings` in particular takes effect immediately on the Decision 1 tab (`finance_view.py`'s `_conversion_base_sql()`). The one true exception is `salary_planning_cap_quantile`, which only the pipeline reads (`finance_feature_pipeline.py`) and does need `python -m src.pipeline.pipeline` to take effect.

**Q: Is DuckDB production-ready?**  
A: Yes, for read-heavy analytics. For multi-user writes, consider PostgreSQL.

---

## 📧 Support

For questions or issues, reach out to your team lead or create a GitHub issue.

Happy analyzing! 📊
