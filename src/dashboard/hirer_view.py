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


def _config_panel() -> dict:
    """The vacancy the hirer is about to post -- drives every tab.

    Lives in the sidebar so it stays visible and keeps its values while the
    hirer moves between tabs. Controls are stacked rather than columned
    because the sidebar is too narrow for side-by-side labels.
    """
    with st.sidebar:
        st.subheader("The vacancy you're posting")
        st.caption("These settings drive every tab.")

        sector = filter_selectbox("Sector", st.session_state.db.get_sector_list(),
                                  ALL_SECTORS, key="hirer_sector")
        level = filter_selectbox("Position level", hirer_data_loader.position_levels(),
                                 ALL_LEVELS, key="hirer_level")
        experience = filter_selectbox("Experience level",
                                      hirer_data_loader.experience_levels(),
                                      ALL_EXPERIENCE, key="hirer_experience")
        salary = st.number_input(
            "Planned salary (S$/month)", min_value=0, max_value=50000,
            value=4000, step=250, key="hirer_salary",
            help="The midpoint of the range you plan to advertise.",
        )
        years = st.number_input(
            "Minimum years of experience", min_value=0, max_value=30,
            value=3, step=1, key="hirer_years",
        )

    return {
        'sector': sector, 'level': level, 'experience': experience,
        'salary': salary or None, 'years': years,
        'pay_band': hirer_data_loader.pay_band_for(salary or None),
        'yrs_bucket': hirer_data_loader.yrs_bucket_for(years),
    }


def _layer1_note() -> None:
    """Scope note for posting-time measures, valid across the whole market."""
    st.caption(
        f"All {hirer_data_loader.cohort_sizes()['market']:,} postings "
        "(duplicates removed), Mar 2023 – May 2024."
    )


def _layer2_note() -> None:
    """Scope note for engagement measures, which only a narrow cohort supports."""
    st.caption(
        f"{hirer_data_loader.cohort_sizes()['first_cycle']:,} first-cycle 30-day postings, "
        "Mar–Jun 2023 — the only window with complete view and application counts. "
        "All sectors; the sector filter does not apply here."
    )


def _render_salary_benchmark(cfg: dict) -> None:
    """#1 -- layer 1 s.3, the core deliverable."""
    st.subheader("What comparable employers pay")
    _layer1_note()
    bench = hirer_data_loader.salary_lookup(cfg['sector'], cfg['level'], cfg['experience'])

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
                f"Your ${cfg['salary']:,.0f} sits below the 25th percentile "
                f"(${bench['mid_p25']:,.0f}) for comparable postings."
            )
        elif cfg['salary'] > bench['mid_p75']:
            st.info(
                f"Your ${cfg['salary']:,.0f} sits above the 75th percentile "
                f"(${bench['mid_p75']:,.0f}) for comparable postings."
            )


def _render_norms(cfg: dict) -> None:
    """#3 -- layer 1 s.4."""
    st.subheader("Experience asked, by position level")
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
            st.warning(
                f"Fewer than 1% of **{cfg['level']}** postings ask for "
                f"**{cfg['yrs_bucket']}** years ({share:.2f}%). This pairing is one "
                "the market essentially never uses."
            )


def _render_response(cfg: dict) -> None:
    """#6 -- layer 2 s.3."""
    st.subheader("Applicant response by pay band")
    _layer2_note()
    bands = hirer_data_loader.response_by_pay_band()
    if bands.empty:
        return

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
        st.caption(f"For your pay band: **{cfg['pay_band']}**")


def _render_funnel(cfg: dict) -> None:
    """#7 -- layer 2 s.4."""
    st.subheader("Reach or conversion — which is the problem?")
    _layer2_note()
    funnel = hirer_data_loader.funnel_by_pay_band()
    if funnel.empty:
        return

    with charts.MPL_LOCK:
        st.write(charts.funnel_scatter(funnel))
    st.caption(
        "The two effects compound rather than trade off: low-paying postings draw "
        "fewer viewers *and* convert fewer of them. If conversion is the weak point, "
        "pay is the lever; if reach is, the sector is simply crowded."
    )


def _render_repost_risk(cfg: dict) -> None:
    """#8 -- layer 2 s.5-6, the headline finding."""
    st.subheader("Repost risk: experience asked against pay offered")
    _layer2_note()
    rates = hirer_data_loader.repost_matrix()
    if rates.empty:
        return

    with charts.MPL_LOCK:
        st.write(charts.repost_heatmap(rates, highlight=(cfg['pay_band'], cfg['yrs_bucket'])))
    st.caption(
        f"Share of postings that were relisted (cells under "
        f"{hirer_data_loader.MIN_N} postings are blank). Shown split by pay band "
        "because the aggregate view reverses "
        "the sign — the protective-looking effect of demanding experience is pay "
        "in disguise. Your combination is outlined."
    )

    contrast = hirer_data_loader.repost_contrast()
    if cfg['pay_band'] in contrast.index and cfg['years'] >= 3:
        row = contrast.loc[cfg['pay_band']]
        if row.repost_gte3 > row.repost_lt3:
            st.warning(
                f"**Danger zone.** In the {cfg['pay_band']} band, postings asking "
                f"3+ years were reposted {row.repost_gte3:.1f}% of the time against "
                f"{row.repost_lt3:.1f}% for those asking less. Consider raising the "
                "pay band or lowering the experience bar. This is a risk factor "
                "across comparable postings, not a prediction about yours."
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


def render_hirer_view():
    """Render hirer-focused dashboard.

    No board-level header: the view switch above already names it, and the
    heading cost enough vertical space to push the taller charts off-screen.
    """
    cfg = _config_panel()

    # on_change="rerun" makes tab bodies lazy: only the selected tab renders,
    # so switching sectors does not rebuild all five figures.
    tabs = st.tabs([label for label, _ in SECTIONS],
                   on_change="rerun", key="hirer_tabs")
    for tab, (_, render) in zip(tabs, SECTIONS):
        with tab:
            # `open` is None when state tracking is unavailable; render then.
            if tab.open is not False:
                render(cfg)
