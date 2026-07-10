"""Feed log and device file parsers.

Feed log format
---------------
Each line is a UTF-8 text line that may contain garbage prefix text followed
by a single JSON object::

    2026-06-11 14:30:01 INFO some garbage {"domain_id": "...", ...}

``re.search(r"\\{.*\\}", line)`` is used to extract the JSON block.

Device file format
------------------
A single JSON object stored in S3 at::

    devices/YYYYMMDD_HHMM_<device_id>.json

The device file is fetched once per ``device_id`` per generator cycle and
merged into the in-memory :class:`DomainSetTally`.

Folder extraction
-----------------
The ``delivered`` field in the feed JSON follows the canonical path::

    <root>/<country>/<product>/<channel>/YYYY/MM/DD/<device_id>.ext

The folder aggregation key is produced by stripping the last four components::

    folder = "/".join(parts[:-4])   # "fe/fi/fo/fum"
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from domain_feed_health_dashboard.data_model import DeviceTally, DomainSetTally, FeedTally
from domain_feed_health_dashboard.status import status_from_count
from domain_feed_health_dashboard.utils.logger import logger

# Matches the first JSON object on a line (handles garbage prefix).
_JSON_RE = re.compile(r"\{.*\}")


# ── Folder extraction (reused from utilities/services/log_parser.py) ───────

def extract_folder_and_date(
    delivered_path: str,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Extract folder key, year, month, day from a delivered S3 path.

    The path must contain at least five components and include a
    ``YYYY/MM/DD`` segment::

        fe/fi/fo/fum/2026/05/28/dev-4491.mp4
        →  folder="fe/fi/fo/fum",  year="2026",  month="05",  day="28"

    Returns:
        ``(folder, year, month, day)`` or ``(None, None, None, None)`` if
        the path does not match the expected structure.
    """
    parts = delivered_path.split("/")
    if len(parts) < 5:
        return None, None, None, None

    i = _date_start_index(parts)
    if i is not None:
        return "/".join(parts[:i]), parts[i], parts[i + 1], parts[i + 2]

    return None, None, None, None


def _date_start_index(parts: list[str]) -> Optional[int]:
    """Return the index where a ``YYYY/MM/DD`` segment begins, or ``None``."""
    for i in range(len(parts) - 2):
        year, month, day = parts[i], parts[i + 1], parts[i + 2]
        if (
            year.isdigit() and len(year) == 4 and int(year) >= 2000
            and month.isdigit() and len(month) == 2 and 1 <= int(month) <= 12
            and day.isdigit() and len(day) == 2 and 1 <= int(day) <= 31
        ):
            return i
    return None


# ── Expected file count ─────────────────────────────────────────────────────

DEFAULT_TRANSCODER_INTERVAL = 15   # minutes per produced file
_MINUTES_PER_DAY = 24 * 60


def _hhmm_to_minutes(token: str) -> Optional[int]:
    """Parse an ``HHMM`` (or ``HH:MM``) 24h clock token into minutes-of-day."""
    token = str(token).strip().replace(":", "")
    if len(token) != 4 or not token.isdigit():
        return None
    hh, mm = int(token[:2]), int(token[2:])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh * 60 + mm


def _window_minutes(window: object) -> Optional[int]:
    """Duration in minutes of a ``"timeStart-timeStop"`` window (wraps overnight)."""
    if not isinstance(window, str) or "-" not in window:
        return None
    start_s, stop_s = window.split("-", 1)
    start = _hhmm_to_minutes(start_s)
    stop = _hhmm_to_minutes(stop_s)
    if start is None or stop is None:
        return None
    if stop <= start:                       # overnight / 0000-0000 → full day
        stop += _MINUTES_PER_DAY
    return stop - start


def _interval_minutes(aimpoint: dict) -> int:
    """The aimpoint's ``transcoderInterval`` in minutes, or the default (15)."""
    try:
        interval = int(aimpoint.get("transcoderInterval"))
    except (TypeError, ValueError):
        return DEFAULT_TRANSCODER_INTERVAL
    return interval if interval > 0 else DEFAULT_TRANSCODER_INTERVAL


