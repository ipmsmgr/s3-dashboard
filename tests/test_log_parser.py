import json
from datetime import datetime, timezone

from domain_feed_health_dashboard.services.log_parser import (
    expected_file_count,
    expected_file_count_so_far,
    extract_folder_and_date,
    parse_device_json,
    parse_feed_line,
)


def _delivered(path: str) -> dict:
    return json.dumps({"eventType": "dBoardData", "delivered": path})


def test_parse_feed_line_domain_is_full_three_segment_path_with_device_folder():
    # up/ru/24oko/glazok1080/<date>/… → domain "up/ru/24oko", device "glazok1080".
    data = parse_feed_line(_delivered("up/ru/24oko/glazok1080/2026/07/09/glazok1080_x.mp4"))
    assert data["domain_id"] == "up/ru/24oko"
    assert data["domain_name"] == "up/ru/24oko"
    assert data["device_id"] == "glazok1080"
    assert data["feed_id"] == "glazok1080"


def test_parse_feed_line_straight_to_date_uses_domain_last_segment_as_device():
    # up/eg/makaniBeachClub/<date>/… (no device folder) → domain
    # "up/eg/makaniBeachClub", device "makaniBeachClub"; aimpoint folder matches.
    path = "up/eg/makaniBeachClub/2026/07/09/makaniBeachClub_x.mp4"
    data = parse_feed_line(_delivered(path))
    assert data["domain_id"] == "up/eg/makaniBeachClub"
    assert data["device_id"] == "makaniBeachClub"
    folder, y, m, d = extract_folder_and_date(path)
    assert folder == "up/eg/makaniBeachClub"          # aimpoint: <folder>/<device>.json
    assert (y, m, d) == ("2026", "07", "09")


def test_parse_feed_line_skips_date_shifted_into_domain_slots():
    # Empty segments push the date into the domain slots → skipped, not ingested.
    assert parse_feed_line(_delivered("up//2026/07/09/x.mp4")) is None
    assert parse_feed_line(_delivered("up/ru//2026/07/09/x.mp4")) is None


def test_expected_file_count_so_far_counts_only_elapsed_operating_minutes():
    noon = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    # 24h operation: 720 elapsed minutes / 15 = 48 by noon.
    assert expected_file_count_so_far({"transcoderInterval": 15}, noon) == 48
    # 09:00-18:00 window: 180 elapsed minutes by noon → 12.
    win = {"transcoderInterval": 15, "hours": {"tz": "UTC", "hrs": ["0900-1800"]}}
    assert expected_file_count_so_far(win, noon) == 12
    # Before the window opens → 0; after it closes → the full window count.
    assert expected_file_count_so_far(win, datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)) == 0
    assert expected_file_count_so_far(win, datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)) == expected_file_count(win)


def test_expected_file_count_so_far_honors_timezone_and_overnight_windows():
    noon = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    # 09:00-18:00 US/Eastern: noon UTC is 07:00 ET, before the window → 0.
    et = {"transcoderInterval": 15, "hours": {"tz": "US/Eastern", "hrs": ["0900-1800"]}}
    assert expected_file_count_so_far(et, noon) == 0
    # Overnight 22:00-06:00: at 03:00 UTC, 180 min of the morning portion → 12.
    overnight = {"transcoderInterval": 15, "hours": {"tz": "UTC", "hrs": ["2200-0600"]}}
    assert expected_file_count_so_far(overnight, datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)) == 12


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


def test_parse_device_json_identity_is_the_file_base_name_not_the_deviceID_field():
    # tomsk21.json carries "deviceID": "21" — a short, folder-scoped id that
    # collides across domains. The file's base name is the device identity; the
    # raw deviceID is still preserved inside aimpoint_json for display.
    tally = parse_device_json(json.dumps({"deviceID": "21", "collectionType": "M3U"}), "tomsk21")
    assert tally.device_id == "tomsk21"
    assert json.loads(tally.aimpoint_json)["deviceID"] == "21"


def test_parse_device_json_rejects_non_object():
    assert parse_device_json(json.dumps([1, 2, 3]), "d") is None
    assert parse_device_json("not json", "d") is None
