from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import pytest

from domain_feed_health_dashboard.data_model import DeviceRecord
from domain_feed_health_dashboard.db.repository import Repository
from domain_feed_health_dashboard.db.schema import open_db
from domain_feed_health_dashboard.history_data import (
    DEFAULT_HISTORY_WINDOW_DAYS,
    MAX_HISTORY_WINDOW_DAYS,
    MIN_HISTORY_WINDOW_DAYS,
    _aimpoint_by_day,
    build_feed_history_pivot,
    build_history_domain_master,
    domain_feed_series,
    domain_ids_with_history,
    domain_trend_png,
    feed_count_timeseries,
    format_day_header,
    history_date_columns,
    status_cell_style,
    style_feed_history_pivot,
)


def _seed_day(
    conn: sqlite3.Connection,
    set_date: str,
    domain_id: str,
    feed_statuses: dict[str, str],
    device_files: dict[str, tuple[int, int]] | None = None,
) -> None:
    """Seed one completed day.

    ``device_files`` optionally maps ``feed_id -> (files_actual, files_expected)``
    to attach a device row to that feed; feeds without an entry get no device.
    """

    device_files = device_files or {}
    conn.execute(
        """
        INSERT INTO domain_sets
            (set_date, domain_id, domain_name, folder, domain_status,
             total_feeds, red_feeds, yellow_feeds, green_feeds,
             files_actual, files_expected, last_observed)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            set_date, domain_id, f"{domain_id}.example.net", "fe/fi/fo/fum", "green",
            len(feed_statuses), 0, 0, len(feed_statuses), 0, 0, f"{set_date}T00:00:00+00:00",
        ),
    )
    set_id = conn.execute(
        "SELECT set_id FROM domain_sets WHERE set_date=? AND domain_id=?", (set_date, domain_id),
    ).fetchone()["set_id"]

    for feed_id, status in feed_statuses.items():
        device_pk = None
        if feed_id in device_files:
            files_actual, files_expected = device_files[feed_id]
            conn.execute(
                """
                INSERT INTO devices
                    (set_id, device_id, health_status, op_window_start,
                     op_window_end, files_actual, files_expected)
                VALUES (?,?,?,?,?,?,?)
                """,
                (set_id, feed_id, status, "00:00", "00:00", files_actual, files_expected),
            )
            device_pk = conn.execute(
                "SELECT device_pk FROM devices WHERE set_id=? AND device_id=?", (set_id, feed_id),
            ).fetchone()["device_pk"]

        conn.execute(
            """
            INSERT INTO feeds
                (set_id, device_pk, feed_id, feed_status, device_status,
                 count, location, observed_time, latitude, longitude,
                 feed_type, source_system, delivered_path, folder)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                set_id, device_pk, feed_id, status, status,
                1, "Test City", f"{set_date}T00:00:00+00:00", 0.0, 0.0,
                "telemetry", "test", f"fe/fi/fo/fum/{feed_id}", "fe/fi/fo/fum",
            ),
        )

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
        (set_date, datetime.now(timezone.utc).isoformat(), 1, len(feed_statuses), 0),
    )
    conn.commit()


@pytest.fixture
def seeded_repository(tmp_path) -> Repository:
    db_path = tmp_path / "history_test.sqlite3"
    conn = open_db(db_path)
    # Cell color is a band of files_actual / files_expected (expected 96 = a
    # full 24h day): 96/96 = 100% green, 90/96 = 94% yellow, 50/96 = 52% red.
    _seed_day(
        conn, "2026-06-16", "DOMAIN-001", {"FEED-001": "green", "FEED-002": "red"},
        device_files={"FEED-001": (96, 96), "FEED-002": (50, 96)},
    )
    _seed_day(
        conn, "2026-06-17", "DOMAIN-001", {"FEED-001": "yellow"},
        device_files={"FEED-001": (90, 96)},
    )
    conn.close()
    return Repository(db_path)


def test_domain_ids_with_history_returns_latest_day_domains(seeded_repository):
    assert domain_ids_with_history(seeded_repository) == ["DOMAIN-001"]


def test_domain_ids_with_history_returns_empty_when_no_data(tmp_path):
    db_path = tmp_path / "empty.sqlite3"
    open_db(db_path).close()
    assert domain_ids_with_history(Repository(db_path)) == []


def test_build_feed_history_pivot_orders_newest_day_first(seeded_repository):
    pivot = build_feed_history_pivot(seeded_repository, "DOMAIN-001")
    assert history_date_columns(pivot) == ["2026-06-17", "2026-06-16"]
    assert list(pivot.columns) == [
        "feed_id", "2026-06-17", "2026-06-17__status", "2026-06-16", "2026-06-16__status",
    ]


