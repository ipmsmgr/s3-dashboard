"""Generator — polls S3, maintains the in-memory tally, and pushes to SQLite.

Lifecycle
---------
1. On startup (or restart) the generator calls :func:`rebuild_tally` to
   replay all of today's files already in S3, reconstructing the in-memory
   :class:`DomainSetTally` from scratch.

2. Every 15 minutes :func:`run_cycle` polls ``feeds/`` and ``devices/``
   for new files, parses them, and merges the results into the tally.

3. At UTC midnight :func:`push_to_sqlite` commits the completed day's tally
   to SQLite, prunes rows older than 30 days, and resets the tally.

S3 key conventions
------------------
- Feed log:    ``feeds/YYYYMMDD_HHMM_feedlog.txt``
- Device file: ``devices/YYYYMMDD_HHMM_<device_id>.json``

The cycle timestamp is extracted from the filename; S3 ``LastModified``
metadata is not used for this purpose.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from domain_feed_health_dashboard.aws.scanner import S3Scanner
from domain_feed_health_dashboard.data_model import DeviceTally, DomainSetTally, FeedTally
from domain_feed_health_dashboard.db.schema import open_db
from domain_feed_health_dashboard.services.log_parser import (
    apply_feed_line_to_tally,
    extract_folder_and_date,
    parse_device_json,
    parse_feed_line,
)
from domain_feed_health_dashboard.status import (
    domain_status_from_feeds,
    feed_status_counts,
    status_from_count,
)
from domain_feed_health_dashboard.utils.logger import logger

# S3 configuration — names are placeholders; replace via environment or config.
S3_BUCKET      = "acb-highwaypatrol-coruscant"
FEED_PREFIX    = "dboard/deliveries/"
DEVICE_PREFIX  = "dboard/aimpoints/"
CYCLE_SECONDS  = 15 * 60           # 15 minutes
DB_RETENTION_DAYS = 30
# Concurrency for fetching aimpoint (device) files from S3. The per-aimpoint
# round-trip dominates load time, so fetch cache-misses in parallel.
DEVICE_FETCH_WORKERS = 16

# Filename patterns for timestamp extraction.
# _FEED_KEY_RE   = re.compile(r"feeds/(\d{8})_(\d{4})_feedlog\.txt$")
_FEED_KEY_RE   = re.compile(r".*deliveryData-(\d+)-(\d{4}-\d{2}-\d{2})-(\d{2}-\d{2}-\d{2})-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.txt$", re.IGNORECASE)
# _DEVICE_KEY_RE = re.compile(r"devices/(\d{8})_(\d{4})_(.+)\.json$")
_DEVICE_KEY_RE = re.compile(r"(.+)\.json$")


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Generator state ────────────────────────────────────────────────────────

class Generator:
    """Owns the in-memory tally and coordinates all ingest operations.

    Args:
        scanner:  Configured :class:`~aws.scanner.S3Scanner`.
        db_path:  Path to the SQLite database file.
    """

    def __init__(self, scanner: S3Scanner, db_path: str | Path) -> None:
        self.scanner  = scanner
        self.db_path  = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock    = threading.Lock()
        self._tally: DomainSetTally = DomainSetTally(set_date=_utc_today())
        # Track the lexicographically largest feed key seen so we only process
        # new files on each poll cycle.
        self._last_feed_key: str = ""
        # Cache of aimpoint file content keyed by S3 key. Aimpoints are stable
        # config that recurs across many feed files and backfill days, so each
        # is downloaded at most once per process (the S3 GET is the bottleneck).
        # An empty string caches a known-missing aimpoint so it is not retried.
        self._aimpoint_cache: dict[str, str] = {}
        # Cache of a domain's aimpoint folder → the actual aimpoint .json key,
        # discovered by listing (the file name need not match the device folder,
        # e.g. up/ru/vtomske/01/tomsk01.json). One list per domain per process.
        self._domain_aimpoint_cache: dict[str, dict[str, str]] = {}

    @property
    def tally(self) -> DomainSetTally:
        """Return the current in-memory tally (thread-safe read)."""
        with self._lock:
            return self._tally

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = open_db(self.db_path)
        return self._conn

    def clear_aimpoint_cache(self) -> None:
        """Drop cached aimpoint files so the next poll re-pulls their metadata.

        Aimpoint config is otherwise cached for the process lifetime; call this
        (e.g. from a manual "Refresh now") to pick up config changes.
        """
        self._aimpoint_cache.clear()
        self._domain_aimpoint_cache.clear()

    # ── Startup ───────────────────────────────────────────────────────────

    def rebuild_tally(self) -> None:
        """Replay all of today's S3 feed files to rebuild the in-memory tally.

        Called on startup / restart so no data is lost if the process dies
        mid-day.
        """
        today = _utc_today()

        logger.info("Rebuilding tally from S3", extra={"set_date": today})

        # List all feed files whose key contains today's date (group 2 = YYYY-MM-DD).
        all_feed_objects = self.scanner.list_prefix(S3_BUCKET, FEED_PREFIX)

        today_feeds = [
            obj for obj in all_feed_objects
            if (m := _FEED_KEY_RE.search(obj.key)) and m.group(2) == today
        ]

        with self._lock:
            self._tally = DomainSetTally(set_date=today)
            # Anchor to the latest key seen across all S3 objects so the first
            # run_cycle() poll only picks up files that arrive after this point.
            self._last_feed_key = max((o.key for o in all_feed_objects), default="")

        for obj in sorted(today_feeds, key=lambda o: o.key):
            self._process_feed_file(obj.key)

        with self._lock:
            self._add_aimpoint_only_devices(self._tally)

        logger.info(
            "Tally rebuilt",
            extra={"set_date": today, "feed_files": len(today_feeds),
                   "domains": len(self._tally.domains)},
        )

    # ── History backfill ─────────────────────────────────────────────────

    def backfill_history(self, days: int = DB_RETENTION_DAYS) -> None:
        """Backfill SQLite history for completed UTC days that have no snapshot yet.

        :class:`~domain_feed_health_dashboard.db.repository.Repository` only
        ever reads from SQLite, and SQLite is normally only written to once
        per day at the midnight rollover inside :func:`run_cycle`. On a
        fresh deployment that means the 30-day history view stays empty
        until 30 real days have elapsed. This replays each missing
        completed day's S3 feed files into a standalone tally and pushes it,
        so history is available immediately.

        Days that already have a ``snapshot_meta`` row are skipped, so
        repeated calls (e.g. on every process restart) only do work for new
        gap days.
        """
        today = _utc_today()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

        conn = self._db()
        already_done = {
            row["set_date"] for row in conn.execute("SELECT set_date FROM snapshot_meta").fetchall()
        }

        all_feed_objects = self.scanner.list_prefix(S3_BUCKET, FEED_PREFIX)
        objects_by_date: dict[str, list] = {}
        for obj in all_feed_objects:
            m = _FEED_KEY_RE.search(obj.key)
            if not m:
                continue
            set_date = m.group(2)
            if set_date == today or set_date < cutoff or set_date in already_done:
                continue
            objects_by_date.setdefault(set_date, []).append(obj)

        if not objects_by_date:
            logger.info("No history backfill needed", extra={"days": days})
            return

        for set_date, objects in sorted(objects_by_date.items()):
            tally = DomainSetTally(set_date=set_date)
            for obj in sorted(objects, key=lambda o: o.key):
                self._process_feed_file(obj.key, tally)
            self._add_aimpoint_only_devices(tally)
            self._push_tally_to_sqlite(tally)
            logger.info(
                "Backfilled history day",
                extra={"event": "history_backfilled", "set_date": set_date, "feed_files": len(objects)},
            )

    # ── Per-cycle poll ────────────────────────────────────────────────────

    def run_cycle(self) -> None:
        """Poll S3 for new files and merge them into the tally.

        Also handles the UTC midnight rollover: if the tally's set_date is
        yesterday, the completed set is pushed to SQLite and the tally resets.
        """
        today = _utc_today()

        # Midnight rollover — push yesterday's completed set.
        with self._lock:
            if self._tally.set_date != today:
                logger.info(
                    "UTC midnight rollover",
                    extra={"completed_date": self._tally.set_date, "new_date": today},
                )
                self._push_tally_to_sqlite(self._tally)
                self._tally = DomainSetTally(set_date=today)
                self._last_feed_key = ""
                # Re-pull aimpoints for the new day. They are cached for the
                # process lifetime, so without this every day would reuse the same
                # stale aimpoint; clearing here lets each day snapshot ITS aimpoint
                # (S3 keeps only the current, non-dated file), so genuine per-day
                # aimpoint history accumulates as the aimpoint changes over time.
                self._aimpoint_cache.clear()
                self._domain_aimpoint_cache.clear()

        # List new feed files since last poll.
        new_feeds = self.scanner.list_prefix(
            S3_BUCKET, FEED_PREFIX, after_key=self._last_feed_key
        )

        if not new_feeds:
            logger.info("No new feed files this cycle")
            return

        for obj in new_feeds:
            self._process_feed_file(obj.key)
            if obj.key > self._last_feed_key:
                self._last_feed_key = obj.key

        with self._lock:
            self._add_aimpoint_only_devices(self._tally)

        logger.info(
            "Cycle complete",
            extra={"event": "cycle_complete", "new_feed_files": len(new_feeds),
                   "domains": len(self._tally.domains)},
        )

    # ── Feed file processing ──────────────────────────────────────────────

    def _process_feed_file(self, feed_key: str, target_tally: Optional[DomainSetTally] = None) -> None:
        """Download, parse, and merge one feed log file into *target_tally*.

        Defaults to the live in-memory tally, guarded by the instance lock —
        the existing behavior used by :func:`rebuild_tally` / :func:`run_cycle`.
        :func:`backfill_history` passes a standalone tally for a historical
        day instead; that tally is never shared across threads and needs no
        locking.
        """
        m = _FEED_KEY_RE.search(feed_key)
        if not m:
            logger.debug("Skipping non-matching feed key", extra={"key": feed_key})
            return

        content = self.scanner.read_text_file(S3_BUCKET, feed_key)
        if not content:
            return

        # Collect (domain_id, device_id) → (delivered folder, delivered file name)
        # before parsing so we can batch-fetch each device's aimpoint. Keying by
        # device_id ALONE is wrong: device ids like "24" are not globally unique,
        # so up/ru/sharyaOnline/24 and up/ru/lanoptic/24 would collide. The file
        # name is needed because the aimpoint is named after the device's
        # filenameBase (sharya24.json ↔ sharya24_2026-...mp4), which need not
        # match the delivered folder segment ("24") — see aimpoint_structure.txt.
        device_info_map: dict[tuple[str, str], tuple[str, str]] = {}
        parsed_lines: list[dict] = []

        for line in content.splitlines():
            data = parse_feed_line(line)
            if data:
                parsed_lines.append(data)
                delivered = str(data.get("delivered", ""))
                folder, _, _, _ = extract_folder_and_date(delivered)
                if folder:
                    filename = delivered.rsplit("/", 1)[-1]
                    device_info_map[(str(data["domain_id"]), str(data["device_id"]))] = (folder, filename)

        # Fetch device files — one per unique (domain, device).
        device_tallies = self._fetch_device_files(device_info_map)

        if target_tally is None:
            with self._lock:
                for data in parsed_lines:
                    apply_feed_line_to_tally(data, self._tally, device_tallies)
        else:
            for data in parsed_lines:
                apply_feed_line_to_tally(data, target_tally, device_tallies)

        logger.info(
            "Processed feed file",
            extra={"event": "feed_file_processed", "key": feed_key,
                   "lines": len(parsed_lines), "devices": len(device_tallies)},
        )

    def _fetch_device_files(
        self,
        device_info_map: dict[tuple[str, str], tuple[str, str]],
    ) -> dict[tuple[str, str], DeviceTally]:
        """Fetch and parse aimpoint (device) JSON files for the given devices.

        A domain's aimpoints are discovered by listing ``{DEVICE_PREFIX}<domain_id>/``
        (see :meth:`_match_aimpoint`), and each aimpoint's **base name** becomes the
        device name — the aimpoint file name is the device's ``filenameBase`` and
        need not match the delivered folder segment (``up/ru/sharyaOnline/24/…``
        delivers ``sharya24_….mp4`` whose aimpoint is ``sharya24.json``).

        Keyed by ``(domain_id, delivered_device_id)`` — device ids are only unique
        within a domain. Each distinct S3 key is read at most once.

        Args:
            device_info_map: ``(domain_id, device_id) → (delivered folder, delivered file name)``
                             collected from the current feed file.

        Returns:
            Dict mapping ``(domain_id, delivered_device_id) → DeviceTally`` whose
            ``device_id`` is the aimpoint file's base name.
        """
        resolved: dict[tuple[str, str], str] = {}  # (dom, dev) → aimpoint s3 key
        for (domain_id, device_id), (folder, filename) in device_info_map.items():
            key = self._match_aimpoint(domain_id, folder, filename)
            if key:
                resolved[(domain_id, device_id)] = key

        self._cache_aimpoints(set(resolved.values()))

        result: dict[tuple[str, str], DeviceTally] = {}
        for (domain_id, device_id), key in resolved.items():
            content = self._aimpoint_cache.get(key, "")
            if content:
                # device_id = aimpoint base name (the device's filenameBase)
                tally = parse_device_json(content, self._aimpoint_basename(key))
                if tally:
                    result[(domain_id, device_id)] = tally
        return result

    @staticmethod
    def _aimpoint_basename(key: str) -> str:
        """``dboard/aimpoints/up/ru/sharyaOnline/24/sharya24.json`` → ``sharya24``."""
        return key.rsplit("/", 1)[-1][: -len(".json")]

    def _match_aimpoint(self, domain_id: str, folder: str, filename: str) -> str:
        """Return the aimpoint S3 key for a delivered device, or ``""``.

        The aimpoint's location is not assumed: a domain's aimpoints are listed
        once, then matched to the delivered device by

        1. an aimpoint sitting directly in the delivered device folder, else
        2. the aimpoint whose base name is the delivered file's base name —
           delivered files are ``<filenameBase>_<suffix>`` and the aimpoint is
           ``<filenameBase>.json`` (longest base name wins, so ``tomsk21`` beats
           ``tomsk2``).

        Matching on the base name (rather than the folder segment) is what keeps a
        device from appearing twice: the delivery and the aimpoint enumeration
        both resolve to the same name.
        """
        keys = self._aimpoint_keys_under(domain_id)
        if not keys:
            return ""

        in_folder = f"{DEVICE_PREFIX}{folder}/"
        for key in keys:
            if key.startswith(in_folder) and "/" not in key[len(in_folder):]:
                return key

        best = ""
        for key in keys:
            base = self._aimpoint_basename(key)
            if filename == base or filename.startswith(base + "_") or filename.startswith(base + "."):
                if not best or len(base) > len(self._aimpoint_basename(best)):
                    best = key
        return best

    def _cache_aimpoints(self, keys: set[str]) -> None:
        """Download any of *keys* not already cached, in parallel.

        The per-file S3 round-trip is the dominant cost, and a device recurs
        across many feed files / backfill days, so caching collapses those to one
        download. An empty string caches a known-missing file.
        """
        missing = {key for key in keys if key not in self._aimpoint_cache}
        if not missing:
            return

        def _read(key: str) -> tuple[str, str]:
            try:
                return key, self.scanner.read_text_file(S3_BUCKET, key)
            except Exception as exc:  # noqa: BLE001 - surfaced as a missing aimpoint
                logger.warning("Could not fetch device file", extra={"key": key, "error": str(exc)})
                return key, ""

        with ThreadPoolExecutor(max_workers=min(DEVICE_FETCH_WORKERS, len(missing))) as pool:
            for key, content in pool.map(_read, missing):
                self._aimpoint_cache[key] = content

    def _add_aimpoint_only_devices(self, tally: DomainSetTally) -> None:
        """Add devices that have an aimpoint but delivered no files this period.

        The pipeline is delivery-driven, so a configured device producing no files
        would otherwise be invisible — exactly the condition an operator needs to
        see (e.g. ``up/ru/vtomske`` has aimpoints for ``01/11/21/29`` but only
        ``21`` delivers). For each domain already in the tally, every aimpoint
        under ``{DEVICE_PREFIX}<domain_id>/`` that is not already a device becomes
        a device + feed with a **zero** delivered count.
        """
        for domain_tally in tally.domains.values():
            keys = self._aimpoint_keys_under(domain_tally.domain_id)
            if not keys:
                continue
            self._cache_aimpoints(set(keys))
            for key in keys:
                basename = self._aimpoint_basename(key)
                if basename in domain_tally.devices:
                    continue                       # already delivering
                content = self._aimpoint_cache.get(key, "")
                if not content:
                    continue
                dev = parse_device_json(content, basename)
                if dev is None:
                    continue
                domain_tally.devices[basename] = dev          # files_actual stays 0
                domain_tally.feeds[basename] = FeedTally(
                    feed_id=basename,
                    device_id=basename,
                    domain_id=domain_tally.domain_id,
                    status=status_from_count(0, dev.files_expected),
                    device_status=dev.health_status,
                    count=0,
                    folder=key.rsplit("/", 1)[0][len(DEVICE_PREFIX):],
                )

    def _aimpoint_keys_under(self, domain_id: str) -> list[str]:
        """Every aimpoint ``.json`` S3 key under a domain (listed once, cached).

        No assumption is made about layout: the aimpoints may sit in per-device
        folders (``up/ru/vtomske/01/tomsk01.json``) or flat under the domain —
        callers key them by base name, not by folder.
        """
        if domain_id in self._domain_aimpoint_cache:
            return self._domain_aimpoint_cache[domain_id]
        keys: list[str] = []
        prefix = f"{DEVICE_PREFIX}{domain_id}/"
        try:
            keys = [obj.key for obj in self.scanner.list_prefix(S3_BUCKET, prefix) if obj.key.endswith(".json")]
        except Exception as exc:  # noqa: BLE001 - listing is best-effort
            logger.warning("Could not list aimpoint folder", extra={"prefix": prefix, "error": str(exc)})
        self._domain_aimpoint_cache[domain_id] = keys
        return keys

    # ── Midnight push ─────────────────────────────────────────────────────

    def _push_tally_to_sqlite(self, tally: DomainSetTally) -> None:
        """Write a completed :class:`DomainSetTally` to SQLite and prune old rows.

        Everything runs inside a single transaction so the DB never holds a
        partial day's data.
        """
        if not tally.domains:
            logger.info("Nothing to push — tally is empty", extra={"set_date": tally.set_date})
            return

        conn = self._db()
        pushed_at = _utc_now_iso()
        domain_count = feed_count = device_count = 0

        try:
            conn.execute("BEGIN")

            for domain_tally in tally.domains.values():
                domain_records = tally.to_domain_records()
                # Grab this specific domain's DomainRecord for status rollup.
                matching = [
                    dr for dr in domain_records
                    if dr.domain_id == domain_tally.domain_id
                ]
                if not matching:
                    continue
                dr = matching[0]
                d_status = domain_status_from_feeds(dr.feeds)
                counts   = feed_status_counts(dr.feeds)

                conn.execute(
                    """
                    INSERT INTO domain_sets
                        (set_date, domain_id, domain_name, folder, domain_status,
                         total_feeds, red_feeds, yellow_feeds, green_feeds,
                         files_actual, files_expected, last_observed)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT (set_date, domain_id) DO UPDATE SET
                        domain_status  = excluded.domain_status,
                        total_feeds    = excluded.total_feeds,
                        red_feeds      = excluded.red_feeds,
                        yellow_feeds   = excluded.yellow_feeds,
                        green_feeds    = excluded.green_feeds,
                        files_actual   = excluded.files_actual,
                        files_expected = excluded.files_expected,
                        last_observed  = excluded.last_observed
                    """,
                    (
                        tally.set_date,
                        domain_tally.domain_id,
                        domain_tally.domain_name,
                        domain_tally.folder,
                        d_status,
                        len(domain_tally.feeds),
                        counts["red"],
                        counts["yellow"],
                        counts["green"],
                        domain_tally.total_files_actual(),
                        domain_tally.total_files_expected(),
                        domain_tally.last_observed_time,
                    ),
                )

                set_id = conn.execute(
                    "SELECT set_id FROM domain_sets WHERE set_date=? AND domain_id=?",
                    (tally.set_date, domain_tally.domain_id),
                ).fetchone()["set_id"]

                # Devices
                device_pk_map: dict[str, int] = {}
                for dev in domain_tally.devices.values():
                    conn.execute(
                        """
                        INSERT INTO devices
                            (set_id, device_id, aimpoint_json, health_status,
                             op_window_start, op_window_end, files_actual, files_expected)
                        VALUES (?,?,?,?,?,?,?,?)
                        ON CONFLICT (set_id, device_id) DO UPDATE SET
                            -- Per-day snapshot: freeze the aimpoint (and its
                            -- derived op window / expected count) once captured, so
                            -- a re-push/backfill never overwrites a day's historical
                            -- aimpoint. Fill it only if the stored one is empty.
                            aimpoint_json = CASE
                                WHEN devices.aimpoint_json IS NULL OR devices.aimpoint_json IN ('', '{}')
                                THEN excluded.aimpoint_json ELSE devices.aimpoint_json END,
                            op_window_start = CASE
                                WHEN devices.aimpoint_json IS NULL OR devices.aimpoint_json IN ('', '{}')
                                THEN excluded.op_window_start ELSE devices.op_window_start END,
                            op_window_end = CASE
                                WHEN devices.aimpoint_json IS NULL OR devices.aimpoint_json IN ('', '{}')
                                THEN excluded.op_window_end ELSE devices.op_window_end END,
                            files_expected = CASE
                                WHEN devices.aimpoint_json IS NULL OR devices.aimpoint_json IN ('', '{}')
                                THEN excluded.files_expected ELSE devices.files_expected END,
                            health_status  = excluded.health_status,
                            files_actual   = excluded.files_actual
                        """,
                        (
                            set_id, dev.device_id, dev.aimpoint_json, dev.health_status,
                            dev.op_window_start, dev.op_window_end,
                            dev.files_actual, dev.files_expected,
                        ),
                    )
                    pk = conn.execute(
                        "SELECT device_pk FROM devices WHERE set_id=? AND device_id=?",
                        (set_id, dev.device_id),
                    ).fetchone()["device_pk"]
                    device_pk_map[dev.device_id] = pk
                    device_count += 1

                # Feeds
                for ft in domain_tally.feeds.values():
                    dev_pk = device_pk_map.get(ft.device_id)
                    conn.execute(
                        """
                        INSERT INTO feeds
                            (set_id, device_pk, feed_id, feed_status, device_status,
                             count, location, observed_time, latitude, longitude,
                             feed_type, source_system, delivered_path, folder)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT (set_id, feed_id) DO UPDATE SET
                            feed_status   = excluded.feed_status,
                            device_status = excluded.device_status,
                            count         = excluded.count,
                            observed_time = excluded.observed_time
                        """,
                        (
                            set_id, dev_pk, ft.feed_id, ft.status, ft.device_status,
                            ft.count, ft.location, ft.observed_time,
                            ft.latitude, ft.longitude, ft.feed_type,
                            ft.source_system, ft.delivered_path, ft.folder,
                        ),
                    )
                    feed_count += 1

                domain_count += 1

            # Snapshot metadata
            conn.execute(
                """
                INSERT INTO snapshot_meta (set_date, pushed_at, domain_count, feed_count, device_count)
                VALUES (?,?,?,?,?)
                ON CONFLICT (set_date) DO UPDATE SET
                    pushed_at    = excluded.pushed_at,
                    domain_count = excluded.domain_count,
                    feed_count   = excluded.feed_count,
                    device_count = excluded.device_count
                """,
                (tally.set_date, pushed_at, domain_count, feed_count, device_count),
            )

            # Prune rows older than 30 days.
            conn.execute(
                "DELETE FROM domain_sets WHERE set_date < date('now', ?)",
                (f"-{DB_RETENTION_DAYS} days",),
            )

            conn.execute("COMMIT")
            logger.info(
                "Pushed tally to SQLite",
                extra={
                    "event": "tally_pushed",
                    "set_date": tally.set_date,
                    "domains": domain_count,
                    "feeds": feed_count,
                    "devices": device_count,
                },
            )

        except Exception as exc:
            conn.execute("ROLLBACK")
            logger.error(
                "Failed to push tally to SQLite",
                extra={"event": "tally_push_error", "set_date": tally.set_date,
                       "error": str(exc)},
            )
            raise

    # ── Scheduler loop ────────────────────────────────────────────────────

    def run_forever(self) -> None:
        """Block and run :func:`run_cycle` every :data:`CYCLE_SECONDS` seconds.

        Intended to be called in a background thread or as a standalone
        process.  Catches and logs all exceptions so a single bad cycle does
        not kill the loop.
        """
        logger.info("Generator starting", extra={"cycle_seconds": CYCLE_SECONDS})
        self.rebuild_tally()

        while True:
            start = _time.monotonic()
            try:
                self.run_cycle()
            except Exception as exc:
                logger.error("Cycle error", extra={"error": str(exc)})

            elapsed = _time.monotonic() - start
            sleep_for = max(0.0, CYCLE_SECONDS - elapsed)
            _time.sleep(sleep_for)
