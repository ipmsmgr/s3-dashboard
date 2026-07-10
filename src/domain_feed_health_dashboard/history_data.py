"""30-day feed history pivot grid — non-UI logic.

One row per feed, one column per day (newest day first), each cell the
delivered file count coloured by its delivered-vs-expected band. Sourced from
the :class:`~domain_feed_health_dashboard.db.repository.Repository` 30-day
SQLite history.

Kept free of Streamlit imports so the pivot/styling logic is testable with
plain pytest, per this project's "non-UI logic stays testable" convention
(see status.py / table_data.py).
"""

from __future__ import annotations

import json

import pandas as pd

from domain_feed_health_dashboard.data_model import DeviceRecord, FeedRecord
from domain_feed_health_dashboard.db.repository import Repository
from domain_feed_health_dashboard.status import (
    BAND_SUMMARY_COLUMNS,
    NONE_BAND,
    cell_health_band,
    rollup_band,
    summarize_domain_bands,
)
from domain_feed_health_dashboard.table_data import (
    _aimpoint_coll_regions,
    _aimpoint_proxy,
    _parse_aimpoint,
    device_field_value_rows,
)

FEED_ID_COLUMN = "feed_id"

# Columns of the history domain master grid (one row per domain): the shared
# band summary (status.BAND_SUMMARY_COLUMNS), a hidden ``feed_rows_json``
# carrying that domain's feed×day pivot rows for AgGrid master/detail expansion,
# ``coll_region`` / ``proxy`` (from any feed's device aimpoint, like the Current
# tab); and ``trend_img`` — a pre-rendered PNG (``data:`` URI) line sparkline of
# the domain's daily total delivered counts, shown in the grid's last ("Trend")
# column as a cell background image (see grid_config.TREND_IMAGE_STYLE_JS).
HISTORY_MASTER_COLUMNS = [*BAND_SUMMARY_COLUMNS, "coll_region", "proxy", "feed_rows_json", "trend_img"]

# Each visible day column ``"<date>"`` (delivered file count) is paired with a
# hidden ``"<date>__status"`` column carrying the RED/YELLOW/GREEN status used
# to colour the count cell. grid_config.py imports this suffix so the AgGrid
# cellStyle callback can read the sibling status field.
STATUS_COLUMN_SUFFIX = "__status"

# Historical window: defaults to 30 days, configurable from 1 to 31 days back
# from the current day (matches the Repository's 30-day retention; 31 covers
# retention plus today).
DEFAULT_HISTORY_WINDOW_DAYS = 30
MIN_HISTORY_WINDOW_DAYS = 1
MAX_HISTORY_WINDOW_DAYS = 31

_STATUS_CELL_STYLE: dict[str, str] = {
    "red": "background-color: #dc2626; color: #ffffff; font-weight: 700;",
    "orange": "background-color: #f97316; color: #7c2d12; font-weight: 700;",
    "yellow": "background-color: #facc15; color: #422006; font-weight: 700;",
    "green": "background-color: #16a34a; color: #ffffff; font-weight: 700;",
    "none": "background-color: #e5e7eb; color: #6b7280;",  # no aimpoint → gray
}
MISSING_DAY_LABEL = "—"


def _aimpoint_by_day(
    routers_by_day: dict[str, tuple[DeviceRecord, ...]],
) -> dict[str, object]:
    """The feed's stored aimpoint for *each specific day* it exists (deduped).

    Returns ``{"days": {set_date: variant_index}, "variants": [<device rows>, …]}``.
    A day is present in ``days`` only if the feed had a non-empty stored aimpoint
    that exact day (aimpoints occasionally change, so each day maps to its own
    variant). Identical aimpoints across days share one entry in ``variants`` to
    keep the payload small. A clicked day not in ``days`` has no aimpoint that day
    → "No aimpoint exists" (no fall-back to a previous day).
    """
    variants: list[list[dict[str, object]]] = []
    signatures: list[str] = []
    days: dict[str, int] = {}
    for set_date in sorted(routers_by_day):  # oldest → newest
        routers = routers_by_day[set_date]
        if not routers or not routers[0].aimpoint_json:
            continue  # no aimpoint that day
        signature = routers[0].aimpoint_json
        try:
            index = signatures.index(signature)
        except ValueError:
            index = len(variants)
            signatures.append(signature)
            variants.append(device_field_value_rows(routers))
        days[set_date] = index
    return {"days": days, "variants": variants}


