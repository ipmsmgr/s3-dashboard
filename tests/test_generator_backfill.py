"""Tests for Generator.backfill_history() — no network calls, uses a FakeScanner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from domain_feed_health_dashboard.aws.scanner import S3Object
from domain_feed_health_dashboard.data_model import DeviceTally, DomainSetTally, DomainTally, FeedTally
from domain_feed_health_dashboard.services.generator import Generator


def _day_tally(set_date: str, aimpoint_json: str, files_actual: int) -> DomainSetTally:
    """A one-domain/one-device DomainSetTally for exercising the midnight push."""
    dt = DomainTally(domain_id="up/ru/x", domain_name="up/ru/x", folder="up/ru/x/24")
    dt.devices["24"] = DeviceTally(
        device_id="24", aimpoint_json=aimpoint_json, files_actual=files_actual, files_expected=96
    )
    dt.feeds["24"] = FeedTally(feed_id="24", device_id="24", domain_id="up/ru/x", count=files_actual)
    st = DomainSetTally(set_date=set_date)
    st.domains["up/ru/x"] = dt
    return st


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


def _obj(key: str) -> S3Object:
    return S3Object(key=key, size=10, last_modified=datetime.now())


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
    # feed_id == device_id (the feed IS the device); no aimpoint here → the
    # delivered-path device segment is used.
    assert feed_row["feed_id"] == "DEV-001"
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
    # Aimpoints are discovered by listing the domain's tree; delivered
    # "up/ru/testdom/DEV-001/<date>/DEV-001_x.mp4" resolves to
    # dboard/aimpoints/up/ru/testdom/DEV-001/DEV-001.json
    date_str = _date_str(1)
    feed_key = _feed_key(date_str)
    d = date_str.replace("-", "/")
    aimpoint_key = "dboard/aimpoints/up/ru/testdom/DEV-001/DEV-001.json"
    aimpoint = {
        "deviceID": "DEV-001",
        "collEnabled": True,
        "collectionType": "M3U",
        "collRegions": ["United States (N. Virginia)"],
        "hours": {"tz": "US/Eastern", "hrs": ["0900-1800"]},
        "dstBucket": "thorium-ch-prod",
    }
    contents = {
        feed_key: _dboard_line(f"up/ru/testdom/DEV-001/{d}/DEV-001_x.mp4"),
        aimpoint_key: json.dumps(aimpoint),
    }
    scanner = _FakeScanner(
        objects=[_obj(feed_key), _obj(aimpoint_key)],  # aimpoint listable in its folder
        contents=contents,
    )
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")

    generator.backfill_history(days=30)

    assert aimpoint_key in scanner.read_calls  # discovered by listing, then fetched
    device_row = generator._db().execute(
        "SELECT * FROM devices WHERE device_id=?", ("DEV-001",)
    ).fetchone()
    # The full aimpoint structure is stored verbatim; op window derived from hours.
    assert json.loads(device_row["aimpoint_json"]) == aimpoint
    assert (device_row["op_window_start"], device_row["op_window_end"]) == ("09:00", "18:00")
    assert device_row["files_expected"] == 36


def _dboard_line(delivered: str) -> str:
    return json.dumps({"eventType": "dBoardData", "delivered": delivered})


def test_same_device_id_in_two_domains_gets_its_own_aimpoint(tmp_path):
    # Device ids like "24" are only unique within a domain. up/ru/sharyaOnline/24
    # and up/ru/lanoptic/24 must NOT collide — each keeps its own aimpoint.
    date_str = _date_str(1)
    feed_key = _feed_key(date_str)
    d = date_str.replace("-", "/")
    sh_aim = "dboard/aimpoints/up/ru/sharyaOnline/24/24.json"
    la_aim = "dboard/aimpoints/up/ru/lanoptic/24/24.json"
    contents = {
        feed_key: "\n".join([
            _dboard_line(f"up/ru/sharyaOnline/24/{d}/24_x.mp4"),
            _dboard_line(f"up/ru/lanoptic/24/{d}/24_x.mp4"),
        ]),
        sh_aim: json.dumps({"deviceID": "24", "deliveryKey": "up/ru/sharyaOnline/24"}),
        la_aim: json.dumps({"deviceID": "24", "deliveryKey": "up/ru/lanoptic/24"}),
    }
    scanner = _FakeScanner(objects=[_obj(feed_key), _obj(sh_aim), _obj(la_aim)], contents=contents)
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")
    generator.backfill_history(days=30)

    # Both domains' aimpoints were fetched (no collision → no folder was dropped).
    assert sh_aim in scanner.read_calls
    assert la_aim in scanner.read_calls
    # Each domain's device 24 stored its OWN aimpoint (correct deliveryKey).
    rows = generator._db().execute(
        "SELECT ds.domain_id AS domain_id, d.aimpoint_json AS aimpoint_json "
        "FROM devices d JOIN domain_sets ds ON ds.set_id = d.set_id WHERE d.device_id = '24'"
    ).fetchall()
    by_domain = {r["domain_id"]: json.loads(r["aimpoint_json"])["deliveryKey"] for r in rows}
    assert by_domain == {
        "up/ru/sharyaOnline": "up/ru/sharyaOnline/24",
        "up/ru/lanoptic": "up/ru/lanoptic/24",
    }


def test_device_aimpoint_is_frozen_once_written_but_counts_refresh(tmp_path):
    # Per-day snapshot: a day's aimpoint is captured once and NOT overwritten by a
    # later push (delivery counts still refresh).
    day = _date_str(1)
    gen = Generator(scanner=_FakeScanner([], {}), db_path=tmp_path / "t.sqlite3")
    gen._push_tally_to_sqlite(_day_tally(day, '{"deviceID":"24","deliveryKey":"A"}', 10))
    gen._push_tally_to_sqlite(_day_tally(day, '{"deviceID":"24","deliveryKey":"B"}', 25))
    row = gen._db().execute("SELECT aimpoint_json, files_actual FROM devices WHERE device_id='24'").fetchone()
    assert json.loads(row["aimpoint_json"])["deliveryKey"] == "A"   # frozen snapshot
    assert row["files_actual"] == 25                                # counts still update


def test_device_aimpoint_is_filled_when_first_write_was_empty(tmp_path):
    # If a day was first written with no aimpoint (fetch miss), a later push fills it.
    day = _date_str(1)
    gen = Generator(scanner=_FakeScanner([], {}), db_path=tmp_path / "t.sqlite3")
    gen._push_tally_to_sqlite(_day_tally(day, "", 5))
    gen._push_tally_to_sqlite(_day_tally(day, '{"deviceID":"24","deliveryKey":"A"}', 5))
    row = gen._db().execute("SELECT aimpoint_json FROM devices WHERE device_id='24'").fetchone()
    assert json.loads(row["aimpoint_json"])["deliveryKey"] == "A"


def test_midnight_rollover_repulls_aimpoints_for_the_new_day(tmp_path):
    # On rollover the aimpoint cache is cleared so the new day re-pulls (and thus
    # snapshots) its own aimpoint instead of reusing the process-cached one.
    gen = Generator(scanner=_FakeScanner([], {}), db_path=tmp_path / "t.sqlite3")
    gen._tally = DomainSetTally(set_date="2020-01-01")   # not today → triggers rollover
    gen._aimpoint_cache["dboard/aimpoints/up/ru/x/24/24.json"] = '{"deviceID":"24"}'
    gen.run_cycle()
    assert gen._aimpoint_cache == {}


def test_aimpoint_filename_differs_from_device_folder_uses_basename(tmp_path):
    # up/ru/vtomske/01 contains tomsk01.json (name != folder). The aimpoint is
    # discovered by listing, and its base name "tomsk01" becomes the device name.
    date_str = _date_str(1)
    feed_key = _feed_key(date_str)
    d = date_str.replace("-", "/")
    aim_key = "dboard/aimpoints/up/ru/vtomske/01/tomsk01.json"
    contents = {
        feed_key: _dboard_line(f"up/ru/vtomske/01/{d}/x.mp4"),
        # NOTE: the aimpoint's own "deviceID" is the short folder id ("01") — the
        # file's base name wins, so the device is "tomsk01", not "01".
        aim_key: json.dumps({"deviceID": "01", "deliveryKey": "up/ru/vtomske/01"}),
    }
    scanner = _FakeScanner(objects=[_obj(feed_key), _obj(aim_key)], contents=contents)
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")
    generator.backfill_history(days=30)

    assert aim_key in scanner.read_calls
    row = generator._db().execute(
        "SELECT d.device_id AS device_id, f.feed_id AS feed_id, d.aimpoint_json AS aim "
        "FROM devices d JOIN feeds f ON f.device_pk = d.device_pk "
        "JOIN domain_sets ds ON ds.set_id = d.set_id WHERE ds.domain_id = 'up/ru/vtomske'"
    ).fetchone()
    assert row["device_id"] == "tomsk01"          # base name, not the folder "01"
    assert row["feed_id"] == "tomsk01"            # feed shows the same device name
    assert json.loads(row["aim"])["deliveryKey"] == "up/ru/vtomske/01"


def test_delivery_links_to_aimpoint_by_filename_base_no_duplicate_device(tmp_path):
    # up/ru/sharyaOnline/24 delivers sharya24_*.mp4; its aimpoint is sharya24.json
    # (name != folder segment "24"). The delivery must resolve to sharya24 — NOT
    # create a separate "24" device alongside the enumerated sharya24.
    date_str = _date_str(1)
    feed_key = _feed_key(date_str)
    d = date_str.replace("-", "/")
    # aimpoints sit flat under the domain (not inside the numbered folder), and
    # each carries a short folder-scoped "deviceID" that must NOT become the name
    aims = {
        "dboard/aimpoints/up/ru/sharyaOnline/sharya24.json": {"deviceID": "24"},
        "dboard/aimpoints/up/ru/sharyaOnline/sharya29.json": {"deviceID": "29"},
    }
    contents = {feed_key: _dboard_line(f"up/ru/sharyaOnline/24/{d}/sharya24_2026-07-08-23-15-00.mp4")}
    contents.update({k: json.dumps(v) for k, v in aims.items()})
    scanner = _FakeScanner(objects=[_obj(feed_key), *(_obj(k) for k in aims)], contents=contents)
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")
    generator.backfill_history(days=30)

    rows = generator._db().execute(
        "SELECT f.feed_id AS feed_id, f.count AS count FROM feeds f "
        "JOIN domain_sets ds ON ds.set_id = f.set_id WHERE ds.domain_id = 'up/ru/sharyaOnline'"
    ).fetchall()
    by_feed = {r["feed_id"]: r["count"] for r in rows}
    assert set(by_feed) == {"sharya24", "sharya29"}   # no stray "24"
    assert by_feed["sharya24"] == 1                   # the delivery landed on it
    assert by_feed["sharya29"] == 0                   # configured, not delivering


def test_configured_devices_without_deliveries_still_appear(tmp_path):
    # up/ru/vtomske has aimpoints for 01/11/21, but only 21 delivers files. All
    # three must appear; the non-delivering ones get a zero delivered count.
    date_str = _date_str(1)
    feed_key = _feed_key(date_str)
    d = date_str.replace("-", "/")
    # each aimpoint's "deviceID" is the short folder id; the file base name wins
    aims = {
        "dboard/aimpoints/up/ru/vtomske/01/tomsk01.json": {"deviceID": "01"},
        "dboard/aimpoints/up/ru/vtomske/11/tomsk11.json": {"deviceID": "11"},
        "dboard/aimpoints/up/ru/vtomske/21/tomsk21.json": {"deviceID": "21"},
    }
    contents = {feed_key: _dboard_line(f"up/ru/vtomske/21/{d}/tomsk21_x.mp4")}
    contents.update({k: json.dumps(v) for k, v in aims.items()})
    scanner = _FakeScanner(objects=[_obj(feed_key), *(_obj(k) for k in aims)], contents=contents)
    generator = Generator(scanner=scanner, db_path=tmp_path / "test.sqlite3")
    generator.backfill_history(days=30)

    rows = generator._db().execute(
        "SELECT f.feed_id AS feed_id, f.count AS count FROM feeds f "
        "JOIN domain_sets ds ON ds.set_id = f.set_id WHERE ds.domain_id = 'up/ru/vtomske'"
    ).fetchall()
    by_feed = {r["feed_id"]: r["count"] for r in rows}
    assert set(by_feed) == {"tomsk01", "tomsk11", "tomsk21"}   # all configured devices show
    assert by_feed["tomsk21"] == 1                              # the delivering one
    assert by_feed["tomsk01"] == 0 and by_feed["tomsk11"] == 0  # configured but not delivering


def test_aimpoint_files_are_fetched_once_and_cached(tmp_path):
    # The same device recurs across many feed files / backfill days; its
    # aimpoint must be downloaded once, not per occurrence (the S3 GET is the
    # load-time bottleneck).
    aimpoint_key = "dboard/aimpoints/up/ru/testdom/DEV-001/DEV-001.json"
    objects: list[S3Object] = [_obj(aimpoint_key)]  # listable + readable
    contents: dict[str, str] = {
        aimpoint_key: json.dumps({"deviceID": "DEV-001", "hpID": "HP1", "collectionType": "M3U"})
    }
    for n in (1, 2, 3):
        date_str = _date_str(n)
        feed_key = _feed_key(date_str)
        objects.append(_obj(feed_key))
        contents[feed_key] = _dboard_line(f"up/ru/testdom/DEV-001/{date_str.replace('-', '/')}/DEV-001_x.mp4")
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
