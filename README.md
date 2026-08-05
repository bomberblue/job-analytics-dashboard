# job-analytics-dashboard

A Streamlit + DuckDB dashboard over roughly 1 million Singapore job postings,
built around one question: what should a job pay, and how much leverage does
each side (hirer, candidate, finance) actually have. Postings are reported by
industry (43 categories, parsed from raw JSON) and position level (9 levels),
not by the ~365k raw job titles, which are too fragmented to group.

## Boards

The dashboard has four boards, reachable from one nav row at the top of the
app - there's no separate page per role, just a single Streamlit app that
switches which board renders.

- **Market Overview** - market-wide pay trends, wage growth decomposition,
  industry/position composition, market concentration, and a cross-view check
  on whether pay actually tracks how hard a role is to fill.
- **Hirer** - benchmark a planned salary against comparable postings, check
  experience norms for a sector/level, and diagnose why a vacancy might be
  under-filling or getting reposted.
- **Seeker** - check your own pay against the market, and see how competitive
  a role or industry is before applying.
- **Finance Business Partner** - workforce-cost mix (contract vs. permanent)
  and where vacancy budget risk concentrates.

## Project layout

```
config/            Centralized settings: paths, DB file location, finance
                    scenario assumptions (config/finance_scenario.py/.json)
data/
  raw/              SGJobData.csv goes here (gitignored)
  processed/        jobs.duckdb is built here (gitignored)
src/
  pipeline/         Extract -> clean -> enrich -> load, plus the finance
                    feature pipeline (data_cleaning.py, feature_enrichment.py,
                    finance_feature_pipeline.py, pipeline.py)
  database/         DuckDB schema and query manager
  dashboard/        The four boards above, plus shared chart/theme/utils
                    modules and app.py (the entry point)
notebooks/          EDA and pipeline-development notebooks
tests/              pytest suite for the pipeline and Market Overview's
                    query layer
```

`ARCHITECTURE.md` and a few other top-level docs predate the current state of
this project and are only partly accurate - if something there disagrees with
the code or the database, trust the code.

## Setup

Requires conda (Miniconda or Anaconda) and the raw `SGJobData.csv` file
(not included in this repo).

```bash
./setup.sh
```

This creates the `job-analytics` conda environment from `environment.yml` and
creates the `data/` subdirectories. Or do it by hand:

```bash
conda env create -f environment.yml
conda activate job-analytics
mkdir -p data/raw data/processed
```

Then:

```bash
# 1. Copy the raw data in
cp /path/to/SGJobData.csv data/raw/

# 2. Run the pipeline (cleans, enriches, and loads everything into
#    data/processed/jobs.duckdb, including the finance_* feature tables)
python -m src.pipeline.pipeline

# 3. Launch the dashboard
streamlit run src/dashboard/app.py
```

The dashboard opens at `http://localhost:8501`. If `data/processed/jobs.duckdb`
is missing (e.g. a fresh Streamlit Cloud deploy) and R2 credentials are
configured in `st.secrets`, `app.py` downloads a prebuilt copy automatically
instead of requiring a local pipeline run.

## Tests

```bash
python -m pytest tests/
```

Covers the pipeline (cleaning, enrichment, schema) and Market Overview's query
layer. Verify dashboard changes with `streamlit.testing.v1.AppTest` rather than
eyeballing - the boards switch via the nav buttons in `app.py`, not a sidebar
or URL route.