def _feed_file_count(feed: FeedRecord) -> int:
    """Delivered file count for a feed on a day.

    Uses the attached device's Files Actual (the per-device delivery tally),
    falling back to the feed's own ``count`` when no device row is present.
    """

    if feed.routers:
        return feed.routers[0].files_actual
    return feed.count


def _feed_expected(feed: FeedRecord) -> int:
    """Expected daily file count for a feed — its device's Files Expected."""

    return feed.routers[0].files_expected if feed.routers else 0


# Feed line colours, shared by the inline PNG sparkline and the enlarged Altair
# chart so the two look the same. Feeds are colour-indexed by their sorted order
# (Altair also sorts a nominal domain alphabetically), so line i gets colour i
# in both. Approximates Altair's default tableau10 scheme.
TREND_COLOR_PALETTE = [
    "#4c78a8", "#f58518", "#e45756", "#72b7b2", "#54a24b",
    "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac",
]


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def domain_feed_series(
    counts_by_feed: dict[str, dict[str, int]],
    feed_ids: list[str],
    dates_newest_first: list[str],
) -> list[list[int]]:
    """Per-feed daily delivered counts, one list per feed (``feed_ids`` order).

    Each list is newest-first (same order as ``dates_newest_first``); a day a
    feed was absent counts as 0. Mirrors the per-feed lines the enlarged Altair
    chart draws, so the inline sparkline has the same shape.
    """

    return [
        [int(counts_by_feed.get(feed_id, {}).get(set_date) or 0) for set_date in dates_newest_first]
        for feed_id in feed_ids
    ]


def domain_trend_png(feed_series: list[list[int]], width: int = 300, height: int = 68) -> str:
    """Render a domain's per-feed daily counts as a small multi-line PNG (``data:`` URI).

    One line per feed (coloured from ``TREND_COLOR_PALETTE`` by feed order, to
    match the enlarged chart), drawn at 2× the display size for crispness (the
    grid scales it down with ``background-size: contain``). Series are
    newest-first, so lines run left→right = most-recent→oldest, matching the
    enlarged graph's reversed x-axis, with a shared 0→max y baseline. Returns
    ``""`` when there is nothing to draw or Pillow is unavailable.
    """

    if not feed_series:
        return ""
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001 - degrade gracefully without Pillow
        return ""
    import base64
    import io

    pad = 6
    vmax = max((v for series in feed_series for v in series), default=0)
    if vmax <= 0:
        vmax = 1  # avoid divide-by-zero; a flat all-zero domain draws along the baseline

    def y_of(value: float) -> float:
        return height - pad - (value / vmax) * (height - 2 * pad)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for index, series in enumerate(feed_series):
        n = len(series)
        if n == 0:
            continue
        step = (width - 2 * pad) / (n - 1) if n > 1 else 0
        points = [(pad + i * step, y_of(v)) for i, v in enumerate(series)]
        color = _hex_to_rgb(TREND_COLOR_PALETTE[index % len(TREND_COLOR_PALETTE)]) + (255,)
        if n > 1:
            draw.line(points, fill=color, width=2, joint="curve")
        x0, y0 = points[0]
        draw.ellipse([x0 - 3, y0 - 3, x0 + 3, y0 + 3], fill=color)  # dot on most-recent day

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/png;base64," + encoded


def _domain_aimpoint_field(feed_router_lists, extractor) -> str:
    """First non-empty aimpoint value across a domain's feeds' devices.

    Mirrors ``table_data._first_feed_device_value`` (Current tab) — used for the
    History domain master's Collection Region / Proxy columns.
    """
    for routers in feed_router_lists:
        if not routers:
            continue
        value = extractor(_parse_aimpoint(routers[0]))
        if value:
            return value
    return ""


def domain_ids_with_history(repository: Repository) -> list[str]:
    """Return domain IDs present in the most recently completed history set."""

    dates = repository.available_dates()
    if not dates:
        return []
    domains = repository.get_history_domains(set_date=dates[0])
    return sorted({domain.domain_id for domain in domains})


