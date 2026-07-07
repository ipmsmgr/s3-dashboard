"""Table-shaping helpers for the Streamlit AgGrid UI.

These helpers keep non-UI transformations testable without importing Streamlit.
Records come from the live :class:`~domain_feed_health_dashboard.services.generator.Generator`
tally or the 30-day :class:`~domain_feed_health_dashboard.db.repository.Repository` history.
"""

from __future__ import annotations

import json

import pandas as pd

from domain_feed_health_dashboard.data_model import DomainRecord, FeedRecord, RouterAccessPoint
from domain_feed_health_dashboard.status import (
    BAND_ICONS,
    BAND_SUMMARY_COLUMNS,
    build_domain_band_summary,
    feed_health_band,
)

# Feed grid columns: Device ID, Status, File Count, Expected / Day, Location,
# Collection Type, Collection Region, Proxy. headerName mapping lives in
# grid_config.py. Location / Collection Region / Proxy come from the feed's
# device aimpoint (longLat / collRegions / proxy), not the FeedRecord.
FEED_VISIBLE_COLUMNS = [
    "feed_id",
    "status_label",
    "count",
    "expected_per_day",
    "location",
    "feed_type",
    "coll_region",
    "proxy",
]

# Feed row data also carries a hidden "band" (the delivered-vs-expected color
# band) used to colour the Status and File Count cells, and a hidden
# router_rows_json consumed by AgGrid master/detail expansion. Keep nested
# lists/dicts out of pandas DataFrames so Streamlit can hash without warnings.
FEED_DETAIL_COLUMNS = [*FEED_VISIBLE_COLUMNS, "band", "router_rows_json"]

# Device detail is a two-column Field/Value layout.
DEVICE_DETAIL_COLUMNS = ["field", "value"]

# Nice labels for known aimpoint keys (see aimpoint_structure.txt); any key not
# listed falls back to a humanized version of the raw key, so the full/evolving
# structure is always shown.
_AIMPOINT_LABELS: dict[str, str] = {
    "deviceID": "Device ID", "hpID": "HP ID", "collEnabled": "Collection Enabled",
    "collRegions": "Collection Regions", "decoy": "Decoy", "proxy": "Proxy",
    "collectionType": "Collection Type", "accessUrl": "Access URL",
    "pollFrequency": "Poll Frequency (s)", "honorExtinf": "Honor EXTINF",
    "firstContactData": "First Contact", "subtype": "Subtype", "cookie": "Cookie",
    "urlTemplate": "URL Template", "group": "Group", "key": "Key",
    "prependUrl": "Prepend URL", "playlistRegex": "Playlist Regex",
    "hours": "Working Hours", "tz": "Timezone", "hrs": "Hours", "rndm": "Random (min)",
    "extractAudio": "Extract Audio", "enabled": "Enabled", "longLat": "Location (lon, lat)",
    "singleCollector": "Single Collector", "waitFraction": "Wait Fraction",
    "concatenate": "Concatenate", "transcodeExt": "Transcode Ext",
    "transcodedBuffer": "Transcoded Buffer (s)", "transcoderInterval": "Transcoder Interval (min)",
    "timelapseLen": "Timelapse Length (s)", "timelapseFPS": "Timelapse FPS",
    "wrkBucket": "Work Bucket", "dstBucket": "Dst Bucket",
    "bucketPrefixTemplate": "Bucket Prefix Template", "deliveryKey": "Delivery Key",
    "deliveryLzInput": "Delivery LZ Input", "filenameBase": "Filename Base",
    "finalFileSuffix": "Final File Suffix", "deviceIdList": "Device ID List",
    "accessUrlList": "Access URL List", "filenameBaseList": "Filename Base List",
    "headers": "Headers", "ffmpegDedup": "FFmpeg Dedup", "transcodeOptions": "Transcode Options",
    "input": "Input", "output": "Output", "useCurl": "Use Curl", "devNotes": "Dev Notes",
    "monitoringData": "Monitoring", "monitorFrequency": "Monitor Frequency (h)",
    "lastMonitored": "Last Monitored (epoch)", "lastMonitoredIsoDate": "Last Monitored",
    "movedToMonitored": "Moved To Monitored", "selectionsState": "Selections State",
}


