"""
Hirer's dashboard view.

Every section is backed by notebooks/hirer_layer1_analysis.ipynb or
hirer_layer2_analysis.ipynb. Data comes from src/dashboard/hirer_data_loader.py, which
deduplicates the market the way those notebooks do.
"""
import streamlit as st
from src.dashboard import charts, hirer_data_loader
from src.dashboard.utils import filter_selectbox


ALL_SECTORS = "All sectors"
ALL_LEVELS = "All levels"
ALL_EXPERIENCE = "All experience levels"

TABS_KEY = "hirer_tabs"

# Which controls each tab's figures actually read. A control absent here changes
# nothing on that tab, so it is hidden rather than left sitting there inert --
# five always-visible controls of which two do nothing reads as a broken chart.
# Keep in step with SECTIONS; the assertion below the renderers enforces it.
TAB_CONTROLS = {
    "Salary benchmark":     ('sector', 'level', 'experience', 'years', 'salary'),
    "Experience norms":     ('sector', 'level', 'years'),
    "Applicant response":   ('sector', 'salary'),
    "Reach vs conversion":  ('sector',),
    "Repost risk":          ('sector', 'salary', 'years'),
}


def _config_panel(active: str) -> dict:
    """The vacancy the hirer is about to post -- drives the open tab.

    Lives in the sidebar so it stays visible and keeps its values while the
    hirer moves between tabs. Controls are stacked rather than columned
    because the sidebar is too narrow for side-by-side labels.

    Only the controls the open tab reads are rendered. A keyed widget's value is
    dropped by default once it stops being rendered, which would reset the
    vacancy on every tab switch, so each one asks for persist_state='session'
    and keeps its value while hidden.
    """
    shown = TAB_CONTROLS.get(active, TAB_CONTROLS["Salary benchmark"])
    state = st.session_state

    with st.sidebar:
        st.subheader("The vacancy you're posting")
        st.caption(f"The settings **{active}** reads. The rest are hidden here "
                   "because they would not change this tab.")

        if 'sector' in shown:
            filter_selectbox("Sector", st.session_state.db.get_sector_list(),
                             ALL_SECTORS, key="hirer_sector",
                             persist_state="session")
        if 'level' in shown:
            filter_selectbox("Position level", hirer_data_loader.position_levels(),
                             ALL_LEVELS, key="hirer_level",
                             persist_state="session")
        if 'experience' in shown:
            filter_selectbox("Experience level",
                             hirer_data_loader.experience_levels(),
                             ALL_EXPERIENCE, key="hirer_experience",
                             persist_state="session")
        if 'salary' in shown:
            st.number_input(
                "Planned salary (S$/month)", min_value=0, max_value=50000,
                value=4000, step=250, key="hirer_salary",
                persist_state="session",
                help="The midpoint of the range you plan to advertise.",
            )
        if 'years' in shown:
            st.number_input(
                "Minimum years of experience", min_value=0, max_value=30,
                value=3, step=1, key="hirer_years", persist_state="session",
            )

    # Read back from state, not from the widget return values: a hidden control
    # returns nothing this run, but its persisted value still has to reach the
    # tabs that do read it.
    sector = _sentinel_to_none(state.get("hirer_sector"), ALL_SECTORS)
    level = _sentinel_to_none(state.get("hirer_level"), ALL_LEVELS)
    experience = _sentinel_to_none(state.get("hirer_experience"), ALL_EXPERIENCE)
    salary = state.get("hirer_salary", 4000) or None
    years = state.get("hirer_years", 3)

    return {
        'sector': sector, 'level': level, 'experience': experience,
        'salary': salary, 'years': years,
        'pay_band': hirer_data_loader.pay_band_for(salary),
        'yrs_bucket': hirer_data_loader.yrs_bucket_for(years),
    }


def _money(value: float) -> str:
    r"""Format a salary for markdown, escaping the dollar sign.

    Streamlit renders markdown as LaTeX between a pair of '$', so a string
    quoting two amounts loses everything between them to italic math. The
    escape has to survive the f-string, hence '\\$'.
    """
    return f"\\${value:,.0f}"


def _escape_money(text: str) -> str:
    """Same escape for label text that already carries a '$' (the pay bands)."""
    return text.replace("$", "\\$")


def _section_title(text: str) -> None:
    """Tab heading, one level below st.subheader.

    The tab label already names the section, so an h3 here spends vertical space
    restating it and pushes the taller charts below the fold. h5 keeps the
    heading -- several say more than their tab label does -- at about half the
    height.
    """
    st.markdown(f"##### {text}")


def _sentinel_to_none(value, all_label: str):
    """Session state holds the raw selectbox choice, including the "all" label."""
    return None if value is None or value == all_label else value


