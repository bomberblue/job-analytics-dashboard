# Singapore Jobs Analytics — Project Report

**Module 1 Coaching Assignment Project**
Dataset: `SGJobData.csv` — 1,048,585 Singapore job postings, Mar 2023 – May 2024
Stack: Python · pandas · DuckDB · Streamlit · Altair

This report covers Sections 1–4 of the assignment brief. Supporting artefacts:

| Artefact | Location |
|---|---|
| Presentation deck | `docs/job-analytics-hirer-deck.pptx` |
| Data handling notebooks | `notebooks/` (6 notebooks — see §2) |
| Cleaning decisions — the *why* behind each choice | `docs/data-cleaning-decisions.md` |
| Cleaning run record — what the pipeline *did*, generated from the live run | `docs/data-cleaning-report-generated.md` |
| Dashboard code | `src/dashboard/` |
| Pipeline code | `src/pipeline/`, `src/database/` |
| Setup & run instructions | `README.md` |

---

## 1. Business Case

- **Scenario** — One market question, asked by four people who each control a different lever: *what should this role pay, and how much leverage does each side actually have?* A talent acquisition lead at a Singapore SME is about to post a vacancy and must set the pay range, the minimum years of experience, and the position level — today, from what they paid last time or a colleague's guess. A candidate is judging whether an offer is fair. A finance business partner is sizing headcount budget and conversion risk. All three read against the same market view.

- **Objective** — Give each user the reference point they currently lack, and support a specific decision rather than general market curiosity:

  | Board | The decision it supports |
  |---|---|
  | **Hirer** | Is this configuration normal, and what response did configurations like it actually get? |
  | **Seeker** | Is my pay fair for this role, and how contested is it before I apply? |
  | **Finance** | Where do vacancy cost exposure and contract-conversion risk concentrate? |
  | **Market Overview** | What is the market doing — and does pay actually track how hard a role is to fill? |

- **Target users & value** — Four boards over one cleaned dataset, so the hirer, the candidate, and the finance partner argue from the same numbers instead of three incompatible ones. The cost of getting it wrong is measurable in the data: **30% of postings end up under-filled** and **17.8% get reposted** — both of which the analysis traces back to pay far more than to the experience bar.

*Depth case.* This report and the accompanying deck drill into the **hirer**, because that is where the engagement data (Layer 2, §2) pays off most directly — it is the only board whose central claim depends on what postings *got* rather than what they *said*. The other three boards rest on the same cleaned dataset and the same Layer 1 / Layer 2 split described in §2.

---

## 2. Data Handling & Process

- **Tools & scale** — Python with pandas for cleaning and feature derivation; DuckDB as the analytical store; Streamlit for the app. The brief suggests prototyping on a 50,000-row sample — we developed that way but **ran the final pipeline over the full 1,048,585 rows**, because the cohort filtering in §2 below leaves only ~79k usable rows for the engagement analysis, and a 50k sample would not have survived it.

- **Notebooks** — Six notebooks in `notebooks/` carry the data work:
  - `data_cleaning.ipynb` — the 15-step cleaning walkthrough, from raw CSV to saved dataset, ending by auto-generating `docs/data-cleaning-report-generated.md` from the live run.
  - `data_exploration.ipynb` — schema overview and salary-outlier profiling.
  - `hirer_layer1_analysis.ipynb` — "what is normal": market shape, salary benchmarks, configuration norms, competition density.
  - `hirer_layer2_analysis.ipynb` — "what response did it get": cohort construction, response benchmarks, the reach-vs-conversion funnel, repost risk, significance testing.
  - `finance_data_exploration.ipynb` and `finance_workforce_cost_budget_risk_features.ipynb` — workforce cost, budget-risk features, and Progressive Wage Model review flags.

  The notebooks **import** `src/pipeline/` rather than reimplementing it, so notebook and production pipeline cannot drift apart.

- **Cleaning — 3,998 rows removed (0.38%), 0 cells imputed.** Removals are structurally-empty ghost rows plus `RANDOM_JOB_` synthetic test rows. Nothing was imputed: salary is the quantity being measured, so filling it would break the assumption every downstream figure rests on. Salary coverage after cleaning is **99.0%**.

- **Cleaning — bad salaries get a reason code, not a repair.** A `salary_flag` column takes `undisclosed · outlier · low_stipend · ok`. The 1,804 postings at `$1–$1` are a required-field placeholder with no real value to preserve at any resolution, so they are nulled (9,577 rows total, under 1%). The 269 postings above `$100,000/month` might be a real C-suite role or a missing decimal — that depends on the question being asked, so they are **flagged and kept**, and any analysis excludes them in one line.

