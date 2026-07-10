"""Streamlit UI for the Domain Feed Health Dashboard.

Two views:

- Current: live data from :class:`~domain_feed_health_dashboard.services.generator.Generator`
  (today's in-memory tally, polled from S3).
- Historical: a feed/device x day pivot grid from
  :class:`~domain_feed_health_dashboard.db.repository.Repository` (read from the
  local SQLite database the Generator pushes to at UTC midnight), defaulting to
  a 30-day window and configurable from 1 to 31 days.

There is no simulated-data mode in this UI.
"""

from __future__ import annotations

import json
import os
import time

import altair as alt
import pandas as pd
import streamlit as st

from domain_feed_health_dashboard.aws.s3_client import get_s3_client
from domain_feed_health_dashboard.aws.scanner import S3Scanner
from domain_feed_health_dashboard.data_model import DomainRecord, Status
from domain_feed_health_dashboard.db.repository import Repository
from domain_feed_health_dashboard.grid_config import (
    aggrid_available,
    build_domain_master_detail_grid_options,
    build_history_master_detail_grid_options,
    render_aggrid,
    selected_row_value,
)
from domain_feed_health_dashboard.history_data import (
    DEFAULT_HISTORY_WINDOW_DAYS,
    MAX_HISTORY_WINDOW_DAYS,
    MIN_HISTORY_WINDOW_DAYS,
    TREND_COLOR_PALETTE,
    build_feed_history_pivot,
    build_history_domain_master,
    domain_ids_with_history,
    feed_count_timeseries,
    style_feed_history_pivot,
)
from domain_feed_health_dashboard.services.generator import CYCLE_SECONDS, Generator
from domain_feed_health_dashboard.status import (
    BAND_ICONS,
    BAND_OPTIONS,
    STATUS_ICONS,
    STATUS_LABELS,
    band_overall_metrics,
    build_domain_band_summary,
    build_domain_summary,
    filter_domain_band_summary,
)
from domain_feed_health_dashboard.table_data import (
    domain_master_detail_dataframe,
    feed_detail_rows,
)

STATUS_BADGE_CLASS: dict[Status, str] = {
    "red": "status-red",
    "yellow": "status-yellow",
    "green": "status-green",
}

# The SQLite history database path is overridable via the DASHBOARD_DB_PATH
# environment variable.
DEFAULT_DB_PATH = os.environ.get("DASHBOARD_DB_PATH", "domain_feed_health_dashboard.sqlite3")

_LAST_CYCLE_SESSION_KEY = "_domain_feed_health_dashboard_last_cycle_monotonic"


@st.cache_resource(show_spinner=False)
def _get_generator(db_path: str) -> Generator:
    scanner = S3Scanner(get_s3_client())
    generator = Generator(scanner=scanner, db_path=db_path)
    generator.rebuild_tally()
    # Backfills missing completed days into SQLite so the 30-day history
    # view has data immediately instead of only accumulating going forward
    # from each UTC midnight rollover. Already-backfilled days are skipped,
    # so this is fast on every restart after the first.
    generator.backfill_history()
    return generator


@st.cache_resource(show_spinner=False)
def _get_repository(db_path: str) -> Repository:
    return Repository(db_path)


def _maybe_run_cycle(generator: Generator) -> str | None:
    """Poll S3 for new files at most once per CYCLE_SECONDS.

    Streamlit reruns this module on every user interaction; without this
    guard every sidebar tweak would trigger a fresh S3 poll.
    """

    now = time.monotonic()
    last = st.session_state.get(_LAST_CYCLE_SESSION_KEY, 0.0)
    if now - last < CYCLE_SECONDS:
        return None
    try:
        generator.run_cycle()
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        return str(exc)
    st.session_state[_LAST_CYCLE_SESSION_KEY] = now
    return None


def _load_live_domains(db_path: str) -> tuple[tuple[DomainRecord, ...], str | None]:
    try:
        with st.spinner("Connecting to S3 and loading today's tally + 30-day history (first run only)..."):
            generator = _get_generator(db_path)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        return (), str(exc)
    error = _maybe_run_cycle(generator)
    return generator.tally.to_domain_records(), error


def _status_badge(status: Status) -> str:
    label = STATUS_LABELS[status]
    css_class = STATUS_BADGE_CLASS[status]
    return f'<span class="status-badge {css_class}">{label}</span>'