def test_build_feed_history_pivot_reports_count_and_band_per_day(seeded_repository):
    pivot = build_feed_history_pivot(seeded_repository, "DOMAIN-001")
    row = pivot.set_index("feed_id").loc["FEED-001"]
    assert row["2026-06-17"] == 90            # device Files Actual
    assert row["2026-06-17__status"] == "yellow"   # 90/96 = 94%
    assert row["2026-06-16"] == 96
    assert row["2026-06-16__status"] == "green"    # 96/96 = 100%


def test_build_feed_history_pivot_colors_cell_by_orange_band(tmp_path):
    db_path = tmp_path / "device_counts.sqlite3"
    conn = open_db(db_path)
    _seed_day(
        conn, "2026-06-17", "DOMAIN-001", {"FEED-001": "green"},
        device_files={"FEED-001": (75, 96)},   # 78% → orange
    )
    conn.close()
    pivot = build_feed_history_pivot(Repository(db_path), "DOMAIN-001")
    row = pivot.set_index("feed_id").loc["FEED-001"]
    assert row["2026-06-17"] == 75            # device Files Actual, not the feed count
    assert row["2026-06-17__status"] == "orange"


def test_build_feed_history_pivot_marks_missing_day_as_none(seeded_repository):
    pivot = build_feed_history_pivot(seeded_repository, "DOMAIN-001")
    row = pivot.set_index("feed_id").loc["FEED-002"]
    assert row["2026-06-16"] == 50
    assert row["2026-06-16__status"] == "red"      # 50/96 = 52%
    assert pd.isna(row["2026-06-17"])


def test_build_feed_history_pivot_returns_empty_for_unknown_domain(seeded_repository):
    pivot = build_feed_history_pivot(seeded_repository, "DOMAIN-MISSING")
    assert history_date_columns(pivot) == ["2026-06-17", "2026-06-16"]
    assert pivot.empty


def test_status_cell_style_known_and_unknown_labels():
    assert "dc2626" in status_cell_style("red")
    assert "f97316" in status_cell_style("orange")
    assert "16a34a" in status_cell_style("green")
    assert status_cell_style(None) == ""


def test_style_feed_history_pivot_returns_a_styler(seeded_repository):
    pivot = build_feed_history_pivot(seeded_repository, "DOMAIN-001")
    styled = style_feed_history_pivot(pivot)
    assert hasattr(styled, "to_html")


def test_history_window_defaults_and_bounds():
    assert DEFAULT_HISTORY_WINDOW_DAYS == 30
    assert MIN_HISTORY_WINDOW_DAYS == 1
    assert MAX_HISTORY_WINDOW_DAYS == 31


def test_build_feed_history_pivot_honors_a_one_day_window(seeded_repository):
    pivot = build_feed_history_pivot(seeded_repository, "DOMAIN-001", max_days=1)
    assert history_date_columns(pivot) == ["2026-06-17"]


def test_build_feed_history_pivot_honors_max_window_of_thirty_one_days(seeded_repository):
    pivot = build_feed_history_pivot(seeded_repository, "DOMAIN-001", max_days=MAX_HISTORY_WINDOW_DAYS)
    assert history_date_columns(pivot) == ["2026-06-17", "2026-06-16"]


def test_format_day_header_short_label():
    assert format_day_header("2026-06-17") == "6/17"
    assert format_day_header("2026-12-03") == "12/3"


def test_build_history_domain_master_nests_feed_pivot_and_device(seeded_repository):
    master_df, date_headers = build_history_domain_master(seeded_repository)

    assert date_headers == [("2026-06-17", "6/17"), ("2026-06-16", "6/16")]
    assert len(master_df) == 1
    domain_row = master_df.iloc[0]
    assert domain_row["domain_id"] == "DOMAIN-001"
    assert domain_row["total_feeds"] == 2

    feed_rows = json.loads(domain_row["feed_rows_json"])
    by_feed = {row["feed_id"]: row for row in feed_rows}
    # Feed×day counts + bands, newest-first; missing day is None.
    assert by_feed["FEED-001"]["2026-06-17"] == 90
    assert by_feed["FEED-001"]["2026-06-17__status"] == "yellow"
    assert by_feed["FEED-001"]["2026-06-16__status"] == "green"
    assert by_feed["FEED-002"]["2026-06-16"] == 50
    assert by_feed["FEED-002"]["2026-06-16__status"] == "red"
    assert by_feed["FEED-002"]["2026-06-17"] is None

    # Each feed row carries its device's aimpoint rows for the second-level detail.
    device_rows = json.loads(by_feed["FEED-001"]["router_rows_json"])
    assert device_rows[0] == {"field": "Device ID", "value": "FEED-001"}


