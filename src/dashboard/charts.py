"""
Chart builders: DataFrame in, matplotlib Figure out.

No streamlit imports and no pyplot -- figures are built on the object API
(`matplotlib.figure.Figure`), so nothing accumulates in pyplot's global
registry and the builders stay usable outside the app (tests, notebooks).
"""
from threading import RLock

import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

# Matplotlib is not thread-safe; hold this around figure creation AND rendering
# (st.write draws the figure) when multiple users may hit the app concurrently.
MPL_LOCK = RLock()

BLUE = '#2a78d6'
RED = '#e34948'
INK = '#0b0b0b'
INK_MUTED = '#52514e'
GRID = '#e8e8e6'
TRACK = '#ececeb'


def _new_axes(figsize: tuple) -> tuple:
    fig = Figure(figsize=figsize, dpi=110, layout='tight')
    return fig, fig.add_subplot()


def _style(ax, grid_axis: str = 'y') -> None:
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    for side in ('left', 'bottom'):
        ax.spines[side].set_color(GRID)
    ax.grid(axis=grid_axis, color=GRID, lw=.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK_MUTED)


def _highlight(ax, col: int, row: int) -> None:
    ax.add_patch(Rectangle((col, row), 1, 1, fill=False,
                           edgecolor=INK, lw=2.5, zorder=5))


def salary_range_bar(bench: dict, planned: float | None = None) -> Figure:
    """P25–P75 range for one configuration, with the hirer's planned salary marked."""
    p25, p50, p75 = bench['mid_p25'], bench['mid_p50'], bench['mid_p75']
    fig, ax = _new_axes((10, 2.1))

    lo = min(p25, planned if planned else p25)
    hi = max(p75, planned if planned else p75)
    pad = max((hi - lo) * .35, 400)
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_ylim(-1, 1.5)

    ax.barh(0, p75 - p25, left=p25, height=.5, color=TRACK, zorder=1)
    ax.barh(0, p75 - p25, left=p25, height=.5, color=BLUE, alpha=.30, zorder=2)
    ax.vlines(p50, -.25, .25, color=BLUE, lw=3.5, zorder=3)

    for value, label, dy in ((p25, 'P25', -.55), (p50, 'median', .42), (p75, 'P75', -.55)):
        ax.annotate(f'{label}\n${value:,.0f}', (value, dy), ha='center',
                    va='bottom' if dy > 0 else 'top', fontsize=9, color=INK_MUTED)

    if planned:
        ax.plot([planned], [0], marker='D', ms=11, color=RED,
                markeredgecolor='white', markeredgewidth=1.6, zorder=6)
        # Sits above the median label, which is itself two lines tall, so the
        # two never collide when the planned salary lands near the median.
        ax.annotate(f'yours ${planned:,.0f}', (planned, 1.08), ha='center',
                    va='bottom', fontsize=9.5, color=RED, fontweight='bold')
        ax.vlines(planned, .28, 1.05, color=RED, lw=1, ls=':', zorder=4)

    ax.get_yaxis().set_visible(False)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(GRID)
    ax.tick_params(colors=INK_MUTED, labelcolor=INK_MUTED)
    ax.xaxis.set_major_formatter(lambda v, _: f'${v:,.0f}')
    return fig


def norms_heatmap(norms: pd.DataFrame, highlight: tuple | None = None) -> Figure:
    fig, ax = _new_axes((10, .6 * len(norms) + 1.6))
    sns.heatmap(
        norms, annot=True, fmt='.1f', cmap='Blues', vmin=0, ax=ax,
        linewidths=.5, linecolor='white', annot_kws={'size': 8},
        cbar_kws={'label': '% of postings at this level'},
    )
    if highlight:
        level, yrs = highlight
        if level in norms.index and yrs in norms.columns:
            _highlight(ax, norms.columns.get_loc(yrs), norms.index.get_loc(level))
    ax.set_xlabel('minimum years of experience required', color=INK_MUTED)
    ax.set_ylabel('')
    ax.tick_params(colors=INK_MUTED, labelcolor=INK_MUTED, rotation=0)
    return fig


def response_chart(bands: pd.DataFrame) -> Figure:
    """Median applications (P10-P90 band) and under-filled risk, per pay band."""
    fig = Figure(figsize=(12, 4.5), dpi=110, layout='tight')
    ax1, ax2 = fig.subplots(1, 2)
    x = np.arange(len(bands))

    ax1.bar(x, bands.apps_p50, color=BLUE, width=.62)
    ax1.errorbar(
        x, bands.apps_p50,
        yerr=[bands.apps_p50 - bands.apps_p10, bands.apps_p90 - bands.apps_p50],
        fmt='none', ecolor=INK_MUTED, capsize=4, lw=1.2,
    )
    ax1.set_title('Median applications (whiskers: P10–P90)', fontsize=10)
    ax1.set_ylabel('applications', color=INK_MUTED)

    ax2.bar(x, bands.under_filled * 100, color=RED, width=.62)
    for xi, v in zip(x, bands.under_filled * 100):
        ax2.annotate(f'{v:.0f}%', (xi, v), ha='center', va='bottom',
                     fontsize=9, color=INK_MUTED)
    ax2.set_title('Under-filled risk: P(applications < vacancies)', fontsize=10)
    ax2.set_ylabel('% of postings', color=INK_MUTED)

    for ax in (ax1, ax2):
        ax.set_xticks(x)
        ax.set_xticklabels(bands.index, rotation=20, ha='right')
        _style(ax)
    return fig


def funnel_scatter(funnel: pd.DataFrame) -> Figure:
    """Reach (median views) against conversion (applications per view)."""
    fig, ax = _new_axes((8.5, 5))
    ax.scatter(funnel.views_p50, funnel.conversion_pct, s=170,
               color=BLUE, edgecolor='white', lw=1.6, zorder=3)
    for label, row in funnel.iterrows():
        ax.annotate(str(label), (row.views_p50, row.conversion_pct),
                    textcoords='offset points', xytext=(10, 7),
                    fontsize=9.5, color=INK_MUTED)
    ax.set_xlabel('median views (reach)', color=INK_MUTED)
    ax.set_ylabel('applications per view (conversion, %)', color=INK_MUTED)
    ax.margins(.18)
    _style(ax, grid_axis='both')
    return fig


def repost_heatmap(rates: pd.DataFrame, highlight: tuple | None = None) -> Figure:
    fig, ax = _new_axes((10, .6 * len(rates) + 1.6))
    # Scale to the observed range rather than anchoring at zero: no cell falls
    # below ~6%, so a zero floor spends a quarter of the ramp on empty space
    # and flattens the contrast between bands.
    sns.heatmap(
        rates, annot=True, fmt='.1f', cmap='Reds', ax=ax,
        linewidths=.5, linecolor='white', annot_kws={'size': 9},
        cbar_kws={'label': 'repost rate (%)'},
    )
    if highlight:
        band, yrs = highlight
        if band in rates.index and yrs in rates.columns:
            _highlight(ax, rates.columns.get_loc(yrs), rates.index.get_loc(band))
    ax.set_xlabel('minimum years of experience required', color=INK_MUTED)
    ax.set_ylabel('')
    ax.tick_params(colors=INK_MUTED, labelcolor=INK_MUTED, rotation=0)
    return fig
