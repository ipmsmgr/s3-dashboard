"""Repository — SQLite read layer for the 30-day history dashboard view.

All queries are read-only.  The repository reconstructs :class:`DomainRecord`
objects from the three normalised tables so the existing dashboard UI code
(``ui.py``, ``status.py``, ``grid_config.py``) requires no changes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from domain_feed_health_dashboard.data_model import (
    DeviceRecord,
    DomainRecord,
    FeedRecord,
    Status,
)
from domain_feed_health_dashboard.db.schema import open_db
from domain_feed_health_dashboard.utils.logger import logger


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Repository:
    """Read-only access to the 30-day history stored in SQLite.

    Args:
        db_path: Path to the ``.db`` file created by the generator.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._conn = open_db(db_path)

    # ── Public API ─────────────────────────────────────────────────────────

    def get_history_domains(
        self,
        set_date: Optional[str] = None,
        days: int = 30,
    ) -> tuple[DomainRecord, ...]:
        """Return all domains for a completed UTC day.

        Args:
            set_date: ``"YYYY-MM-DD"`` string.  Defaults to yesterday
                      (the most recently completed day).
            days:     Not used for filtering here — the pruning in the
                      generator enforces the 30-day window at write time.

        Returns:
            Tuple of :class:`DomainRecord` objects with feeds and device
            metadata attached, ready for the dashboard UI.
        """
        if set_date is None:
            set_date = self._latest_completed_date()
        if set_date is None:
            return ()

        domain_rows = self._conn.execute(
            "SELECT * FROM domain_sets WHERE set_date = ? ORDER BY domain_name",
            (set_date,),
        ).fetchall()

        records: list[DomainRecord] = []
        for ds in domain_rows:
            feeds   = self._feeds_for_set(ds["set_id"])
            records.append(DomainRecord(
                domain_name        = ds["domain_name"],
                feeds              = feeds,
                last_observed_time = ds["last_observed"] or "",
                domain_id          = ds["domain_id"],
                folder             = ds["folder"],
            ))

        logger.info(
            "Repository loaded history",
            extra={"set_date": set_date, "domains": len(records)},
        )
        return tuple(records)

    def available_dates(self) -> list[str]:
        """Return all set_date values present in the DB, newest first."""
        rows = self._conn.execute(
            "SELECT set_date FROM snapshot_meta ORDER BY set_date DESC"
        ).fetchall()
        return [row["set_date"] for row in rows]

    def domain_set_summary(self, set_date: Optional[str] = None) -> list[dict]:
        """Return a lightweight summary list for the history date selector.

        Args:
            set_date: Optional filter.  If ``None``, all dates are returned.

        Returns:
            List of dicts with keys ``set_date``, ``domain_count``,
            ``feed_count``, ``device_count``, ``pushed_at``.
        """
        if set_date:
            rows = self._conn.execute(
                "SELECT * FROM snapshot_meta WHERE set_date = ?", (set_date,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM snapshot_meta ORDER BY set_date DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Private helpers ────────────────────────────────────────────────────

    def _latest_completed_date(self) -> Optional[str]:
        """Return the most recent set_date that has been pushed."""
        row = self._conn.execute(
            "SELECT set_date FROM snapshot_meta ORDER BY set_date DESC LIMIT 1"
        ).fetchone()
        return row["set_date"] if row else None

    def _feeds_for_set(self, set_id: int) -> tuple[FeedRecord, ...]:
        """Load all feeds (and their device) for one domain_set row."""
        rows = self._conn.execute(
            """
            SELECT f.*, d.device_id as dev_id, d.aimpoint_json, d.health_status,
                   d.op_window_start, d.op_window_end,
                   d.files_actual, d.files_expected
            FROM feeds f
            LEFT JOIN devices d ON f.device_pk = d.device_pk
            WHERE f.set_id = ?
            ORDER BY f.feed_id
            """,
            (set_id,),
        ).fetchall()

        feeds: list[FeedRecord] = []
        for row in rows:
            device: Optional[DeviceRecord] = None
            if row["dev_id"]:
                device = DeviceRecord(
                    device_id       = row["dev_id"],
                    aimpoint_json   = row["aimpoint_json"] or "",
                    health_status   = (row["health_status"] or "yellow"),  # type: ignore[arg-type]
                    op_window_start = row["op_window_start"] or "00:00",
                    op_window_end   = row["op_window_end"]   or "00:00",
                    files_actual    = row["files_actual"]    or 0,
                    files_expected  = row["files_expected"]  or 0,
                )

            feeds.append(FeedRecord(
                feed_id        = row["feed_id"],
                status         = (row["feed_status"] or "yellow"),   # type: ignore[arg-type]
                device_status  = (row["device_status"] or "yellow"), # type: ignore[arg-type]
                count          = row["count"]         or 0,
                location       = row["location"]      or "",
                observed_time  = row["observed_time"] or "",
                latitude       = row["latitude"]      or 0.0,
                longitude      = row["longitude"]     or 0.0,
                feed_type      = row["feed_type"]     or "",
                source_system  = row["source_system"] or "",
                delivered_path = row["delivered_path"] or "",
                folder         = row["folder"]         or "",
                routers        = (device,) if device else (),
            ))

        return tuple(feeds)
