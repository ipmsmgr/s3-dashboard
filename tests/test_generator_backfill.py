"""Tests for Generator.backfill_history() — no network calls, uses a FakeScanner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from domain_feed_health_dashboard.aws.scanner import S3Object
from domain_feed_health_dashboard.services.generator import Generator


@dataclass
class _FakeScanner:
    """Minimal in-memory stand-in for S3Scanner — no real S3 calls."""

    objects: list[S3Object]
    contents: dict[str, str]
    read_calls: list[str] = field(default_factory=list)

    def list_prefix(self, bucket, prefix, after_key=None):
        results = [obj for obj in self.objects if obj.key.startswith(prefix)]
        if after_key:
            results = [obj for obj in results if obj.key > after_key]
        return sorted(results, key=lambda obj: obj.key)

    def read_text_file(self, bucket, key):
        self.read_calls.append(key)
        return self.contents.get(key, "")


def _date_str(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _feed_key(date_str: str, hour: str = "14") -> str:
    return (
        f"dboard/deliveries/{date_str.replace('-', '/')}/{hour}/"
        f"deliveryData-2-{date_str}-{hour}-15-41-3e769071-8cd3-4edc-a9a5-d684358ade1e.txt"
    )


def _feed_line(domain_id: str, feed_id: str, device_id: str, status: str, date_str: str) -> str:
    return json.dumps(
        {
            "domain_id": domain_id,
            "feed_id": feed_id,
            "device_id": device_id,
            "status": status,
            "count": 1,
            "location": "Test City",
            "observed_time": f"{date_str}T14:15:00+00:00",
            "latitude": 0.0,
            "longitude": 0.0,
            "feed_type": "telemetry",
            "source_system": "test",
            "delivered": f"fe/fi/fo/fum/{device_id}/{date_str.replace('-', '/')}/{device_id}.mp4",
        }
    )


def _make_scanner_with_days(*days_ago: int) -> _FakeScanner:
    objects: list[S3Object] = []
    contents: dict[str, str] = {}
    for n in days_ago:
        date_str = _date_str(n)
        key = _feed_key(date_str)
        objects.append(S3Object(key=key, size=10, last_modified=datetime.now()))
        contents[key] = _feed_line("DOMAIN-001", "FEED-001", "DEV-001", "green", date_str)
    return _FakeScanner(objects=objects, contents=contents)


def test_backfill_history_skips_today(tmp_path):
    scanner = _make_scanner_with_days(0, 1, 2)
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")

    generator.backfill_history(days=30)

    conn = generator._db()
    dates = {row["set_date"] for row in conn.execute("SELECT set_date FROM snapshot_meta").fetchall()}
    assert dates == {_date_str(1), _date_str(2)}


def test_backfill_history_writes_domain_and_feed_rows(tmp_path):
    scanner = _make_scanner_with_days(1)
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")

    generator.backfill_history(days=30)

    conn = generator._db()
    set_date = _date_str(1)
    domain_row = conn.execute(
        "SELECT * FROM domain_sets WHERE set_date=? AND domain_id=?", (set_date, "DOMAIN-001")
    ).fetchone()
    assert domain_row is not None
    assert domain_row["total_feeds"] == 1

    feed_row = conn.execute("SELECT * FROM feeds WHERE set_id=?", (domain_row["set_id"],)).fetchone()
    assert feed_row["feed_id"] == "FEED-001"
    assert feed_row["feed_status"] == "green"


def test_backfill_history_is_idempotent_and_skips_already_done_days(tmp_path):
    scanner = _make_scanner_with_days(1, 2)
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")

    generator.backfill_history(days=30)
    first_read_count = len(scanner.read_calls)
    assert first_read_count > 0

    generator.backfill_history(days=30)
    assert len(scanner.read_calls) == first_read_count

    conn = generator._db()
    count = conn.execute("SELECT COUNT(*) FROM domain_sets").fetchone()[0]
    assert count == 2


def test_backfill_populates_device_fields_from_aimpoint_file(tmp_path):
    # Aimpoint files live at the delivered-path prefix under the aimpoints root:
    # delivered "fe/fi/fo/fum/DEV-001/<date>/DEV-001.mp4" → folder
    # "fe/fi/fo/fum/DEV-001" → aimpoint dboard/aimpoints/fe/fi/fo/fum/DEV-001/DEV-001.json
    date_str = _date_str(1)
    feed_key = _feed_key(date_str)
    aimpoint_key = "dboard/aimpoints/fe/fi/fo/fum/DEV-001/DEV-001.json"
    aimpoint = {
        "deviceID": "DEV-001",
        "collEnabled": True,
        "collectionType": "M3U",
        "collRegions": ["United States (N. Virginia)"],
        "hours": {"tz": "US/Eastern", "hrs": ["0900-1800"]},
        "dstBucket": "thorium-ch-prod",
    }
    contents = {
        feed_key: _feed_line("DOMAIN-001", "FEED-001", "DEV-001", "green", date_str),
        aimpoint_key: json.dumps(aimpoint),
    }
    scanner = _FakeScanner(
        objects=[S3Object(key=feed_key, size=10, last_modified=datetime.now())],
        contents=contents,
    )
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")

    generator.backfill_history(days=30)

    assert aimpoint_key in scanner.read_calls  # the folder-based path was fetched
    device_row = generator._db().execute(
        "SELECT * FROM devices WHERE device_id=?", ("DEV-001",)
    ).fetchone()
    # The full aimpoint structure is stored verbatim; op window derived from hours.
    assert json.loads(device_row["aimpoint_json"]) == aimpoint
    assert (device_row["op_window_start"], device_row["op_window_end"]) == ("09:00", "18:00")
    assert device_row["files_expected"] == 36


def test_aimpoint_files_are_fetched_once_and_cached(tmp_path):
    # The same device recurs across many feed files / backfill days; its
    # aimpoint must be downloaded once, not per occurrence (the S3 GET is the
    # load-time bottleneck).
    aimpoint_key = "dboard/aimpoints/fe/fi/fo/fum/DEV-001/DEV-001.json"
    objects: list[S3Object] = []
    contents: dict[str, str] = {
        aimpoint_key: json.dumps({"deviceID": "DEV-001", "hpID": "HP1", "collectionType": "M3U"})
    }
    for n in (1, 2, 3):
        date_str = _date_str(n)
        feed_key = _feed_key(date_str)
        objects.append(S3Object(key=feed_key, size=10, last_modified=datetime.now()))
        contents[feed_key] = _feed_line("DOMAIN-001", "FEED-001", "DEV-001", "green", date_str)
    scanner = _FakeScanner(objects=objects, contents=contents)
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")

    generator.backfill_history(days=30)

    assert scanner.read_calls.count(aimpoint_key) == 1


def test_backfill_history_respects_days_cutoff(tmp_path):
    scanner = _make_scanner_with_days(1, 40)
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")

    generator.backfill_history(days=30)

    conn = generator._db()
    dates = {row["set_date"] for row in conn.execute("SELECT set_date FROM snapshot_meta").fetchall()}
    assert dates == {_date_str(1)}