def history_date_columns(pivot: pd.DataFrame) -> list[str]:
    """Return the visible day columns of *pivot* (excludes id + status columns)."""

    return [
        column
        for column in pivot.columns
        if column != FEED_ID_COLUMN and not str(column).endswith(STATUS_COLUMN_SUFFIX)
    ]


def build_feed_history_pivot(
    repository: Repository,
    domain_id: str,
    max_days: int = DEFAULT_HISTORY_WINDOW_DAYS,
) -> pd.DataFrame:
    """Return a feed x day pivot of delivered file counts for *domain_id*.

    Rows are feeds (by ``feed_id``); columns are ``set_date`` strings ordered
    newest first. Each day cell holds that feed's delivered file count (the
    device's Files Actual) on that day, or NaN if the feed was not present in
    that day's completed set. Each day column ``"<date>"`` is paired with a
    hidden ``"<date>__status"`` column carrying that cell's color band
    (``green``/``yellow``/``orange``/``red``), scaled by the delivered-vs-expected
    percentage (see :func:`~domain_feed_health_dashboard.status.cell_health_band`).
    """

    dates = repository.available_dates()[:max_days]
    if not dates:
        return pd.DataFrame(columns=[FEED_ID_COLUMN])

    counts_by_feed: dict[str, dict[str, int]] = {}
    status_by_feed: dict[str, dict[str, str]] = {}
    has_aimpoint: dict[str, bool] = {}
    for set_date in dates:
        for domain in repository.get_history_domains(set_date=set_date):
            if domain.domain_id != domain_id:
                continue
            for feed in domain.feeds:
                count = _feed_file_count(feed)
                expected = _feed_expected(feed)
                counts_by_feed.setdefault(feed.feed_id, {})[set_date] = count
                status_by_feed.setdefault(feed.feed_id, {})[set_date] = cell_health_band(count, expected)
                has_aimpoint[feed.feed_id] = has_aimpoint.get(feed.feed_id, False) or expected > 0

    columns: list[str] = [FEED_ID_COLUMN]
    for set_date in dates:
        columns.append(set_date)
        columns.append(f"{set_date}{STATUS_COLUMN_SUFFIX}")

    if not counts_by_feed:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for feed_id in sorted(counts_by_feed):
        per_count = counts_by_feed[feed_id]
        per_status = status_by_feed[feed_id]
        feed_gray = not has_aimpoint.get(feed_id, False)  # no aimpoint at all → gray
        row: dict[str, object] = {FEED_ID_COLUMN: feed_id}
        for set_date in dates:
            count = per_count.get(set_date)
            if count is None:
                row[set_date] = None
                status = None
            else:
                # No aimpoint → no files: default the count to 0. Nothing delivered
                # (count 0) → gray, since there is nothing to assess.
                shown = 0 if feed_gray else count
                row[set_date] = shown
                status = NONE_BAND if shown == 0 else per_status.get(set_date)
            row[f"{set_date}{STATUS_COLUMN_SUFFIX}"] = status
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def build_history_domain_master(
    repository: Repository,
    max_days: int = DEFAULT_HISTORY_WINDOW_DAYS,
    live_routers: dict[tuple[str, str], tuple[DeviceRecord, ...]] | None = None,
) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """Return ``(master_df, date_headers)`` for the history master/detail grid.

    A single nested AgGrid (domain table → feed×day grid → device aimpoint):
    one master row per domain with
    history in the window, each carrying a hidden ``feed_rows_json`` of that
    domain's feed×day pivot rows. Every feed pivot row in turn carries its
    device's aimpoint Field/Value rows as ``router_rows_json`` for the
    second-level (device) detail grid. Day cells hold the delivered file count
    with a hidden ``"<date>__status"`` band sibling for colouring; a feed not
    present on a day is ``None``.

    ``live_routers`` maps ``(domain_id, feed_id)`` to the most recent (live)
    aimpoint for that feed; when supplied it is used for the device detail in
    preference to the stored historical device row, so the History tab shows
    the current aimpoint config (stored rows may predate aimpoint capture).

    ``date_headers`` is ``[(set_date, "M/D")]`` newest-first for the detail
    grid's day columns.
    """

    dates = repository.available_dates()[:max_days]
    if not dates:
        return pd.DataFrame(columns=HISTORY_MASTER_COLUMNS), []

    # Gather per domain/feed across the window. dates is newest-first, so the
    # first FeedRecord seen for a feed is its most recent (used for the domain
    # rollup and the device aimpoint detail).
    names: dict[str, str] = {}
    latest_feed: dict[str, dict[str, FeedRecord]] = {}
    counts: dict[str, dict[str, dict[str, int]]] = {}
    bands: dict[str, dict[str, dict[str, str]]] = {}
    # Whether a feed has an aimpoint on ANY day in the window (expected > 0). A
    # feed with none is "no aimpoint at all" → gray.
    has_aimpoint: dict[str, dict[str, bool]] = {}
    # Stored routers per feed per day, for the per-day aimpoint detail.
    day_routers: dict[str, dict[str, dict[str, tuple[DeviceRecord, ...]]]] = {}
    for set_date in dates:
        for domain in repository.get_history_domains(set_date=set_date):
            domain_id = domain.domain_id
            names.setdefault(domain_id, domain.domain_name)
            for feed in domain.feeds:
                count = _feed_file_count(feed)
                expected = _feed_expected(feed)
                counts.setdefault(domain_id, {}).setdefault(feed.feed_id, {})[set_date] = count
                bands.setdefault(domain_id, {}).setdefault(feed.feed_id, {})[set_date] = cell_health_band(
                    count, expected
                )
                feed_seen = has_aimpoint.setdefault(domain_id, {})
                feed_seen[feed.feed_id] = feed_seen.get(feed.feed_id, False) or expected > 0
                day_routers.setdefault(domain_id, {}).setdefault(feed.feed_id, {})[set_date] = feed.routers
                latest_feed.setdefault(domain_id, {}).setdefault(feed.feed_id, feed)

    if not names:
        return pd.DataFrame(columns=HISTORY_MASTER_COLUMNS), []

    date_headers = [(set_date, format_day_header(set_date)) for set_date in dates]

    rows: list[dict[str, object]] = []
    for domain_id in sorted(names, key=lambda d: names[d].lower()):
        feed_ids = sorted(counts.get(domain_id, {}))

        def _no_aimpoint(feed_id: str) -> bool:
            return not has_aimpoint[domain_id].get(feed_id, False)

        def _day_count(feed_id: str, set_date: str) -> int | None:
            """The delivered count shown for a feed on a day; ``None`` when absent.
            A feed with no aimpoint at all delivers nothing that can be assessed,
            so its cells default to 0 (no aimpoint → no files)."""
            raw = counts[domain_id][feed_id].get(set_date)
            if raw is None:
                return None
            return 0 if _no_aimpoint(feed_id) else int(raw)

        def _day_band(feed_id: str, set_date: str) -> str | None:
            """The cell band for a feed on a day; ``None`` for a day it was absent.

            Gray ("none") when nothing was delivered that day (count 0 — including
            a feed with no aimpoint at all), since there is nothing to assess.
            """
            count = _day_count(feed_id, set_date)
            if count is None:
                return None
            if count == 0:
                return NONE_BAND
            return bands[domain_id][feed_id][set_date]

        # Worst color propagates upward (device cell → feed → domain). A feed's
        # band is the WORST of its day cells in the window, so any red day makes
        # the feed — and thus the domain — red. A feed with no aimpoint at all is
        # gray ("none"); it never forces the domain, and a domain whose feeds are
        # ALL no-aimpoint is itself gray. Shrinking the window drops bad days, so
        # a domain red over 30 days can be green over 10.
        feed_window_bands = [
            rollup_band([b for b in (_day_band(feed_id, d) for d in dates) if b is not None])
            for feed_id in feed_ids
        ]

        summary = summarize_domain_bands(
            domain_id,
            names[domain_id],
            feed_window_bands,
            max((latest_feed[domain_id][feed_id].observed_time for feed_id in feed_ids), default=""),
        )

        feed_rows: list[dict[str, object]] = []
        for feed_id in feed_ids:
            feed_row: dict[str, object] = {FEED_ID_COLUMN: feed_id}
            for set_date in dates:
                feed_row[set_date] = _day_count(feed_id, set_date)
                feed_row[f"{set_date}{STATUS_COLUMN_SUFFIX}"] = _day_band(feed_id, set_date)
            # Default device detail (no day selected): the most recent (live)
            # aimpoint, falling back to the stored historical device row.
            routers = (live_routers or {}).get((domain_id, feed_id))
            if not routers:
                routers = latest_feed[domain_id][feed_id].routers
            feed_row["router_rows_json"] = json.dumps(
                device_field_value_rows(routers),
                separators=(",", ":"),
            )
            # Per-day aimpoint: the STORED aimpoint for each specific day, so a
            # clicked day shows that exact day's aimpoint — or "No aimpoint
            # exists" if that day has none (no fall-back to a previous day).
            feed_row["aimpoint_by_day_json"] = json.dumps(
                _aimpoint_by_day(day_routers.get(domain_id, {}).get(feed_id, {})),
                separators=(",", ":"),
            )
            feed_rows.append(feed_row)

        # Trend uses the same displayed counts (gray feeds contribute 0).
        effective_counts = {
            feed_id: {d: c for d in dates if (c := _day_count(feed_id, d)) is not None}
            for feed_id in feed_ids
        }
        feed_series = domain_feed_series(effective_counts, feed_ids, dates)
        # Collection Region / Proxy from any feed's device aimpoint (live-preferred,
        # same source as the device detail), like the Current tab.
        feed_router_lists = [
            (live_routers or {}).get((domain_id, feed_id)) or latest_feed[domain_id][feed_id].routers
            for feed_id in feed_ids
        ]
        rows.append({
            **summary,
            "coll_region": _domain_aimpoint_field(feed_router_lists, _aimpoint_coll_regions),
            "proxy": _domain_aimpoint_field(feed_router_lists, _aimpoint_proxy),
            "feed_rows_json": json.dumps(feed_rows, separators=(",", ":")),
            "trend_img": domain_trend_png(feed_series),
        })

    return pd.DataFrame(rows, columns=HISTORY_MASTER_COLUMNS), date_headers