def test_domain_feed_series_is_per_feed_counts_newest_first():
    # One list per feed (feed_ids order), newest-first; absent day → 0.
    counts = {"FEED-001": {"2026-06-17": 90, "2026-06-16": 96}, "FEED-002": {"2026-06-16": 50}}
    series = domain_feed_series(counts, ["FEED-001", "FEED-002"], ["2026-06-17", "2026-06-16"])
    assert series == [[90, 96], [0, 50]]


def test_domain_trend_png_returns_png_data_uri():
    uri = domain_trend_png([[90, 146, 30], [10, 20, 5]])
    assert uri.startswith("data:image/png;base64,")
    assert len(uri) > 40  # non-trivial payload
    assert domain_trend_png([]) == ""


def test_history_master_trend_img_is_a_png_data_uri(seeded_repository):
    master_df, _ = build_history_domain_master(seeded_repository)
    assert master_df.iloc[0]["trend_img"].startswith("data:image/png;base64,")


def test_history_no_aimpoint_feed_is_gray_but_domain_keeps_real_band(tmp_path):
    db_path = tmp_path / "mixed.sqlite3"
    conn = open_db(db_path)
    # FEED-A has a device (green); FEED-NOAIM has no device at all (like rdtc15).
    _seed_day(
        conn, "2026-06-17", "DOMAIN-1", {"FEED-A": "green", "FEED-NOAIM": "green"},
        device_files={"FEED-A": (96, 96)},
    )
    conn.close()
    master, _ = build_history_domain_master(Repository(db_path))
    row = master.iloc[0]
    # A real feed exists → domain colored normally (gray never wins).
    assert row["domain_band"] == "green"
    feeds = {r["feed_id"]: r for r in json.loads(row["feed_rows_json"])}
    # No-aimpoint feed's day cell is gray ("none"), its count defaults to 0
    # (no aimpoint → no files), and it has no per-day aimpoint (any day click → placeholder).
    assert feeds["FEED-NOAIM"]["2026-06-17__status"] == "none"
    assert feeds["FEED-NOAIM"]["2026-06-17"] == 0
    assert json.loads(feeds["FEED-NOAIM"]["aimpoint_by_day_json"])["days"] == {}
    # The feed with a device keeps its real band.
    assert feeds["FEED-A"]["2026-06-17__status"] == "green"


def test_history_master_has_collection_region_and_proxy_from_aimpoint(tmp_path):
    db_path = tmp_path / "cr.sqlite3"
    conn = open_db(db_path)
    _seed_day(conn, "2026-06-19", "DOMAIN-001", {"FEED-001": "green"}, device_files={"FEED-001": (96, 96)})
    conn.close()
    live = DeviceRecord(
        device_id="FEED-001",
        aimpoint_json=json.dumps(
            {"deviceID": "FEED-001", "collRegions": ["United States (N. Virginia)"], "proxy": "px.host:8080"}
        ),
    )
    master, _ = build_history_domain_master(
        Repository(db_path), live_routers={("DOMAIN-001", "FEED-001"): (live,)}
    )
    row = master.iloc[0]
    assert row["coll_region"] == "United States (N. Virginia)"
    assert row["proxy"] == "px.host:8080"


def test_history_domain_all_no_aimpoint_is_gray(tmp_path):
    db_path = tmp_path / "allgray.sqlite3"
    conn = open_db(db_path)
    _seed_day(conn, "2026-06-17", "DOMAIN-1", {"FEED-X": "green"})  # no device at all
    conn.close()
    master, _ = build_history_domain_master(Repository(db_path))
    assert master.iloc[0]["domain_band"] == "none"


def test_aimpoint_by_day_maps_each_day_with_dedup_and_no_fallback():
    def dev(ct):
        return (DeviceRecord(device_id="D", aimpoint_json=json.dumps({"deviceID": "D", "collectionType": ct})),)
    routers_by_day = {
        "2026-06-17": dev("RTSP"),   # different aimpoint
        "2026-06-16": dev("M3U"),    # same as 06-15
        "2026-06-15": dev("M3U"),
        "2026-06-14": (),            # no aimpoint that day
    }
    result = _aimpoint_by_day(routers_by_day)
    # Only days that actually have an aimpoint are mapped (06-14 is absent → no fallback).
    assert set(result["days"]) == {"2026-06-15", "2026-06-16", "2026-06-17"}
    # 06-15 and 06-16 share one deduped variant; 06-17 is a different variant.
    assert result["days"]["2026-06-15"] == result["days"]["2026-06-16"]
    assert result["days"]["2026-06-17"] != result["days"]["2026-06-15"]
    assert len(result["variants"]) == 2
    assert result["variants"][result["days"]["2026-06-17"]][0] == {"field": "Device ID", "value": "D"}


def test_aimpoint_by_day_empty_when_no_stored_aimpoint():
    assert _aimpoint_by_day({"2026-06-17": ()}) == {"days": {}, "variants": []}


