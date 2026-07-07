"""SQLite schema for completed daily domain sets.

Tables
------
domain_sets
    One row per domain per completed UTC day.  Indexed on set_date and
    domain_id so 30-day history queries and domain lookups stay fast.

feeds
    One row per feed per completed UTC day.  FK → domain_sets and devices.

devices
    One row per device (aimpoint) per completed UTC day.  FK → domain_sets.
    Carries the aimpoint structure (see ``aimpoint_structure.txt``) plus the
    derived op-window clock times, device status, and file-count metrics.

snapshot_meta
    One row per completed push (one per UTC day).  Used to detect whether
    today's set has already been committed and for audit trails.

Retention
---------
Rows older than 30 days are pruned during each midnight push.  The purge
runs inside the same write transaction as the insert so the DB never holds
a partial state.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous   = NORMAL;
PRAGMA foreign_keys  = ON;
PRAGMA temp_store    = MEMORY;
PRAGMA cache_size    = -32000;

CREATE TABLE IF NOT EXISTS domain_sets (
    set_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    set_date        TEXT    NOT NULL,           -- "YYYY-MM-DD"
    domain_id       TEXT    NOT NULL,
    domain_name     TEXT    NOT NULL,
    folder          TEXT    NOT NULL,           -- "fe/fi/fo/fum"
    domain_status   TEXT    NOT NULL,           -- green | yellow | red
    total_feeds     INTEGER NOT NULL DEFAULT 0,
    red_feeds       INTEGER NOT NULL DEFAULT 0,
    yellow_feeds    INTEGER NOT NULL DEFAULT 0,
    green_feeds     INTEGER NOT NULL DEFAULT 0,
    files_actual    INTEGER NOT NULL DEFAULT 0,
    files_expected  INTEGER NOT NULL DEFAULT 0,
    last_observed   TEXT,
    UNIQUE (set_date, domain_id)
);

CREATE INDEX IF NOT EXISTS idx_ds_date      ON domain_sets (set_date);
CREATE INDEX IF NOT EXISTS idx_ds_domain    ON domain_sets (domain_id);
CREATE INDEX IF NOT EXISTS idx_ds_folder    ON domain_sets (folder);

CREATE TABLE IF NOT EXISTS devices (
    device_pk       INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id          INTEGER NOT NULL REFERENCES domain_sets (set_id)
                            ON DELETE CASCADE,
    device_id       TEXT    NOT NULL,               -- deviceID
    aimpoint_json   TEXT    DEFAULT '',             -- full raw aimpoint JSON
    health_status   TEXT    NOT NULL DEFAULT 'yellow',
    op_window_start TEXT    NOT NULL DEFAULT '00:00',  -- derived from hours.hrs
    op_window_end   TEXT    NOT NULL DEFAULT '00:00',
    files_actual    INTEGER NOT NULL DEFAULT 0,
    files_expected  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (set_id, device_id)
);

CREATE INDEX IF NOT EXISTS idx_dev_set      ON devices (set_id);
CREATE INDEX IF NOT EXISTS idx_dev_id       ON devices (device_id);

CREATE TABLE IF NOT EXISTS feeds (
    feed_pk         INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id          INTEGER NOT NULL REFERENCES domain_sets (set_id)
                            ON DELETE CASCADE,
    device_pk       INTEGER          REFERENCES devices (device_pk)
                            ON DELETE SET NULL,
    feed_id         TEXT    NOT NULL,
    feed_status     TEXT    NOT NULL DEFAULT 'yellow',
    device_status   TEXT    NOT NULL DEFAULT 'yellow',
    count           INTEGER NOT NULL DEFAULT 0,
    location        TEXT,
    observed_time   TEXT,
    latitude        REAL,
    longitude       REAL,
    feed_type       TEXT,
    source_system   TEXT,
    delivered_path  TEXT,
    folder          TEXT,
    UNIQUE (set_id, feed_id)
);

CREATE INDEX IF NOT EXISTS idx_feed_set     ON feeds (set_id);
CREATE INDEX IF NOT EXISTS idx_feed_dev     ON feeds (device_pk);

CREATE TABLE IF NOT EXISTS snapshot_meta (
    meta_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    set_date        TEXT    NOT NULL UNIQUE,    -- "YYYY-MM-DD"
    pushed_at       TEXT    NOT NULL,           -- ISO-8601 UTC timestamp
    domain_count    INTEGER NOT NULL DEFAULT 0,
    feed_count      INTEGER NOT NULL DEFAULT 0,
    device_count    INTEGER NOT NULL DEFAULT 0
);
"""


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database, apply schema, and return the
    connection.

    The connection uses ``row_factory = sqlite3.Row`` so all queries return
    dict-like rows.

    Args:
        db_path: Filesystem path to the ``.db`` file.

    Returns:
        Open :class:`sqlite3.Connection`.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _apply_schema(conn)
    return conn


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Execute DDL statements idempotently (CREATE IF NOT EXISTS)."""
    conn.executescript(_DDL)
    conn.commit()