- **Cleaning — four conversions that were not housekeeping.** (i) Dates are parsed, formatted back, and compared; a single mismatch refuses the conversion, because a wrong date is a wrong cohort. (ii) 184 rows carried **zero-width characters** in their title — invisible, and `\s` does not match them, so one title silently becomes two. (iii) Same-day duplicate groups: 16,990 of 21,344 had *different view counts*, i.e. they are real distinct listings — so they are flagged, not dropped. (iv) `categories` is a JSON array of 43 industries; 37% of postings carry more than one, so keeping only the first would have discarded **723,000 category assignments** — it is exploded into a bridge table instead. The chain matters: case-folding titles is what makes the duplicate key work, and duplicates inflate how crowded a sector looks.

- **Feature engineering** — `src/pipeline/feature_enrichment.py` derives experience bands (Entry ≤1yr / Mid ≤4yr / Senior), salary bands (Entry <$3k / Mid $3–5k / Senior $5–8k / Executive >$8k), SSOC-style standardised job labels (the ~365k raw titles are too fragmented to group directly, so reporting is by 43 industries × 9 position levels), and the finance feature tables. Two features were **built and then deleted**: `skill_count` matched keywords against job *titles* — there is no description field, and a headline is not where skills live; and `competitiveness_score` barely correlated with applications, views or vacancies. A score that does not track its own subject is worse than no score.

- **EDA — the finding that shaped the product.** Median views per posting collapse from **51 in June 2023 to 2 in July 2023**, and stay there. Crucially, *older* postings have *fewer* views: a July 2023 posting has had ten extra months to accumulate and has fewer than a June one. No "the data is old" explanation produces that ordering. The cause is two collection regimes — after the crawl boundary, counters are frozen at day zero. Those postings are not low-response, they are **unmeasured**.

- **EDA — the two-layer split this forces.** Everything a posting *says* (pay, level, years, dates) is fixed the moment it goes up and is usable across all 1.04M rows — that is **Layer 1**. Everything a posting *got* (views, applications, reposts) accumulates afterwards and is only trustworthy inside a defensible cohort — that is **Layer 2**, built by three filters, each earning its place: counters complete (1,009,709 → 118,749), 30-day listings only for exposure comparability (→ 96,028), first cycle only for volume outcomes (→ **78,942**, Mar–Jun 2023). Roughly half of the Layer 2 notebook is spent earning the right to use 78,942 rows instead of a million.

---

## 3. Dashboard / App

- **Solution type** — A single Streamlit app (`src/dashboard/app.py`) over a DuckDB file, with **four boards** switched from one nav row: Market Overview, Hirer, Seeker, and Finance Business Partner. There is no page-per-role; one app switches which board renders.

- **Why DuckDB** — Columnar analytics over the cleaned tables is what lets a board aggregate a million postings **inside a click**, instead of re-reading a 400 MB CSV on every filter change. The pipeline writes `data/processed/jobs.duckdb`; the app only reads it.

- **Hirer board — five tabs, driven by one persistent vacancy config.** A sidebar panel ("The vacancy you're posting") holds sector, position level, experience level, planned salary, and minimum years. The tabs are **Salary benchmark · Experience norms · Applicant response · Reach vs conversion · Repost risk**. Each tab renders *only* the controls it actually reads (`TAB_CONTROLS` in `hirer_view.py`) — five always-visible controls of which two do nothing reads as a broken chart — and hidden controls persist their values across tab switches.

- **Market Overview board — four tabs in narrative order:** Market Pulse (headline metrics, industry momentum, salary trend, wage-growth decomposition), Market Composition (top categories, employment-type mix, seasonality), Market Structure (concentration among top companies), and Cross-View Insight — two checks: does pay actually track how hard a role is to fill, and where do repost risk and vacancy budget exposure concentrate together by industry.

- **Seeker board** — pay fairness and market position against a salary percentile, seniority ladder, pay-range width by industry and level, competition per opening, and best-opportunity ranking.

- **Finance board** — three tabs: recruitment mix and monthly trend by type; Decision 1, where contract-to-permanent conversion saves versus costs; Decision 2, where vacancy cost exposure concentrates by position level, plus a watchlist of slow-to-fill, high-exposure segments. Scenario assumptions are externalised to `config/finance_scenario.json`.

- **Interactivity** — Dropdown filters for sector / position level / experience, numeric inputs for planned salary and years, sortable tables, and Altair charts with hover tooltips. Filters are shared through session state so a selection survives moving between tabs.

- **Design rationale — discovery vs investigation.** Market Overview answers "what is happening in this market at all"; the Hirer, Seeker and Finance boards answer a *specific* decision for a *specific* user. Splitting them means the quick scan and the deep dive do not compete for the same screen.

