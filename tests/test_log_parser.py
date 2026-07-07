import json

from domain_feed_health_dashboard.services.log_parser import (
    expected_file_count,
    parse_device_json,
)


def test_expected_file_count_no_hours_is_full_day():
    # No hours → 24h operation; default transcoderInterval 15 → 1440/15 = 96.
    assert expected_file_count({}) == 96
    assert expected_file_count({"deviceID": "d"}) == 96


def test_expected_file_count_uses_hours_window():
    assert expected_file_count({"hours": {"hrs": ["0900-1800"]}}) == 36   # 9h / 15min
    assert expected_file_count({"hours": {"hrs": ["0600-2200"]}}) == 64   # 16h / 15min


def test_expected_file_count_overnight_and_full_day_windows_wrap():
    assert expected_file_count({"hours": {"hrs": ["2200-0600"]}}) == 32   # 8h overnight
    assert expected_file_count({"hours": {"hrs": ["0000-0000"]}}) == 96   # full day


def test_expected_file_count_sums_multiple_windows():
    # Two 4h windows → 8h → 8*60/15 = 32.
    assert expected_file_count({"hours": {"hrs": ["0000-0400", "1200-1600"]}}) == 32


def test_expected_file_count_uses_transcoder_interval():
    # 24h at a 30-minute interval → 1440/30 = 48.
    assert expected_file_count({"transcoderInterval": 30}) == 48
    # Invalid / non-positive interval falls back to the default (15).
    assert expected_file_count({"transcoderInterval": 0}) == 96
    assert expected_file_count({"transcoderInterval": "x"}) == 96


def test_expected_file_count_adds_rndm_minutes():
    # 9h window (540 min) + 60 rndm = 600 / 15 = 40.
    assert expected_file_count({"hours": {"hrs": ["0900-1800"], "rndm": 60}}) == 40
    # rndm of 0 / absent adds nothing.
    assert expected_file_count({"hours": {"hrs": ["0900-1800"], "rndm": 0}}) == 36


def test_parse_device_json_preserves_full_structure_and_derives_op_window():
    aimpoint = {
        "deviceID": "glazok1080",
        "collectionType": "M3U",
        "collEnabled": False,
        "hours": {"tz": "US/Eastern", "hrs": ["0900-1800"]},
        "monitoringData": {"lastMonitoredIsoDate": "2025-12-16T20:39:05+00:00"},
    }
    tally = parse_device_json(json.dumps(aimpoint), "glazok1080")
    assert tally.device_id == "glazok1080"
    # Full structure preserved verbatim for display.
    assert json.loads(tally.aimpoint_json) == aimpoint
    # Op window derived from hours.hrs → expected count.
    assert (tally.op_window_start, tally.op_window_end) == ("09:00", "18:00")
    assert tally.files_expected == 36


def test_parse_device_json_full_day_when_no_hours():
    tally = parse_device_json(json.dumps({"deviceID": "d"}), "d")
    assert (tally.op_window_start, tally.op_window_end) == ("00:00", "00:00")
    assert tally.files_expected == 96
    assert json.loads(tally.aimpoint_json) == {"deviceID": "d"}


def test_parse_device_json_rejects_non_object():
    assert parse_device_json(json.dumps([1, 2, 3]), "d") is None
    assert parse_device_json("not json", "d") is None