def _operation_minutes(aimpoint: dict) -> int:
    """Minutes of operation per day from ``hours.hrs`` (+ optional ``rndm``).

    No ``hours`` (or no parseable window) → 24-hour operation.
    """
    hours = aimpoint.get("hours")
    if not isinstance(hours, dict):
        return _MINUTES_PER_DAY
    total = 0
    for window in hours.get("hrs") or []:
        minutes = _window_minutes(window)
        if minutes is not None:
            total += minutes
    if total <= 0:
        return _MINUTES_PER_DAY
    rndm = hours.get("rndm")
    if isinstance(rndm, (int, float)) and rndm:   # not 0 / None
        total += int(rndm)
    return total


def expected_file_count(aimpoint: dict) -> int:
    """Expected daily file count for an aimpoint.

    ``expected = operation_minutes // transcoderInterval``, where
    ``transcoderInterval`` is minutes-per-file (default 15) and
    ``operation_minutes`` is the summed ``hours.hrs`` window durations plus any
    ``hours.rndm``. With no ``hours``, 24-hour operation is assumed (so the
    default is ``1440 / 15 = 96`` files/day).
    """
    interval = _interval_minutes(aimpoint)
    operation = _operation_minutes(aimpoint)
    if interval <= 0 or operation <= 0:
        return 0
    return operation // interval


def _operating_intervals(aimpoint: dict) -> list[tuple[int, int]]:
    """The aimpoint's operating windows as ``[start, stop)`` minute-of-day ranges.

    No ``hours`` (or no parseable window) → a single 24-hour window. Overnight
    windows (``stop <= start``) are split into two same-day ranges so each range
    lies within ``[0, 1440)``.
    """
    hours = aimpoint.get("hours")
    if not isinstance(hours, dict) or not hours.get("hrs"):
        return [(0, _MINUTES_PER_DAY)]
    intervals: list[tuple[int, int]] = []
    for window in hours.get("hrs") or []:
        if not isinstance(window, str) or "-" not in window:
            continue
        start_s, stop_s = window.split("-", 1)
        start = _hhmm_to_minutes(start_s)
        stop = _hhmm_to_minutes(stop_s)
        if start is None or stop is None:
            continue
        if stop > start:
            intervals.append((start, stop))
        else:                                   # overnight / 0000-0000 → wraps
            intervals.append((start, _MINUTES_PER_DAY))
            intervals.append((0, stop))
    return intervals or [(0, _MINUTES_PER_DAY)]