def _layer1_note() -> None:
    """Scope note for posting-time measures, valid across the whole market."""
    st.caption(
        f"All {hirer_data_loader.cohort_sizes()['market']:,} postings "
        "(duplicates removed), Mar 2023 – May 2024."
    )


def _layer2_note(n: int, sector: str | None = None,
                 cohort: str = "first-cycle 30-day postings") -> None:
    """Scope note for engagement measures, which only a narrow cohort supports.

    `n` is the row count behind the figure, and it always describes the sector
    asked for: these charts never stand in the whole market for a sector, so the
    note has only the one thing to say.
    """
    st.caption(
        f"{n:,} {cohort}, Mar–Jun 2023 — the only window with complete view and "
        f"application counts. {f'Filtered to **{sector}**.' if sector else 'All sectors.'}"
    )


def _too_thin(sector: str | None, what: str) -> None:
    """Empty state for a sector the cohort cannot support at all."""
    st.info(
        f"No pay band in **{sector}** has {hirer_data_loader.MIN_N} or more "
        f"postings in this cohort, so there is nothing to read {what} from. "
        "The figures for other sectors are not a substitute — pick another "
        "sector, or clear the filter to see the whole market."
    )


def _render_salary_benchmark(cfg: dict) -> None:
    """#1 -- layer 1 s.3, the core deliverable."""
    _section_title("What comparable employers pay")
    _layer1_note()
    bench = hirer_data_loader.salary_lookup(cfg['sector'], cfg['level'],
                                            cfg['experience'], cfg['yrs_bucket'])

    with charts.MPL_LOCK:
        st.write(charts.salary_range_bar(bench, cfg['salary']))

    st.caption(
        f"Benchmark grain: **{bench['grain']}** · {int(bench['n']):,} comparable "
        "postings with a disclosed salary. Advertised salary midpoint; percentiles "
        "rather than averages, because a handful of extreme postings survive the "
        "salary quality filter."
    )

    if cfg['salary']:
        if cfg['salary'] < bench['mid_p25']:
            st.warning(
                f"Your {_money(cfg['salary'])} sits below the 25th percentile "
                f"({_money(bench['mid_p25'])}) for comparable postings."
            )
        elif cfg['salary'] > bench['mid_p75']:
            st.info(
                f"Your {_money(cfg['salary'])} sits above the 75th percentile "
                f"({_money(bench['mid_p75'])}) for comparable postings."
            )


def _render_norms(cfg: dict) -> None:
    """#3 -- layer 1 s.4."""
    _section_title("Experience asked, by position level")
    _layer1_note()
    norms = hirer_data_loader.config_norms(cfg['sector'])
    if norms.empty:
        st.info("Not enough postings in this sector to read configuration norms.")
        return

    # No position level chosen means no single cell to point at, so the heatmap
    # is shown unannotated and the rarity check is skipped.
    marked = cfg['level'] is not None
    highlight = (cfg['level'], cfg['yrs_bucket']) if marked else None

    with charts.MPL_LOCK:
        st.write(charts.norms_heatmap(norms, highlight=highlight))
    st.caption(
        "Each row shows how postings at that level distribute their minimum "
        "years-of-experience ask (rows sum to 100%)."
        + (" Your combination is outlined." if marked else
           " Choose a position level above to mark your combination.")
    )

    if marked and cfg['level'] in norms.index and cfg['yrs_bucket'] in norms.columns:
        share = norms.loc[cfg['level'], cfg['yrs_bucket']]
        if share < 1.0:
            # info, not warning: a rare pairing is a factual oddity, not a cost.
            # As a warning it competed with the repost danger zone, which is the
            # one alert in this view that quantifies what it costs the hirer.
            st.info(
                f"Fewer than 1% of **{cfg['level']}** postings ask for "
                f"**{cfg['yrs_bucket']}** years ({share:.2f}%). This pairing is one "
                "the market essentially never uses."
            )


def _render_response(cfg: dict) -> None:
    """#6 -- layer 2 s.3."""
    _section_title("Applicant response by pay band")
    bands = hirer_data_loader.response_by_pay_band(cfg['sector'])
    if bands.empty:
        _too_thin(cfg['sector'], "applicant response")
        return
    _layer2_note(int(bands.n.sum()), cfg['sector'])

    with charts.MPL_LOCK:
        st.write(charts.response_chart(bands))
    st.caption(
        "Pay dominates response. Getting applications ≥ vacancies is a necessary "
        "condition for filling the role, not proof that it filled."
    )

    if cfg['pay_band'] in bands.index:
        row = bands.loc[cfg['pay_band']]
        c1, c2, c3 = st.columns(3)
        c1.metric("Median applications", f"{row.apps_p50:.0f}",
                  help=f"P10–P90: {row.apps_p10:.0f}–{row.apps_p90:.0f}")
        c2.metric("Under-filled risk", f"{row.under_filled:.0%}")
        c3.metric("Comparable postings", f"{int(row.n):,}")
        st.caption(f"For your pay band: **{_escape_money(cfg['pay_band'])}**")