def test_history_domain_band_propagates_worst_cell_over_the_window(tmp_path):
    # Lowest color propagates up: a feed that delivers fully on most days but
    # under-delivers on one (50/96 = 52% → red) has a red cell, so the feed — and
    # the domain — is red whenever that day is in the window, even though the
    # average is high. Excluding the bad day (shorter window) makes it green.
    db_path = tmp_path / "window.sqlite3"
    conn = open_db(db_path)
    _seed_day(conn, "2026-06-10", "DOMAIN-001", {"FEED-001": "red"}, device_files={"FEED-001": (50, 96)})
    _seed_day(conn, "2026-06-18", "DOMAIN-001", {"FEED-001": "green"}, device_files={"FEED-001": (96, 96)})
    _seed_day(conn, "2026-06-19", "DOMAIN-001", {"FEED-001": "green"}, device_files={"FEED-001": (96, 96)})
    conn.close()
    repo = Repository(db_path)

    short_window, _ = build_history_domain_master(repo, max_days=2)
    wide_window, _ = build_history_domain_master(repo, max_days=3)
    assert short_window.iloc[0]["domain_band"] == "green"   # only green cells in window
    assert wide_window.iloc[0]["domain_band"] == "red"       # one red cell propagates up
    assert wide_window.iloc[0]["red_feeds"] == 1             # the feed itself counts as red


def test_history_zero_delivery_day_is_gray_not_red(tmp_path):
    # A day that delivered nothing is gray (nothing to assess) and, being
    # non-contributing, does not drag the domain to red.
    db_path = tmp_path / "zero.sqlite3"
    conn = open_db(db_path)
    _seed_day(conn, "2026-06-18", "DOMAIN-001", {"FEED-001": "red"}, device_files={"FEED-001": (0, 96)})
    _seed_day(conn, "2026-06-19", "DOMAIN-001", {"FEED-001": "green"}, device_files={"FEED-001": (96, 96)})
    conn.close()
    master, _ = build_history_domain_master(Repository(db_path), max_days=2)
    row = master.iloc[0]
    feed = json.loads(row["feed_rows_json"])[0]
    assert feed["2026-06-18"] == 0 and feed["2026-06-18__status"] == "none"   # gray
    assert feed["2026-06-19__status"] == "green"
    assert row["domain_band"] == "green"   # gray never wins the rollup


def test_history_device_detail_prefers_live_aimpoint(tmp_path):
    # Stored history device rows predate aimpoint capture (empty fields); the
    # most recent (live) aimpoint is used for the device detail instead.
    db_path = tmp_path / "live.sqlite3"
    conn = open_db(db_path)
    _seed_day(conn, "2026-06-19", "DOMAIN-001", {"FEED-001": "green"}, device_files={"FEED-001": (96, 96)})
    conn.close()

    def collection_type_of(master):
        rows = json.loads(json.loads(master.iloc[0]["feed_rows_json"])[0]["router_rows_json"])
        return {row["field"]: row["value"] for row in rows}.get("Collection Type")

    live = DeviceRecord(
        device_id="FEED-001",
        aimpoint_json=json.dumps({"deviceID": "FEED-001", "collectionType": "M3U"}),
    )
    with_live, _ = build_history_domain_master(
        Repository(db_path), live_routers={("DOMAIN-001", "FEED-001"): (live,)}
    )
    assert collection_type_of(with_live) == "M3U"

    # Without the override, the stored row has no aimpoint data.
    without_live, _ = build_history_domain_master(Repository(db_path))
    assert collection_type_of(without_live) is None


def test_feed_count_timeseries_long_form_oldest_first_with_zero_fill():
    feed_rows = [
        {"feed_id": "a", "2026-06-19": 96, "2026-06-18": 90},
        {"feed_id": "b", "2026-06-19": 50, "2026-06-18": None},
    ]
    ts = feed_count_timeseries(feed_rows, ["2026-06-19", "2026-06-18"])  # newest-first input
    assert list(ts.columns) == ["day", "feed", "count"]
    assert len(ts) == 4  # 2 feeds x 2 days
    # Oldest day first on the x-axis.
    assert list(ts["day"].unique()) == [pd.Timestamp("2026-06-18"), pd.Timestamp("2026-06-19")]

    def count(feed, day):
        sel = ts[(ts["feed"] == feed) & (ts["day"] == pd.Timestamp(day))]
        return int(sel["count"].iloc[0])

    assert count("a", "2026-06-19") == 96
    assert count("b", "2026-06-18") == 0  # missing day → 0


def test_build_history_domain_master_empty_when_no_history(tmp_path):
    db_path = tmp_path / "empty.sqlite3"
    open_db(db_path).close()
    master_df, date_headers = build_history_domain_master(Repository(db_path))
    assert master_df.empty
    assert date_headers == []