def _now_minute_of_day(aimpoint: dict, now: datetime) -> int:
    """Minute-of-day of ``now`` in the aimpoint's ``hours.tz`` (UTC if absent)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    hours = aimpoint.get("hours")
    tzname = hours.get("tz") if isinstance(hours, dict) else None
    if tzname:
        try:
            from zoneinfo import ZoneInfo

            now = now.astimezone(ZoneInfo(str(tzname)))
        except Exception:  # noqa: BLE001 - unknown tz → fall back to the given offset
            pass
    return now.hour * 60 + now.minute


def expected_file_count_so_far(aimpoint: dict, now: Optional[datetime] = None) -> int:
    """Files that should have been delivered from the day's start up to ``now``.

    Like :func:`expected_file_count` but only counts the operating minutes that
    have already elapsed today (in the aimpoint's timezone), so the Current tab
    can compare against files delivered *so far*. ``rndm`` is not included (it is
    a random daily tail, not attributable to a specific minute). ``now`` defaults
    to the current UTC time.
    """
    interval = _interval_minutes(aimpoint)
    if interval <= 0:
        return 0
    now_min = _now_minute_of_day(aimpoint, now or datetime.now(timezone.utc))
    elapsed = 0
    for start, stop in _operating_intervals(aimpoint):
        lo, hi = max(start, 0), min(stop, now_min)
        if hi > lo:
            elapsed += hi - lo
    return elapsed // interval


# ── Feed log line parser ───────────────────────────────────────────────────

def parse_feed_line(line: str) -> Optional[dict]:
    """Extract the JSON payload from one feed log line.

    Handles two formats:

    Legacy (explicit fields)::

        <garbage prefix> {"domain_id": "...", "feed_id": "...", "device_id": "...", ...}

    Current dBoardData format::

        {"eventType": "dBoardData", "delivered": "<up>/<country>/<name>/<device>/<YYYY>/<MM>/<DD>/<file>"}

    For the current format the **domain** is the full three-segment key
    ``up/<country>/<name>`` (e.g. ``up/ru/powernet.com.ru``, ``up/bb/worldcam``)
    and the **device** is the segment just before the date. Most paths have a
    dedicated device folder (``up/ru/24oko/glazok1080/<date>/…`` → domain
    ``up/ru/24oko``, device ``glazok1080``); some go straight from the domain to
    the date with no device folder (``up/eg/makaniBeachClub/<date>/…`` → domain
    ``up/eg/makaniBeachClub``, device ``makaniBeachClub`` — the domain's last
    segment). The device's aimpoint is then ``dboard/aimpoints/<domain>/<device>.json``.

    Returns the parsed dict (augmented if needed) or ``None`` on failure.
    """
    if not line.strip():
        return None

    match = _JSON_RE.search(line)
    if not match:
        return None

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        logger.debug("JSON decode error", extra={"error": str(exc), "line": line[:120]})
        return None

    # Current format: derive identifiers from the delivered path. The domain is
    # the three-segment key ``up/<country>/<name>`` (parts[:3]); the device is the
    # segment just before the date (parts[date_start - 1]) — parts[3] when a
    # device folder is present (date_start == 4), or parts[2] (the domain's last
    # segment) when the path goes straight to the date (date_start == 3). Skip
    # lines whose date is shifted into the first three (domain) slots (date_start
    # < 3) or whose domain/device segment is empty, so date components and empty
    # directories are never ingested as domains/feeds.
    if data.get("eventType") == "dBoardData" and data.get("delivered"):
        parts = data["delivered"].split("/")
        date_start = _date_start_index(parts)
        if date_start is None or date_start < 3 or not all(parts[:3]) or not parts[date_start - 1]:
            logger.debug(
                "Skipping delivered path with missing/empty domain or device",
                extra={"delivered": data["delivered"]},
            )
            return None
        device = parts[date_start - 1]
        data["domain_id"]   = "/".join(parts[:3])
        data["domain_name"] = data["domain_id"]
        data["feed_id"]     = device
        data["device_id"]   = device

    required = ("domain_id", "feed_id", "device_id")
    if not all(data.get(k) for k in required):
        logger.debug("Feed line missing required fields", extra={"data_keys": list(data.keys())})
        return None

    return data


# ── Device file parser ─────────────────────────────────────────────────────

def _op_window_from_hours(data: dict) -> tuple[str, str]:
    """Derive the ``(op_start, op_end)`` clock times from the aimpoint's
    ``hours.hrs`` (``["HHMM-HHMM"]``), or ``("00:00", "00:00")`` (full day)."""
    hours = data.get("hours", {}) or {}
    hrs_list = hours.get("hrs", []) if isinstance(hours, dict) else []
    if hrs_list:
        parts = str(hrs_list[0]).split("-")          # e.g. "0900-1800"
        if len(parts) == 2 and len(parts[0]) >= 4 and len(parts[1]) >= 4:
            return f"{parts[0][:2]}:{parts[0][2:4]}", f"{parts[1][:2]}:{parts[1][2:4]}"
    return "00:00", "00:00"


def parse_device_json(content: str, device_id: str) -> Optional[DeviceTally]:
    """Parse an aimpoint JSON file and return a :class:`DeviceTally`.

    The full aimpoint structure (see ``aimpoint_structure.txt``) is preserved
    verbatim in ``aimpoint_json`` for display; only the op window (for the
    expected-file-count math) is derived here.

    Args:
        content:   Raw file content (UTF-8 string).
        device_id: The device name to use — the aimpoint file's **base name**
                   (its ``filenameBase``, e.g. ``tomsk21`` from ``tomsk21.json``).
                   The aimpoint's own ``deviceID`` field must NOT set the identity:
                   it is a short, folder-scoped id (``tomsk21.json`` carries
                   ``"deviceID": "21"``) that collides across domains and does not
                   match the name the delivery/enumeration paths resolve to. It is
                   still kept verbatim inside ``aimpoint_json`` for display.

    Returns:
        :class:`DeviceTally` or ``None`` on parse failure.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("Device JSON parse error", extra={"device_id": device_id, "error": str(exc)})
        return None
    if not isinstance(data, dict):
        return None

    op_start, op_end = _op_window_from_hours(data)
    return DeviceTally(
        device_id       = device_id,
        aimpoint_json   = json.dumps(data, separators=(",", ":")),
        health_status   = str(data.get("health_status", "yellow")).lower(),
        op_window_start = op_start,
        op_window_end   = op_end,
        files_expected  = expected_file_count(data),
    )


# ── Tally updater ──────────────────────────────────────────────────────────

def apply_feed_line_to_tally(
    data: dict,
    tally: DomainSetTally,
    device_tallies: dict[tuple[str, str], DeviceTally],
) -> None:
    """Merge one parsed feed-log record into the in-memory *tally*.

    Args:
        data:           Parsed JSON dict from :func:`parse_feed_line`.
        tally:          The live :class:`DomainSetTally` to update.
        device_tallies: Dict mapping ``(domain_id, device_id) → DeviceTally``
                        already fetched for this generator cycle. Keyed by the
                        pair because device ids are only unique within a domain.
    """
    domain_id   = str(data["domain_id"])
    delivered_device = str(data["device_id"])   # from the delivered path, e.g. "01"
    domain_name = str(data.get("domain_name", domain_id))

    delivered   = str(data.get("delivered", ""))
    folder, _, _, _ = extract_folder_and_date(delivered)
    folder = folder or ""

    domain_tally = tally.get_or_create_domain(domain_id, domain_name, folder)

    # The device/feed identity is the aimpoint file's base name (e.g. "tomsk01"),
    # resolved by the Generator when it read the aimpoint; fall back to the
    # delivered-path segment when no aimpoint was found.
    dev = device_tallies.get((domain_id, delivered_device))
    device_id = dev.device_id if dev is not None else delivered_device
    feed_id   = device_id

    # Attach device tally to domain (once per device_id per cycle).
    if device_id not in domain_tally.devices:
        if dev is None:
            # Device file unavailable — create a minimal placeholder whose
            # expected daily count assumes 24h operation at the default
            # transcoder interval (so "Files Expected" is populated, not 0).
            dev = DeviceTally(device_id=device_id)
            dev.files_expected = expected_file_count({})
        domain_tally.devices[device_id] = dev
        dev.files_actual += 1               # this cycle delivered one file
    else:
        domain_tally.devices[device_id].files_actual += 1

    dev_tally = domain_tally.devices.get(device_id)
    device_status = dev_tally.health_status if dev_tally else "yellow"

    observed_time = str(data.get("observed_time", ""))
    if observed_time > domain_tally.last_observed_time:
        domain_tally.last_observed_time = observed_time

    # File count for a feed = number of delivered files for that feed in the
    # day. The current dBoardData feed format carries no explicit "count" — each
    # delivered line *is* one file — so accumulate one per line. A legacy line
    # that carries an explicit "count" is treated as authoritative instead.
    existing = domain_tally.feeds.get(feed_id)
    prior_count = existing.count if existing else 0
    if "count" in data:
        feed_count = int(data.get("count", 0))
    else:
        feed_count = prior_count + 1

    # Feed status is derived from delivered vs. expected file counts
    # (status_from_count), not read from the feed line — the current dBoardData
    # format carries no "status" field. A legacy line with an explicit "status"
    # is honored as-is.
    if "status" in data:
        feed_status = str(data.get("status", "yellow")).lower()
    else:
        expected = dev_tally.files_expected if dev_tally else 0
        feed_status = status_from_count(feed_count, expected)

    domain_tally.feeds[feed_id] = FeedTally(
        feed_id       = feed_id,
        device_id     = device_id,
        domain_id     = domain_id,
        status        = feed_status,
        device_status = device_status,
        count         = feed_count,
        location      = str(data.get("location", "")),
        observed_time = observed_time,
        latitude      = float(data.get("latitude", 0.0)),
        longitude     = float(data.get("longitude", 0.0)),
        feed_type     = str(data.get("feed_type", "")),
        source_system = str(data.get("source_system", "")),
        delivered_path = delivered,
        folder        = folder,
    )
