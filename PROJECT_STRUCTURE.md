# Job Analytics Dashboard

**A Singapore job market analytics platform with role-based dashboards for hirers, job seekers, and finance business partners.**

> **Staleness note:** the file tree and Finance sections below reflect the
> current code. Where other parts of this doc disagree with `src/`, trust
> the code — see the top-level `README.md` for the up-to-date board list.

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
│   │   └── pipeline.py               # Pipeline orchestrator (Stage 4 = finance)
│   ├── database/           # Database layer
│   │   ├── schema.py            # DuckDB schema definitions
│   │   └── database_manager.py  # DB operations
│   └── dashboard/          # Streamlit UI
│       ├── app.py               # Main dashboard app (nav-chip router)
│       ├── hirer_view.py        # Hirer board
│       ├── seeker_view.py       # Seeker board
│       ├── market_overview.py   # Market Overview board
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

### 👔 Hirer View
Helps hiring teams understand market demand and sourcing strategy.

**Metrics:**
- Total job postings and active companies
- Top hiring roles and salary ranges
- Skills most in-demand
- Hiring trends over time
- Industry-specific breakdowns

**Use Cases:**
- Identify which roles are hardest to fill
- Benchmark salary offers
- Understand emerging skill requirements
- Track hiring velocity

---

### 🔍 Seeker View
Helps job seekers understand market opportunities and benchmark their value.

**Metrics:**
- Total job opportunities matching criteria
- Salary benchmarks by role and experience
- Market competitiveness scores
- High-value skill premiums
- Role growth trends

**Use Cases:**
- Find which roles have most opportunities
- Benchmark salary expectations
- Identify high-paying vs. competitive skills
- Understand market demand for your experience level

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

1. **Data Cleaning** (`src/pipeline/data_cleaning.py`)
   - Drop ghost rows (structurally empty) and synthetic test rows
   - Null out placeholder salaries below a floor, flag statistical outliers
   - Normalize title/company text, strip zero-width characters
   - Flag same-day duplicate postings (doesn't drop them)

2. **Feature Enrichment** (`src/pipeline/feature_enrichment.py`)
   - Rename columns to match the `jobs` table schema
   - Categorize experience levels, extract technical skills via pattern matching
   - Calculate salary midpoints and bands
   - Compute competitiveness scores

3. **Database Loading** (`src/database/database_manager.py`)
   - Insert into DuckDB schema
   - Create analytical views
   - Optimize for query performance

### Output
- **Database:** `data/processed/jobs.duckdb`
- **Tables:**
  - `jobs` - Main cleaned job data
  - `salary_benchmarks` - P25, P50, P75, P90 by role/experience
  - `market_trends` - Historical trends by sector/role
  - `skills_demand` - Skill popularity and salary impact
  - `role_statistics` - Aggregated role metrics
  - `finance_scenario_params` - cost assumptions used for this pipeline run
  - `finance_job_features` - per-posting loaded cost, vacancy exposure, employment cohort
  - `finance_industry_budget_risk` - offline snapshot, exposure ranked by sector
  - `finance_permanent_contract_conversion_economics` - offline snapshot, Savings/Cost premium/Cost neutral by segment

---

## 📈 Key Analyses

### Market Overview & Trends
- **Total Postings:** Market size and hiring volume
- **Company Diversity:** Number of unique employers
- **Role Distribution:** Most common positions
- **Salary Trends:** Historical salary movements

### Benchmarks by User Type

**For Hirers:**
- Competitive salary ranges by role
- Availability of skills in the market
- Time-to-fill metrics
- Regional variations

**For Seekers:**
- Salary expectations by experience level
- Premium skills (highest salary impact)
- Market saturation (competitiveness)
- Career progression paths

### Sector & Sub-Sector Analysis
- Technology, Finance, Healthcare, Consulting, etc.
- Demand patterns within each sector
- Salary variations by sector
- Skills requirements by sector

---

## 🔧 Configuration

Edit `config/settings.py` to customize:

- **Data Thresholds:** Salary min/max filters, duplicate detection
- **Categories:** Experience levels, sectors, job types
- **Dashboard:** Page title, layout, initial state
- **Business Logic:** Hirer/seeker metrics, filters

---

## 👥 Team Assignments (5 Members)

Suggested role distribution:

| Role | Responsibilities |
|------|-----------------|
| **Data Engineer** | Maintain pipeline, DuckDB schemas, data quality |
| **Analytics** | Feature engineering, metrics, analysis queries |
| **Dashboard Dev** | Streamlit UI, visualizations, user experience |
| **Product Manager** | Business logic, requirements, hirer/seeker/finance prioritization |
| **DevOps / Docs** | Deployment, CI/CD, documentation, testing |
| **Finance / FP&A Analyst** | `finance_feature_pipeline.py`, `finance_scenario.py/.json`, `finance_view.py` — loaded-cost model and conversion economics |

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
A: Add queries to `database_manager.py` and new dashboard sections to `app.py`.

**Q: How do I change Finance's cost assumptions?**  
A: Edit `config/finance_scenario.json` (employer burden rates, agency premium, cost-neutral tolerance) — the dashboard reads it live on every render, no pipeline rerun needed. The two exceptions are `salary_planning_cap_quantile` and `min_cohort_postings`, which govern what the pipeline keeps and do need `python -m src.pipeline.pipeline`.

**Q: Is DuckDB production-ready?**  
A: Yes, for read-heavy analytics. For multi-user writes, consider PostgreSQL.

---

## 📧 Support

For questions or issues, reach out to your team lead or create a GitHub issue.

Happy analyzing! 📊