def _humanize(key: str) -> str:
    """Fallback label for an aimpoint key not in _AIMPOINT_LABELS (camelCase → Title)."""
    spaced = "".join(f" {ch}" if ch.isupper() else ch for ch in key).strip()
    return spaced[:1].upper() + spaced[1:] if spaced else key


def _flatten_aimpoint(obj: dict, prefix: str = "") -> list[dict[str, object]]:
    """Flatten the aimpoint dict into ``{field, value}`` rows.

    Nested objects become ``Parent · Child`` rows; arrays are joined; booleans
    render as ``true``/``false``. Only keys present in the JSON are emitted, so
    absent fields are simply omitted (never fabricated).
    """
    rows: list[dict[str, object]] = []
    for raw_key, value in obj.items():
        label = f"{prefix}{_AIMPOINT_LABELS.get(raw_key, _humanize(raw_key))}"
        if isinstance(value, dict):
            rows.extend(_flatten_aimpoint(value, prefix=f"{label} · "))
        elif isinstance(value, list):
            rows.append({"field": label, "value": ", ".join(str(item) for item in value) if value else "—"})
        elif isinstance(value, bool):
            rows.append({"field": label, "value": "true" if value else "false"})
        else:
            rows.append({"field": label, "value": "—" if value is None or value == "" else value})
    return rows