def _install_css() -> None:
    st.markdown(
        """
        <style>
          .info-banner {
            border: 1px solid #6b7280;
            border-left: 6px solid #2563eb;
            border-radius: 0.45rem;
            padding: 0.75rem 1rem;
            background: rgba(37, 99, 235, 0.08);
            margin-bottom: 1rem;
          }
          .status-badge {
            display: inline-block;
            padding: 0.16rem 0.5rem;
            border-radius: 999px;
            font-weight: 700;
            letter-spacing: 0.01em;
            font-size: 0.82rem;
            border: 1px solid transparent;
          }
          .status-red { color: #7f1d1d; background: #fee2e2; border-color: #fecaca; }
          .status-yellow { color: #713f12; background: #fef3c7; border-color: #fde68a; }
          .status-green { color: #14532d; background: #dcfce7; border-color: #bbf7d0; }
          .muted { color: #6b7280; }
          .metric-card {
            border: 1px solid #e5e7eb;
            border-radius: 0.45rem;
            padding: 0.35rem 0.45rem;
            background: #ffffff;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
          }
          .metric-card-label {
            color: #4b5563;
            font-size: 0.6rem;
            font-weight: 650;
            letter-spacing: 0.01em;
            text-transform: uppercase;
            margin-bottom: 0.15rem;
            line-height: 1.15;
          }
          .metric-card-value {
            color: #111827;
            font-size: 1.25rem;
            line-height: 1.1;
            font-weight: 780;
          }
          .metric-card-note {
            color: #6b7280;
            font-size: 0.56rem;
            line-height: 1.15;
            margin-top: 0.15rem;
          }
          .table-title {
            margin-top: 1.5rem;
            margin-bottom: 0.35rem;
            font-size: 1.35rem;
            font-weight: 700;
            color: #111827;
          }
          /* Domain status filter: stack the selected boxes one per line, each
             full width (uniform), showing the whole label (no truncation), and
             let the control grow vertically so every box fits without scrolling. */
          .stMultiSelect div[data-baseweb="select"] > div:first-child {
            flex-wrap: wrap;
            max-height: none !important;
            overflow: visible !important;
          }
          .stMultiSelect span[data-baseweb="tag"] {
            width: 100%;
            max-width: 100% !important;
            box-sizing: border-box;
          }
          .stMultiSelect span[data-baseweb="tag"] span {
            max-width: 100% !important;
            overflow: visible !important;
            text-overflow: clip !important;
            white-space: normal !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _metric_card(label: str, value: int, note: str) -> str:
    return (
        '<div class="metric-card">'
        f'<div class="metric-card-label">{label}</div>'
        f'<div class="metric-card-value">{value:,}</div>'
        f'<div class="metric-card-note">{note}</div>'
        '</div>'
    )


def _render_overall_metrics(summary: pd.DataFrame) -> None:
    """Render the metric cards from a band summary DataFrame (shared by both tabs)."""
    metrics = band_overall_metrics(summary)
    cards = [
        ("Visible domains", metrics["total_domains"], "after current filters"),
        ("Visible feeds", metrics["total_feeds"], "sum of visible domain feeds"),
        ("Green domains", metrics["green_domains"], "worst feed 95-100%"),
        ("Yellow domains", metrics["yellow_domains"], "worst feed 80-94%"),
        ("Orange domains", metrics["orange_domains"], "worst feed 70-79%"),
        ("Red domains", metrics["red_domains"], "worst feed <70% or >100%"),
        ("Green feeds", metrics["green_feeds"], "95-100% of expected"),
        ("Yellow feeds", metrics["yellow_feeds"], "80-94% of expected"),
        ("Orange feeds", metrics["orange_feeds"], "70-79% of expected"),
        ("Red feeds", metrics["red_feeds"], "<70% or over-delivery"),
    ]
    columns = st.columns(len(cards), gap="small")
    for column, (label, value, note) in zip(columns, cards, strict=False):
        column.markdown(_metric_card(label, value, note), unsafe_allow_html=True)
    # Spacer between the cards row and the table below.
    st.markdown("<div style='height: 1.25rem'></div>", unsafe_allow_html=True)


def _full_grid_height(num_rows: int) -> int:
    """Grid height that shows every row at once (no pagination), capped to avoid
    a pathologically tall component for very large result sets."""
    return min(6000, 120 + 34 * max(1, num_rows))


def _render_master_detail_domain_table(domains: tuple[DomainRecord, ...], max_feed_rows: int | None = None) -> None:
    grid_df = domain_master_detail_dataframe(domains, max_feed_rows=max_feed_rows)
    if grid_df.empty:
        st.info("No domains match the current filters.")
        return

    if not aggrid_available():
        st.warning(
            "streamlit-aggrid is not installed in this runtime, so a simple fallback is shown. "
            "Install streamlit-aggrid to enable inline master/detail row expansion."
        )
        fallback_df = grid_df.drop(columns=["domain_id", "domain_band", "feed_rows_json"], errors="ignore")
        st.dataframe(fallback_df, width="stretch", hide_index=True, height=min(640, 96 + 32 * len(fallback_df)))
        _render_fallback_expanders(domains, max_feed_rows=max_feed_rows)
        return

    render_aggrid(
        grid_df,
        build_domain_master_detail_grid_options(grid_df),
        key="domain_master_detail_aggrid",
        height=_full_grid_height(len(grid_df)),
        enable_enterprise_modules=True,
        fit_columns=True,
    )


def _render_fallback_expanders(domains: tuple[DomainRecord, ...], max_feed_rows: int) -> None:
    st.markdown("### Fallback expanded feed preview")
    summary = build_domain_summary(domains)
    summary_by_id = {str(row["domain_id"]): row for _, row in summary.iterrows()}
    for domain in domains:
        domain_id = domain.domain_id or domain.domain_name
        row = summary_by_id[domain_id]
        status = str(row["domain_status"])
        label = (
            f"{STATUS_ICONS[status]} · {domain.domain_name} · "
            f"{row['total_feeds']} feeds · R/Y/G: "
            f"{row['red_feeds']}/{row['yellow_feeds']}/{row['green_feeds']}"
        )
        with st.expander(label, expanded=False):
            st.markdown(_status_badge(status), unsafe_allow_html=True)
            if not domain.feeds:
                st.warning("No feeds. Domain health is YELLOW / Unknown.")
            else:
                feed_preview = pd.DataFrame(feed_detail_rows(domain, max_feed_rows=max_feed_rows)).drop(columns=["router_rows_json"], errors="ignore")
                st.dataframe(feed_preview, width="stretch", hide_index=True)


def _render_history_fallback(repository: Repository, window_days: int) -> None:
    """Non-AgGrid fallback: a domain selector + that domain's styled feed×day pivot."""

    st.warning(
        "streamlit-aggrid is not installed in this runtime, so a simple fallback is shown. "
        "Install streamlit-aggrid to enable the nested domain → feed → device drilldown."
    )
    domain_ids = domain_ids_with_history(repository)
    selected_domain_id = st.selectbox("Domain", options=domain_ids, key="history_domain_select")
    pivot = build_feed_history_pivot(repository, selected_domain_id, max_days=window_days)
    if pivot.empty or len(pivot.columns) <= 1:
        st.info(f"No feed history found for {selected_domain_id} in the last {window_days} days.")
        return
    st.dataframe(style_feed_history_pivot(pivot), width="stretch", hide_index=True)


def _render_history_section(
    db_path: str,
    window_days: int,
    search_text: str,
    selected_statuses: list[str],
    live_domains: tuple[DomainRecord, ...] = (),
) -> None:
    try:
        repository = _get_repository(db_path)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        st.warning(f"History database unavailable: {exc}")
        return

    if not aggrid_available():
        _render_history_fallback(repository, window_days)
        return

    # Most recent (live) aimpoint per feed, used for the device detail so the
    # History tab shows the current aimpoint config even when stored history
    # rows predate aimpoint capture.
    live_routers = {
        (domain.domain_id or domain.domain_name, feed.feed_id): feed.routers
        for domain in live_domains
        for feed in domain.feeds
    }

    master_df, date_headers = build_history_domain_master(
        repository, max_days=window_days, live_routers=live_routers
    )
    if master_df.empty:
        st.info("No completed history sets are available yet in this database. Click “Backfill / refresh history now” above.")
        return

    # Same sidebar filters as the Current tab apply here.
    visible_ids = filter_domain_band_summary(master_df, search_text, selected_statuses)
    visible_master = master_df[master_df["domain_id"].isin(visible_ids)].reset_index(drop=True)

    _render_overall_metrics(visible_master)

    if visible_master.empty:
        st.info("No domains match the current filters.")
        return

    response = render_aggrid(
        visible_master,
        build_history_master_detail_grid_options(visible_master, date_headers),
        key="history_domain_master_detail_aggrid",
        height=_full_grid_height(len(visible_master)),
        enable_enterprise_modules=True,
        # Column widths are governed by per-column flex (Trend 1.5×), so don't
        # also run sizeColumnsToFit — the two would fight.
        fit_columns=False,
    )

    _render_history_feed_linechart(response, visible_master, date_headers)


def _history_trend_chart(timeseries: pd.DataFrame, height: int = 320) -> "alt.Chart":
    """Altair line graph of a domain's feeds' daily delivered counts.

    One line per feed; x-axis reversed so the most recent day is on the left
    (matching the inline sparkline, which is drawn newest-first left→right).
    """
    return (
        alt.Chart(timeseries)
        .mark_line(point=True)
        .encode(
            x=alt.X("day:T", title="Day", scale=alt.Scale(reverse=True)),
            y=alt.Y("count:Q", title="Files delivered"),
            # Same palette (and alphabetical feed order) as the inline PNG
            # sparkline, so the enlarged chart matches it line-for-line.
            color=alt.Color("feed:N", title="Feed", scale=alt.Scale(range=TREND_COLOR_PALETTE)),
        )
        .properties(height=height)
    )


@st.dialog("Daily delivered counts", width="large")
def _history_trend_dialog(domain_name: str, timeseries: pd.DataFrame) -> None:
    """Enlarged, interactive version of the inline Trend sparkline (per feed)."""
    st.markdown(f"**{domain_name}** — daily files delivered, one line per feed")
    st.altair_chart(_history_trend_chart(timeseries, height=430), use_container_width=True)


_OPENED_TREND_DOMAIN_KEY = "_history_open_trend_domain"


def _render_history_feed_linechart(response, visible_master: pd.DataFrame, date_headers: list[tuple[str, str]]) -> None:
    """Open the enlarged per-feed line graph for the selected domain.

    Each domain row shows an inline PNG sparkline in its "Trend" column. Only
    that cell selects the domain (grid_config sets suppressRowClickSelection and
    a Trend-cell-only onCellClicked), so clicking the sparkline — and nothing
    else on the row — opens the full interactive per-feed line graph in a modal
    dialog, the same graph the "Enlarge trend" button opens. The dialog
    auto-opens only when the selection *changes* (tracked in session state) so it
    doesn't reopen on every rerun; the button reopens it for the current domain.
    """

    selected_domain_id = selected_row_value(response, "domain_id")
    if not selected_domain_id:
        # Selection cleared — allow the next click on any row to reopen.
        st.session_state.pop(_OPENED_TREND_DOMAIN_KEY, None)
        st.caption(
            "Each domain's **Trend** column shows a per-feed sparkline (most recent day on the "
            "left). Click a domain's Trend cell to open the full interactive graph."
        )
        return

    match = visible_master[visible_master["domain_id"] == selected_domain_id]
    if match.empty:
        return
    row = match.iloc[0]
    feed_rows = json.loads(row["feed_rows_json"])
    timeseries = feed_count_timeseries(feed_rows, [set_date for set_date, _ in date_headers])
    if timeseries.empty:
        st.caption("No daily delivered-count history for the selected domain.")
        return

    reopen = st.button(f"🔍 Enlarge trend — {row['domain_name']}", key="history_enlarge_trend")
    # Auto-open when the clicked domain changed; the button forces a reopen.
    changed_selection = st.session_state.get(_OPENED_TREND_DOMAIN_KEY) != selected_domain_id
    if reopen or changed_selection:
        st.session_state[_OPENED_TREND_DOMAIN_KEY] = selected_domain_id
        _history_trend_dialog(str(row["domain_name"]), timeseries)


def main() -> None:
    st.set_page_config(
        page_title="Domain Feed Health Dashboard",
        page_icon="🛰️",
        layout="wide",
    )
    _install_css()

    if not aggrid_available():
        st.error(
            "AgGrid support is unavailable because `streamlit-aggrid` is not installed. "
            "Run `python -m pip install -e \".[dev]\"` from the project root, then restart Streamlit."
        )

    with st.sidebar:
        st.title("Domain Feed Health Dashboard")
        st.markdown(
            '<div class="info-banner"><strong>Live feed health at a glance.</strong> '
            "The <strong>Current</strong> tab shows today's domain, feed, and device health. "
            "The <strong>Historical</strong> tab shows the last 30 days. Filters below apply to both.</div>",
            unsafe_allow_html=True,
        )
        st.header("Dashboard controls")
        db_path = st.text_input(
            "SQLite history database path",
            value=DEFAULT_DB_PATH,
            help="Local database file the Historical tab reads from (the Generator writes to it at "
            "UTC midnight). Overridable with the DASHBOARD_DB_PATH environment variable.",
        )
        st.markdown("**Refresh data**")
        if st.button(
            "Refresh now",
            help="Poll S3 for new files right now and re-pull aimpoint metadata, instead of waiting "
            "for the automatic 15-minute cycle.",
        ):
            st.session_state[_LAST_CYCLE_SESSION_KEY] = 0.0
            try:
                # Also re-pull aimpoint metadata on the next cycle.
                _get_generator(db_path).clear_aimpoint_cache()
            except Exception:  # noqa: BLE001 - refresh is best-effort
                pass
        search_text = st.text_input(
            "Search domains",
            value="",
            help="Show only domains whose name contains this text (applies to both tabs).",
        )
        selected_statuses = st.multiselect(
            "Domain status filter",
            options=BAND_OPTIONS,
            default=BAND_OPTIONS,
            format_func=lambda value: BAND_ICONS[value],
            help="Show only domains whose status is one of the selected color bands "
            "(⚪ 0% = no aimpoint). Applies to both tabs.",
        )
        history_window_days = st.slider(
            "Historical window (days)",
            min_value=MIN_HISTORY_WINDOW_DAYS,
            max_value=MAX_HISTORY_WINDOW_DAYS,
            value=DEFAULT_HISTORY_WINDOW_DAYS,
            step=1,
            help="How many UTC days back from today the Historical view's feed/device day-pivot grid covers.",
        )

        # Historical view: description (in the subheader's help tooltip) + backfill,
        # at the bottom of the sidebar.
        st.subheader(
            "Feed history",
            help=(
                "Click a domain row to expand its feeds, then click a feed to inspect its device "
                "(aimpoint), mirroring the Current tab. Domain Status is the WINDOW aggregate over the "
                f"selected {history_window_days} days (total delivered ÷ total expected), so shrinking "
                "the window can change a domain's color. Each feed cell shows that day's delivered file "
                "count, colored by delivered ÷ expected: green = 95-100%, yellow = 80-94%, "
                "orange = 70-79%, red = 0-69% or over 100%; — = feed not present that day."
            ),
        )
        if st.button(
            "Backfill / refresh history now",
            key="history_backfill_button",
            help="Fill any missing completed days into the history database from S3. May take a "
            "while when many days are missing.",
        ):
            try:
                with st.spinner("Backfilling history from S3 — this can take a while depending on how many days are missing..."):
                    _get_generator(db_path).backfill_history()
            except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
                st.warning(f"Backfill failed: {exc}")
            else:
                st.rerun()

    tab_current, tab_historical = st.tabs(["Current", "Historical"])

    with tab_current:
        live_domains, live_error = _load_live_domains(db_path)
        if live_error:
            st.warning(f"Live data unavailable right now: {live_error}")

        summary = build_domain_band_summary(live_domains)
        visible_ids = filter_domain_band_summary(summary, search_text, selected_statuses)
        visible_summary = summary[summary["domain_id"].isin(visible_ids)]
        visible_domains = tuple(
            domain for domain in live_domains if (domain.domain_id or domain.domain_name) in visible_ids
        )

        _render_overall_metrics(visible_summary)
        _render_master_detail_domain_table(visible_domains)

    with tab_historical:
        _render_history_section(
            db_path,
            window_days=int(history_window_days),
            search_text=search_text,
            selected_statuses=selected_statuses,
            live_domains=live_domains,
        )