def feed_count_timeseries(
    feed_rows: list[dict],
    dates_newest_first: list[str],
) -> pd.DataFrame:
    """Long-form day/feed/count table for the per-domain line graph.

    Reshapes a domain's feed×day pivot rows (the parsed ``feed_rows_json`` of
    one master row) into ``(day, feed, count)`` records, oldest day first, with
    a missing day counted as 0. ``count`` is that feed's delivered files that
    day (the sum across the feed's devices); one line per feed when plotted.
    """

    dates = list(reversed(dates_newest_first))  # oldest first for the x-axis
    records: list[dict[str, object]] = []
    for row in feed_rows:
        feed_id = row.get(FEED_ID_COLUMN)
        for set_date in dates:
            value = row.get(set_date)
            records.append({
                "day": pd.Timestamp(set_date),
                "feed": feed_id,
                "count": int(value) if value is not None else 0,
            })
    return pd.DataFrame(records, columns=["day", "feed", "count"])


def status_cell_style(status: object) -> str:
    """Return the CSS style string for a cell given its RYG status string."""

    if isinstance(status, str):
        return _STATUS_CELL_STYLE.get(status, "")
    return ""


def style_feed_history_pivot(pivot: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """Return a pandas Styler rendering *pivot* as RYG-colored file-count cells.

    Each day cell shows the delivered file count (``—`` when the feed was
    absent that day), coloured by the cell's parallel status column so colour
    is paired with a number rather than being the only signal.
    """

    date_columns = history_date_columns(pivot)
    display_df = pivot[[FEED_ID_COLUMN, *date_columns]].copy()
    style_df = pd.DataFrame("", index=pivot.index, columns=[FEED_ID_COLUMN, *date_columns])
    for column in date_columns:
        statuses = pivot[f"{column}{STATUS_COLUMN_SUFFIX}"]
        style_df[column] = statuses.map(status_cell_style)
        # Render every day cell as a string ("—" or the count) so the column is
        # single-typed and serializes cleanly to Arrow for st.dataframe.
        display_df[column] = display_df[column].map(
            lambda value: MISSING_DAY_LABEL if pd.isna(value) else str(int(value))
        )
    return display_df.style.apply(lambda _frame: style_df, axis=None)


def format_day_header(set_date: str) -> str:
    """Format a ``"YYYY-MM-DD"`` set_date as a short ``M/D`` column header."""

    year, month, day = set_date.split("-")
    return f"{int(month)}/{int(day)}"
