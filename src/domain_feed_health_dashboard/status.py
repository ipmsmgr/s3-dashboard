"""Status severity helpers for domains, feeds, and devices.

Rollup rules
------------
* Feed status and device status are stored as-is from their source files.
* Domain status = max(feed_status, device_status) across ALL feeds in the
  domain.  One red device or one red feed makes the whole domain red.
* Severity mapping: green=1, yellow=2, red=3.  ``max()`` gives worst-wins.
* Zero feeds → domain is yellow (health unknown).
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Iterable, Optional

import pandas as pd

from domain_feed_health_dashboard.data_model import DomainRecord, FeedRecord, Status

# A feed at or below this fraction of its expected daily file count is RED.
RED_MAX_RATIO = 0.5

STATUS_SEVERITY: dict[Status, int] = {"green": 1, "yellow": 2, "red": 3}
STATUS_LABELS: dict[Status, str] = {
    "green": "GREEN / Good",
    "yellow": "YELLOW / Unknown",
    "red": "RED / Broken",
}
STATUS_ICONS: dict[Status, str] = {
    "green": "🟢 GREEN / Good",
    "yellow": "🟡 YELLOW / Unknown",
    "red": "🔴 RED / Broken",
}


def status_from_count(count: int, expected: int) -> Status:
    """Derive feed health from delivered vs. expected daily file counts.

    A feed with no expected files is GREEN only if at least one file was
    delivered, otherwise RED; at or below half the expected count is RED; at or
    above the expected count is GREEN; anything in between is YELLOW. Non-numeric
    inputs are RED.
    """
    try:
        count = int(count)
        expected = int(expected)
    except (TypeError, ValueError):
        return "red"
    if expected <= 0:
        return "green" if count > 0 else "red"
    if count <= expected * RED_MAX_RATIO:
        return "red"
    if count >= expected:
        return "green"
    return "yellow"


def cell_health_band(actual: int, expected: int) -> str:
    """Color band for a delivery cell, scaled by ``(actual / expected) * 100``.

    Bands (percentage of expected daily files actually delivered):

    * ``> 100%`` (over-delivery) or ``0-69%`` → ``"red"``
    * ``70-79%`` → ``"orange"``
    * ``80-94%`` → ``"yellow"``
    * ``95-100%`` → ``"green"``

    A non-positive expected count (no usable op window) is ``"red"`` since the
    delivery rate cannot be assessed. Returns one of
    ``"green" | "yellow" | "orange" | "red"`` — note ``"orange"`` is a
    cell-coloring band only, not a :data:`Status` used in domain rollups.
    """
    try:
        actual = int(actual)
        expected = int(expected)
    except (TypeError, ValueError):
        return "red"
    if expected <= 0:
        return "red"
    pct = (actual / expected) * 100
    if pct > 100:
        return "red"
    if pct >= 95:
        return "green"
    if pct >= 80:
        return "yellow"
    if pct >= 70:
        return "orange"
    return "red"


# ── Percentage health bands (the UI color model, shared by both tabs) ───────
#
# Domain/feed coloring in the dashboard is driven by the delivered-vs-expected
# percentage band (cell_health_band), not the 3-level stored feed.status. Bands
# add "orange" (70-79%) between yellow and red. The 3-level helpers above remain
# for the SQLite write path (db/schema feed_status, domain_sets rollups).
# "none" (gray) is a non-health state meaning "no aimpoint exists at all", so the
# delivery rate cannot be assessed. It has no severity (0) — it never wins a
# rollup against a real band — but when EVERY band in a rollup is "none" the
# result is "none" (a gray feed/domain), distinct from "red" (broken delivery).
NONE_BAND = "none"
# Current tab: how far the delivered count may sit from the expected-so-far count
# and still be green — a one-file grace for delivery timing around an interval.
CURRENT_BAND_TOLERANCE = 1
BAND_SEVERITY: dict[str, int] = {"green": 1, "yellow": 2, "orange": 3, "red": 4}
# Domain-status filter options (sidebar), including "none" (gray = no aimpoint).
BAND_OPTIONS = ["green", "yellow", "orange", "red", "none"]
# Filter labels: a colored box + the percentage range only (no color words); the
# gray "no aimpoint" box reads 0%.
BAND_ICONS: dict[str, str] = {
    "green": "🟢 95-100%",
    "yellow": "🟡 80-94%",
    "orange": "🟠 70-79%",
    "red": "🔴 <70% or >100%",
    "none": "⚪ 0%",
}
BAND_SUMMARY_COLUMNS = [
    "domain_id", "domain_name", "domain_band", "status_label",
    "total_feeds", "green_feeds", "yellow_feeds", "orange_feeds", "red_feeds",
    "last_observed_time",
]


def rollup_band(bands: Iterable[str]) -> str:
    """Worst-wins rollup of child bands (red worst), ignoring ``"none"``.

    ``"none"`` (no aimpoint) is non-contributing, so a real band always wins.
    When there are child bands but ALL of them are ``"none"`` the rollup is
    ``"none"`` (a gray feed/domain — no aimpoint at all). With no child bands at
    all the rollup is ``"red"`` (no delivery).
    """
    bands = list(bands)
    worst = 0
    for band in bands:
        worst = max(worst, BAND_SEVERITY.get(band, 0))
    if worst > 0:
        return next(b for b, v in BAND_SEVERITY.items() if v == worst)
    if bands:  # children exist but every one is "none" → gray, not red
        return NONE_BAND
    return "red"  # no feeds/cells at all → no delivery


def current_feed_band(feed: FeedRecord, now=None) -> str:
    """Current-tab feed band: green / yellow / gray, never red.

    A feed is green while the delivered count is within ±1 of the files expected
    *by now* (from the aimpoint's operating hours, see
    ``log_parser.expected_file_count_so_far``) — a one-file tolerance absorbs
    normal timing jitter around a transcoder-interval boundary. A larger
    deviation (extra or missing files for the current time) is ``"yellow"``.

    A feed is ``"none"`` (gray) when there is nothing to assess: **no files
    delivered** (count 0 — e.g. a configured device that isn't producing), or no
    aimpoint available. ``now`` defaults to the current time.
    """
    try:
        if int(feed.count) == 0:
            return NONE_BAND        # nothing delivered → nothing to assess
    except (TypeError, ValueError):
        return NONE_BAND

    routers = feed.routers
    if not routers or not routers[0].aimpoint_json:
        return NONE_BAND
    # Imported lazily: log_parser imports this module (status), so a top-level
    # import here would be circular.
    from domain_feed_health_dashboard.services.log_parser import expected_file_count_so_far

    try:
        aimpoint = json.loads(routers[0].aimpoint_json)
    except (json.JSONDecodeError, TypeError):
        return NONE_BAND
    if not isinstance(aimpoint, dict):
        return NONE_BAND
    expected = expected_file_count_so_far(aimpoint, now)
    try:
        actual = int(feed.count)
    except (TypeError, ValueError):
        actual = 0
    return "green" if abs(actual - expected) <= CURRENT_BAND_TOLERANCE else "yellow"


def summarize_domain_bands(
    domain_id: str,
    domain_name: str,
    feed_bands: list[str],
    last_observed_time: str,
) -> dict[str, object]:
    """One band-summary row for a domain given its feeds' health bands."""
    counts = Counter(feed_bands)
    band = rollup_band(feed_bands)
    return {
        "domain_id": domain_id,
        "domain_name": domain_name,
        "domain_band": band,
        "status_label": BAND_ICONS[band],
        "total_feeds": len(feed_bands),
        "green_feeds": counts.get("green", 0),
        "yellow_feeds": counts.get("yellow", 0),
        "orange_feeds": counts.get("orange", 0),
        "red_feeds": counts.get("red", 0),
        "last_observed_time": last_observed_time,
    }


def build_domain_band_summary(domains: Iterable[DomainRecord], now=None) -> pd.DataFrame:
    """Band-based domain summary for the Current tab (one row per domain).

    Feed bands are green / yellow / gray (never red), and the domain is the worst
    (yellow > green); a domain whose feeds are all gray (no aimpoint) is gray.
    ``now`` is threaded to :func:`current_feed_band` for deterministic tests.
    """
    rows = [
        summarize_domain_bands(
            domain.domain_id or domain.domain_name,
            domain.domain_name,
            [current_feed_band(feed, now) for feed in domain.feeds],
            domain.last_observed_time,
        )
        for domain in domains
    ]
    return pd.DataFrame(rows, columns=BAND_SUMMARY_COLUMNS)


def band_overall_metrics(summary: pd.DataFrame) -> dict[str, int]:
    """Top-level KPI counts (the metric cards) from a band-summary DataFrame."""
    keys = (
        "total_domains", "total_feeds",
        "green_domains", "yellow_domains", "orange_domains", "red_domains",
        "green_feeds", "yellow_feeds", "orange_feeds", "red_feeds",
    )
    if summary.empty:
        return {key: 0 for key in keys}
    return {
        "total_domains": len(summary),
        "total_feeds": int(summary["total_feeds"].sum()),
        "green_domains": int((summary["domain_band"] == "green").sum()),
        "yellow_domains": int((summary["domain_band"] == "yellow").sum()),
        "orange_domains": int((summary["domain_band"] == "orange").sum()),
        "red_domains": int((summary["domain_band"] == "red").sum()),
        "green_feeds": int(summary["green_feeds"].sum()),
        "yellow_feeds": int(summary["yellow_feeds"].sum()),
        "orange_feeds": int(summary["orange_feeds"].sum()),
        "red_feeds": int(summary["red_feeds"].sum()),
    }


def filter_domain_band_summary(
    summary: pd.DataFrame,
    search_text: str,
    selected_bands: list[str],
    only_red_feeds: bool = False,
) -> set[str]:
    """Return the set of visible ``domain_id``s after applying sidebar filters.

    Shared by both tabs so the Search / status-filter widgets apply to the
    Current and Historical views alike. ``only_red_feeds`` is retained (default
    off) for callers/tests, though the sidebar checkbox that drove it was removed.
    """
    if summary.empty:
        return set()
    visible = set(summary["domain_id"].tolist())
    if search_text.strip():
        needle = search_text.strip().lower()
        matching = summary[summary["domain_name"].str.lower().str.contains(needle, regex=False)]
        visible &= set(matching["domain_id"].tolist())
    if selected_bands:
        # "none" (no-aimpoint / gray) is now a first-class filter option, so it
        # filters like any other band.
        matching = summary[summary["domain_band"].isin(set(selected_bands))]
        visible &= set(matching["domain_id"].tolist())
    if only_red_feeds:
        matching = summary[summary["red_feeds"] > 0]
        visible &= set(matching["domain_id"].tolist())
    return visible


def normalize_status(status: str) -> Status:
    """Return a lower-cased, validated status string."""
    normalized = status.lower().strip()
    if normalized not in STATUS_SEVERITY:
        raise ValueError(f"Unsupported status: {status!r}")
    return normalized  # type: ignore[return-value]


def _severity(status: Optional[str]) -> int:
    """Return numeric severity for *status*.

    ``None`` means no device status is available (e.g. simulated data).
    Treat it as non-contributing (0) so it never inflates the domain rollup
    above the feed's own status.
    """
    if not status:
        return 0
    try:
        return STATUS_SEVERITY[normalize_status(status)]
    except ValueError:
        return 0


def domain_status_from_feeds(feeds: Iterable[FeedRecord]) -> Status:
    """Compute domain status as worst(feed_status, device_status) across all feeds.

    A red device attached to a green feed makes the domain red.
    A red feed attached to a green device makes the domain red.
    Zero feeds → yellow (health unknown).
    """
    feed_list = list(feeds)
    if not feed_list:
        return "yellow"

    worst = 1
    for feed in feed_list:
        worst = max(worst, _severity(feed.status), _severity(feed.device_status))

    return next(s for s, v in STATUS_SEVERITY.items() if v == worst)


def feed_status_counts(feeds: Iterable[FeedRecord]) -> dict[Status, int]:
    """Count red, yellow, and green feed statuses (feed-level only, not device)."""
    counts = Counter(normalize_status(feed.status) for feed in feeds)
    return {
        "red": counts.get("red", 0),
        "yellow": counts.get("yellow", 0),
        "green": counts.get("green", 0),
    }


def summarize_domain(domain: DomainRecord) -> dict[str, object]:
    """Build one summary-row dict for the domain metrics AgGrid table."""
    counts = feed_status_counts(domain.feeds)
    domain_status = domain_status_from_feeds(domain.feeds)
    return {
        "domain_id": domain.domain_id or domain.domain_name,
        "domain_name": domain.domain_name,
        "domain_status": domain_status,
        "status_label": STATUS_ICONS[domain_status],
        "total_feeds": len(domain.feeds),
        "red_feeds": counts["red"],
        "yellow_feeds": counts["yellow"],
        "green_feeds": counts["green"],
        "last_observed_time": domain.last_observed_time,
    }


def build_domain_summary(domains: Iterable[DomainRecord]) -> pd.DataFrame:
    """Return a DataFrame with one summary row per domain."""
    rows = [summarize_domain(domain) for domain in domains]
    columns = [
        "domain_id", "domain_name", "domain_status", "status_label",
        "total_feeds", "red_feeds", "yellow_feeds", "green_feeds",
        "last_observed_time",
    ]
    return pd.DataFrame(rows, columns=columns)


def overall_metrics(domains: Iterable[DomainRecord]) -> dict[str, int]:
    """Compute top-level KPI counts for all visible domains."""
    domain_list = list(domains)
    summary = build_domain_summary(domain_list)
    if summary.empty:
        return {k: 0 for k in (
            "total_domains", "total_feeds",
            "red_domains", "yellow_domains", "green_domains",
            "red_feeds", "yellow_feeds", "green_feeds",
        )}
    return {
        "total_domains":  len(summary),
        "total_feeds":    int(summary["total_feeds"].sum()),
        "red_domains":    int((summary["domain_status"] == "red").sum()),
        "yellow_domains": int((summary["domain_status"] == "yellow").sum()),
        "green_domains":  int((summary["domain_status"] == "green").sum()),
        "red_feeds":      int(summary["red_feeds"].sum()),
        "yellow_feeds":   int(summary["yellow_feeds"].sum()),
        "green_feeds":    int(summary["green_feeds"].sum()),
    }


def select_domain(
    current_selection: str | None,
    selected_domain: str | None,
) -> str | None:
    """Return the next selected domain ID (testable without Streamlit)."""
    return selected_domain or current_selection
