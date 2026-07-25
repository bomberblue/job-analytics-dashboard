# Job Analytics Dashboard

**A Singapore job market analytics platform with role-based dashboards for hirers and job seekers.**

## 📋 Project Structure

```
job-analytics-dashboard/
├── data/
│   ├── raw/                 # Raw CSV data (SGJobData.csv)
│   └── processed/           # DuckDB database files
├── src/
│   ├── pipeline/           # ETL pipeline
│   │   ├── data_cleaner.py      # Data cleaning logic
│   │   ├── feature_engineer.py  # Feature engineering
│   │   └── pipeline.py          # Pipeline orchestrator
│   ├── database/           # Database layer
│   │   ├── schema.py            # DuckDB schema definitions
│   │   └── database_manager.py  # DB operations
│   └── dashboard/          # Streamlit UI
│       ├── app.py               # Main dashboard app
│       └── utils.py             # Dashboard utilities
├── config/
│   └── settings.py         # Global configuration
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
- ✓ Load and sample the data
- ✓ Clean missing values, standardize fields
- ✓ Extract skills and categorize experience levels
- ✓ Engineer analytical features
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

## 🔄 Data Pipeline

### Input
- **Source:** `SGJobData.csv` (~1M rows)
- **Fields:** Job title, company, salary, experience, skills, description, etc.

### Processing Steps

1. **Data Cleaning** (`src/pipeline/data_cleaner.py`)
   - Handle missing values
   - Parse salary ranges (extract min/max from string formats)
   - Standardize text fields (sectors, experience levels)
   - Remove duplicates
   - Extract technical skills via pattern matching

2. **Feature Engineering** (`src/pipeline/feature_engineer.py`)
   - Calculate salary midpoints and bands
   - Categorize experience levels
   - Count required skills
   - Identify growth roles
   - Compute competitiveness scores
   - Calculate skill premiums (salary impact)

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
| **Product Manager** | Business logic, requirements, hirer/seeker prioritization |
| **DevOps / Docs** | Deployment, CI/CD, documentation, testing |

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
A: Yes! Extend `data_cleaner.py` to handle new CSV formats.

**Q: How do I add new metrics?**  
A: Add queries to `database_manager.py` and new dashboard sections to `app.py`.

**Q: Is DuckDB production-ready?**  
A: Yes, for read-heavy analytics. For multi-user writes, consider PostgreSQL.

---

## 📧 Support

For questions or issues, reach out to your team lead or create a GitHub issue.

Happy analyzing! 📊