def _render_funnel(cfg: dict) -> None:
    """#7 -- layer 2 s.4."""
    _section_title("Reach or conversion — which is the problem?")
    funnel = hirer_data_loader.funnel_by_pay_band(cfg['sector'])
    if funnel.empty:
        _too_thin(cfg['sector'], "reach and conversion")
        return
    _layer2_note(int(funnel.n.sum()), cfg['sector'])

    with charts.MPL_LOCK:
        st.write(charts.funnel_scatter(funnel))
    st.caption(
        "The two effects compound rather than trade off: low-paying postings draw "
        "fewer viewers *and* convert fewer of them. If conversion is the weak point, "
        "pay is the lever; if reach is, the sector is simply crowded."
    )


def _render_repost_risk(cfg: dict) -> None:
    """#8 -- layer 2 s.5-6, the headline finding."""
    _section_title("Repost risk: experience asked against pay offered")
    rates = hirer_data_loader.repost_matrix(cfg['sector'])
    if rates.notna().to_numpy().sum() == 0:
        _too_thin(cfg['sector'], "repost risk")
        return
    # Not the first-cycle pool the other two layer-2 tabs use: reposts are the
    # measure here, so excluding them would remove the thing being counted.
    _layer2_note(hirer_data_loader.layer2_size(cfg['sector']), cfg['sector'],
                 cohort="30-day postings with complete counters")

    with charts.MPL_LOCK:
        st.write(charts.repost_heatmap(rates, highlight=(cfg['pay_band'], cfg['yrs_bucket'])))
    st.caption(
        f"Share of postings that were relisted (cells under "
        f"{hirer_data_loader.MIN_N} postings are blank). Shown split by pay band "
        "because the aggregate view reverses "
        "the sign — the protective-looking effect of demanding experience is pay "
        "in disguise. Your combination is outlined."
    )

    # Two groups rather than the grid's seven year-buckets, so a band can be
    # readable here even where the heatmap cell above it is blank. A band this
    # sector cannot support is simply absent, and the warning stays silent.
    contrast = hirer_data_loader.repost_contrast(cfg['sector'])
    if cfg['pay_band'] in contrast.index and cfg['years'] >= 3:
        row = contrast.loc[cfg['pay_band']]
        if row.repost_gte3 > row.repost_lt3:
            where = f"in **{cfg['sector']}**" if cfg['sector'] else "across all sectors"
            # The only alert here that puts a number on what the configuration
            # costs, so it gets the one red in the view. Everything else is
            # warning (a risk) or info (worth knowing).
            st.error(
                f"**Danger zone.** In the {_escape_money(cfg['pay_band'])} band "
                f"{where}, postings "
                f"asking 3+ years were reposted {row.repost_gte3:.1f}% of the time "
                f"against {row.repost_lt3:.1f}% for those asking less "
                f"({int(row.n):,} postings). Consider raising the pay band or "
                "lowering the experience bar. This is a risk factor across "
                "comparable postings, not a prediction about yours."
            )


# Tab label -> renderer. The first two read the whole market (layer 1); the
# last three read the narrow engagement cohort (layer 2).
SECTIONS = (
    ("Salary benchmark", _render_salary_benchmark),
    ("Experience norms", _render_norms),
    ("Applicant response", _render_response),
    ("Reach vs conversion", _render_funnel),
    ("Repost risk", _render_repost_risk),
)

# A label that drifts out of TAB_CONTROLS would silently fall back to showing
# the salary tab's controls, so fail at import instead.
assert {label for label, _ in SECTIONS} == set(TAB_CONTROLS), (
    "SECTIONS and TAB_CONTROLS disagree: "
    f"{ {label for label, _ in SECTIONS} ^ set(TAB_CONTROLS) }"
)


def render_hirer_view():
    """Render hirer-focused dashboard.

    No board-level header: the view switch above already names it, and the
    heading cost enough vertical space to push the taller charts off-screen.
    """
    # The sidebar is built before the tabs exist, so the open tab comes from the
    # tab widget's own state. on_change="rerun" means a tab switch reruns the
    # script, so this is the tab about to render, not the one just left.
    active = st.session_state.get(TABS_KEY, SECTIONS[0][0])
    cfg = _config_panel(active)

    # on_change="rerun" makes tab bodies lazy: only the selected tab renders,
    # so switching sectors does not rebuild all five figures.
    tabs = st.tabs([label for label, _ in SECTIONS],
                   on_change="rerun", key=TABS_KEY)
    for tab, (_, render) in zip(tabs, SECTIONS):
        with tab:
            # `open` is None when state tracking is unavailable; render then.
            if tab.open is not False:
                render(cfg)