def _parse_aimpoint(device: RouterAccessPoint | None) -> dict:
    """Return a feed's device aimpoint dict (parsed from raw JSON), or ``{}``."""
    if device is None or not device.aimpoint_json:
        return {}
    try:
        data = json.loads(device.aimpoint_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _aimpoint_longlat(aimpoint: dict) -> str:
    """``longLat`` [lon, lat] joined as ``"lon, lat"`` (matches the device panel)."""
    value = aimpoint.get("longLat")
    return ", ".join(str(item) for item in value) if isinstance(value, list) else ""


def _aimpoint_coll_regions(aimpoint: dict) -> str:
    """``collRegions`` (array of AWS regions) joined into one string."""
    value = aimpoint.get("collRegions")
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return "" if value is None else str(value)


def _aimpoint_proxy(aimpoint: dict) -> str:
    """``proxy`` string (``"domain:port"``) or empty when absent."""
    value = aimpoint.get("proxy")
    return "" if value is None else str(value)


def _aimpoint_collection_type(aimpoint: dict) -> str:
    """``collectionType`` string or empty when absent."""
    value = aimpoint.get("collectionType")
    return "" if value is None else str(value)


def _first_feed_device_value(domain: DomainRecord, extractor) -> str:
    """First non-empty aimpoint value across the domain's feeds' devices.

    Used for the domain master's Collection Region / Proxy columns, which the
    request populates from *any* of the domain's feed devices.
    """
    for feed in domain.feeds:
        if not feed.routers:
            continue
        value = extractor(_parse_aimpoint(feed.routers[0]))
        if value:
            return value
    return ""


def device_field_value_rows(routers: tuple[RouterAccessPoint, ...]) -> list[dict[str, object]]:
    """Return Field/Value rows for the aimpoint (device) attached to a feed.

    A feed has at most one device despite ``routers`` being a tuple (see
    ``db/repository.py``). The rows are the full aimpoint structure (flattened
    from the stored raw JSON — see ``aimpoint_structure.txt``) plus the device's
    file-count metrics. Two-column Field/Value layout.
    """

    if not routers:
        return []
    device = routers[0]
    try:
        aimpoint = json.loads(device.aimpoint_json) if device.aimpoint_json else {}
    except (json.JSONDecodeError, TypeError):
        aimpoint = {}
    if not isinstance(aimpoint, dict):
        aimpoint = {}

    # Device ID first (from the record, so it shows even with no aimpoint JSON),
    # then the rest of the aimpoint structure, then status/metrics.
    rows: list[dict[str, object]] = [{"field": "Device ID", "value": device.device_id}]
    rows.extend(_flatten_aimpoint({k: v for k, v in aimpoint.items() if k != "deviceID"}))
    rows.append({"field": "Files Actual", "value": device.files_actual})
    rows.append({"field": "Files Expected", "value": device.files_expected})
    return rows


def feed_detail_rows(domain: DomainRecord, max_feed_rows: int | None = None) -> list[dict[str, object]]:
    """Return feed rows used inside an expanded domain row.

    The visible nested feed grid has the eight columns in FEED_VISIBLE_COLUMNS.
    Each feed row also carries a hidden ``router_rows_json`` value: Field/Value
    rows for that feed's device,
    used for the second-level AgGrid detail grid, allowing domain -> feed ->
    device expansion inside the same drilldown table without storing
    non-hashable list/dict objects in pandas cells.
    """

    feeds: tuple[FeedRecord, ...] = domain.feeds
    if max_feed_rows is not None:
        feeds = feeds[:max_feed_rows]

    rows: list[dict[str, object]] = []
    for feed in feeds:
        band = feed_health_band(feed)
        # Collection Type / Location / Collection Region / Proxy come from the
        # feed's device aimpoint (collectionType / longLat / collRegions / proxy),
        # not the FeedRecord.
        aimpoint = _parse_aimpoint(feed.routers[0]) if feed.routers else {}
        rows.append(
            {
                "feed_id": feed.feed_id,
                "status_label": BAND_ICONS[band],
                "count": feed.count,
                "expected_per_day": feed.routers[0].files_expected if feed.routers else None,
                "location": _aimpoint_longlat(aimpoint),
                "feed_type": _aimpoint_collection_type(aimpoint),
                "coll_region": _aimpoint_coll_regions(aimpoint),
                "proxy": _aimpoint_proxy(aimpoint),
                "band": band,
                "router_rows_json": json.dumps(device_field_value_rows(feed.routers), separators=(",", ":")),
            }
        )
    return rows


def domain_master_detail_dataframe(domains: tuple[DomainRecord, ...], max_feed_rows: int | None = None) -> pd.DataFrame:
    """Return one domain row per domain with nested feed rows for AgGrid.

    The ``feed_rows_json`` string column is hidden in the parent grid and
    consumed by AgGrid master/detail expansion. It intentionally stores JSON
    text rather than list/dict objects so Streamlit can hash the DataFrame
    without non-hashable object warnings.
    """

    summary = build_domain_band_summary(domains)
    if summary.empty:
        return pd.DataFrame(columns=[*BAND_SUMMARY_COLUMNS, "coll_region", "proxy", "displayed_feed_rows", "feed_rows_json"])

    domains_by_id = {domain.domain_id or domain.domain_name: domain for domain in domains}
    feeds_by_domain_id = {
        domain_id: feed_detail_rows(domain, max_feed_rows=max_feed_rows)
        for domain_id, domain in domains_by_id.items()
    }
    summary = summary.copy()
    # Collection Region / Proxy come from any of the domain's feed devices.
    summary["coll_region"] = summary["domain_id"].map(
        lambda value: _first_feed_device_value(domains_by_id[str(value)], _aimpoint_coll_regions) if str(value) in domains_by_id else ""
    )
    summary["proxy"] = summary["domain_id"].map(
        lambda value: _first_feed_device_value(domains_by_id[str(value)], _aimpoint_proxy) if str(value) in domains_by_id else ""
    )
    summary["displayed_feed_rows"] = summary["domain_id"].map(lambda value: len(feeds_by_domain_id.get(str(value), [])))
    summary["feed_rows_json"] = summary["domain_id"].map(
        lambda value: json.dumps(feeds_by_domain_id.get(str(value), []), separators=(",", ":"))
    )
    return summary[[*BAND_SUMMARY_COLUMNS, "coll_region", "proxy", "displayed_feed_rows", "feed_rows_json"]]


def device_field_value_dataframe(routers: tuple[RouterAccessPoint, ...]) -> pd.DataFrame:
    """Return the device's Field/Value rows as a DataFrame (non-AgGrid fallback rendering)."""

    return pd.DataFrame(device_field_value_rows(routers), columns=DEVICE_DETAIL_COLUMNS)