- **Business alignment — headline finding, and why the board withholds a true number.** Market-wide, reposting falls from **18.7% to 16.2%** as the experience ask rises from under 3 years to 3+. That number is true, and it gives exactly the wrong advice: postings asking 3+ years are simply the better-paid ones ($5,400 vs $3,000 median). Holding pay fixed reverses it at the bottom:

  | Pay band | Repost rate, < 3 yrs → 3+ yrs | Change |
  |---|---|---|
  | Entry < $3k | 19.4% → **24.6%** | **+5.3 pts** |
  | Mid $3–5k | 18.4% → 18.1% | −0.3 |
  | Senior $5–8k | 17.9% → **15.5%** | −2.4 |
  | Exec > $8k | 15.0% → **12.1%** | −2.9 |

  Demanding 3+ years while paying under $3k is the one place the experience bar actually costs you. Because the gap between bands is far larger than chance, **the board never shows the market-wide view** — the Repost risk tab always conditions on pay band.

- **Business alignment — pay is the lever, not visibility.** Applications per posting run at a **median of 3 against a mean of 9.6**, so a board quoting averages would set hirer expectations three times too high; every figure on the Hirer board is a median. Under-fill rate falls monotonically with pay (43.3% at Entry <$3k, down to 12.6% at Exec >$8k), and the funnel shows two compounding effects rather than one: entry postings get **half the views** (53 vs 116) *and* convert them at **a third the rate** (3.2% vs 8.9%), with conversion the bigger half.

- **Provenance carried into the UI** — Every chart repeats its notebook's scope note: which cohort, how many postings, which window. Where a filter leaves too few rows, the board says so instead of drawing a chart from a handful of records.

- **Testing** — `pytest` covers the pipeline (cleaning, enrichment, schema) and the Market Overview and Seeker query layers; dashboard behaviour is verified with `streamlit.testing.v1.AppTest` rather than by eye.

---

## 4. Presentation

10 minutes, delivered from `docs/job-analytics-hirer-deck.pptx` (14 slides), scoped to the **hirer** business case.

*Why one board and not four.* Ten minutes across four boards gives each about two — enough to describe a screen, not enough to show a finding survive scrutiny. The hirer board is presented end-to-end instead, because it is the one that exercises the full data chain: the view-count collapse, the 78,942-row cohort built to survive it, and a headline number that reverses once you condition on pay. The cleaning and cohort work shown in segment 2 is shared by all four boards, so the walkthrough covers the team's common foundation even where it shows one board's charts.

Structure and timing against the brief's bands:

| # | Segment | Time | Slides |
|---|---|---|---|
| 1 | **Business case & objective** | ~2:00 | Title · the user (SME talent lead, no reference point) · the constraint (what a posting *says* vs what it *got*) |
| 2 | **Process & data handling** | ~3:00 | Cleaning at a glance (0.38% removed, 0 imputed) · Decision 1: reason codes not repairs · Decision 2: four non-trivial conversions · Decision 3: the view-count collapse · the 78,942-row cohort · architecture (CSV → clean → enrich → DuckDB → Streamlit) |
| 3 | **Dashboard walkthrough** | ~3:45 | Live demo of the Hirer board's five tabs, then the two analytical payoffs: pay dominates response, and the market-wide repost number giving the wrong advice |
| 4 | **Challenges & learnings** | ~1:00 | Closing slide |

**Challenges & learnings, in brief:**

1. *The hard part was deciding what the data couldn't answer.* Half of the Layer 2 work is spent earning the right to use 78,942 rows instead of a million. It felt like losing data; it was the difference between a number and a trustworthy one.
2. *We built two features and deleted them.* `skill_count` and `competitiveness_score` — see §2.
3. *Analysis and product carry the same caveats.* Every chart on the board repeats its notebook's scope note.

**Not established:** causation; seasonality (Layer 2 is a single four-month window); and whether a role actually *filled* — the data records reposting, not outcomes.

**Next:** employers posting at volume get markedly less engagement per posting (ρ = −0.53) — a company-level effect the current boards do not expose.

---

## 5. Deliverables Index

| Brief requirement | Where |
|---|---|
| Written report covering §1–4 | This document |
| Functional dashboard, with run instructions | `README.md` § Setup → `streamlit run src/dashboard/app.py` |
| Data handling notebooks | `notebooks/` — 6 notebooks, listed in §2 |
| Dashboard / app scripts | `src/dashboard/`, `src/pipeline/`, `src/database/`, `config/` |
| README with setup and dependencies | `README.md`, `environment.yml`, `requirements.txt`, `setup.sh` |
| Presentation deck | `docs/job-analytics-hirer-deck.pptx` |

**Run in three steps** (full detail in `README.md`):

```bash
./setup.sh                        # conda env + data/ dirs
cp /path/to/SGJobData.csv data/raw/
python -m src.pipeline.pipeline   # clean → enrich → load into data/processed/jobs.duckdb
streamlit run src/dashboard/app.py
```

Note: `ARCHITECTURE.md`, `GETTING_STARTED.md` and `PROJECT_STRUCTURE.md` are early scaffolding docs kept for reference. Where they disagree with the code or the database, trust the code.
