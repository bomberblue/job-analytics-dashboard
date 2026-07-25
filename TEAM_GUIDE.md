## Team Assignment: Singapore Jobs Analytics Dashboard

### 🎯 Project Overview

This is a **team data project** to build an analytics platform for Singapore's job market. You'll:
- Transform raw CSV data (~1M rows) into a DuckDB database
- Build analytical features for hirers and job seekers
- Create an interactive Streamlit dashboard
- Present insights and learnings

### 👥 Team Structure (5 Members)

**Suggested Roles:**

| Member | Role | Key Tasks |
|--------|------|-----------|
| **Member 1** | **Data Pipeline Lead** | - Manage `src/pipeline/` modules<br>- Ensure data quality and pipeline integrity<br>- Lead data cleaner and feature engineer testing |
| **Member 2** | **Analytics Engineer** | - Build queries in `database_manager.py`<br>- Create salary benchmarks and aggregations<br>- Validate business metrics accuracy |
| **Member 3** | **Dashboard Developer** | - Build Streamlit UI in `src/dashboard/`<br>- Create hirer & seeker views<br>- Design visualizations and interactivity |
| **Member 4** | **Product / QA** | - Define business requirements<br>- Test dashboard functionality<br>- Verify hirer/seeker features work correctly |
| **Member 5** | **DevOps / Documentation** | - Set up testing framework (`tests/`)<br>- Write and maintain documentation<br>- Prepare deployment package |

---

### 📅 Workflow & Milestones

#### Week 1: Setup & Data Exploration
- [ ] Clone and explore project structure
- [ ] Set up local environment (conda/venv)
- [ ] Run EDA on raw data (use `notebooks/exploration_template.py`)
- [ ] **Milestone:** Team confirms data understanding and column mappings

#### Week 2: Pipeline & Database
- [ ] Data Pipeline Lead + Analytics Engineer: finalize cleaning logic
- [ ] Run full ETL pipeline (`python src/pipeline/pipeline.py`)
- [ ] Validate DuckDB schema and record counts
- [ ] Build core analytics queries
- [ ] **Milestone:** DuckDB populated with clean, feature-engineered data

#### Week 3: Dashboard & Presentation
- [ ] Dashboard Dev + Analytics: build hirer/seeker views
- [ ] DevOps: add tests, finalize docs
- [ ] All: review dashboard locally
- [ ] **Milestone:** Dashboard launches and all metrics display correctly

#### Week 4: Presentation Prep
- [ ] Create presentation slides (business case + demo)
- [ ] Finalize visualizations and messaging
- [ ] Dry run presentation
- [ ] **Milestone:** Team presents to class (10 min)

---

### 🚀 Getting Started

1. **One person:** Clone the repo
   ```bash
   git clone <your-repo-url>
   cd job-analytics-dashboard
   ```

2. **Everyone:** Set up local environment
   ```bash
   conda env create -f environment.yml
   conda activate job-analytics
   ```

3. **Data Lead:** Prepare raw data
   ```bash
   mkdir -p data/raw
   # Copy SGJobData.csv to data/raw/
   ```

4. **Data Lead:** Run pipeline
   ```bash
   python src/pipeline/pipeline.py
   ```

5. **Everyone:** Explore the data
   ```bash
   # Run queries in notebooks/exploration_template.py
   # Understand the schema and metrics
   ```

---

### 📊 Dashboard Requirements

#### Business Case
Your dashboard addresses **two distinct user groups**:

**1. Hirers** — Recruitment teams finding talent and planning hiring strategy
- *Use Case:* "Which roles are hardest to fill? What skills should we prioritize?"
- *Key Metrics:* Demand trends, salary benchmarks, skill premiums

**2. Job Seekers** — Professionals evaluating opportunities and career growth
- *Use Case:* "What's my market value? Which roles have the most opportunities?"
- *Key Metrics:* Salary benchmarks, competitiveness, high-value skills

#### Core Features

**Hirer Dashboard:**
- Market overview (total postings, active companies, avg salary)
- Top hiring roles and trends
- Skills most in-demand
- Industry/sector-specific breakdowns
- Filter by sector

**Seeker Dashboard:**
- Opportunities matching your profile
- Salary benchmarks by role & experience level
- Competitive skill analysis
- Role growth and market trends
- Filter by experience level and sector

---

### 📁 Key Files & Responsibilities

| Component | Owner | Key Files |
|-----------|-------|-----------|
| **Data Pipeline** | Member 1 | `src/pipeline/data_cleaner.py`, `feature_engineer.py`, `pipeline.py` |
| **Database** | Member 2 | `src/database/schema.py`, `database_manager.py` |
| **Dashboard UI** | Member 3 | `src/dashboard/app.py`, `utils.py` |
| **Configuration** | All | `config/settings.py` (business logic) |
| **Tests** | Member 5 | `tests/test_pipeline.py` |
| **Docs** | Member 5 | `PROJECT_STRUCTURE.md`, `README.md` |

---

### 💡 Tips for Success

1. **Start small:** Test pipeline with first 50k rows before full data load
2. **Divide & conquer:** Each person owns their module; integrate incrementally
3. **Test frequently:** Run `streamlit run src/dashboard/app.py` after each change
4. **Communicate:** Daily stand-ups (5 min) to unblock issues
5. **Document:** Add comments explaining business logic
6. **Git workflow:** Use feature branches (`feature/hirer-view`), PR reviews

---

### 🔧 Common Commands

```bash
# Activate environment
conda activate job-analytics

# Run pipeline (Data Engineer)
python src/pipeline/pipeline.py

# Explore data (Analyst)
python notebooks/exploration_template.py

# Launch dashboard (Dashboard Dev)
streamlit run src/dashboard/app.py

# Run tests (QA)
pytest tests/

# Update git
git add .
git commit -m "Add hirer view dashboard"
git push origin feature/your-feature
```

---

### ❓ FAQ

**Q: Data Lead ran pipeline but database is empty?**  
A: Check that `data/raw/SGJobData.csv` exists. Run with `nrows=5000` first to debug.

**Q: Dashboard shows "No data available" for metrics?**  
A: Ensure pipeline ran successfully. Try `db.query("SELECT COUNT(*) FROM jobs")` in a notebook.

**Q: How do I add a new metric for hirers?**  
A: Add query to `database_manager.get_hirer_view()`, then display in `app.py`.

**Q: Can we change the experience level categories?**  
A: Yes! Edit `config/settings.py` and rerun pipeline.

**Q: How do I merge my feature branch?**  
A: Push, create PR with description, get 1 review, then merge to `main`.

---

### 📈 Success Criteria

Your dashboard should:
- ✅ Load and display data without errors
- ✅ Show different views for hirers vs. seekers
- ✅ Include at least 3 metrics per user type
- ✅ Have interactive filters (sector, experience level)
- ✅ Display charts and summary statistics
- ✅ Be deployed or runnable locally
- ✅ Have clear, professional styling

---

### 🎓 Learning Objectives

By completing this project, you will:
- 📊 **Load & explore** large CSV datasets
- 🧹 **Clean & standardize** messy real-world data
- 🗄️ **Design & use** relational databases (DuckDB)
- 📈 **Engineer features** for analytics
- 🎨 **Build interactive** web dashboards
- 👥 **Collaborate** on a team project
- 📢 **Present** findings and business value

---

### 📧 Questions?

Reach out to your instructor or team lead!

**Good luck! 🚀**
