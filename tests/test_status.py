import json
from datetime import datetime, timezone

from domain_feed_health_dashboard.data_model import DeviceRecord, DomainRecord, FeedRecord
from domain_feed_health_dashboard.status import (
    band_overall_metrics,
    build_domain_band_summary,
    build_domain_summary,
    cell_health_band,
    current_feed_band,
    domain_status_from_feeds,
    feed_status_counts,
    filter_domain_band_summary,
    rollup_band,
    select_domain,
    status_from_count,
)

# noon UTC → 720 minutes elapsed → 720 // 15 = 48 files expected so far (24h op).
_NOON = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
# 24-hour operation at the default 15-min interval (no "hours" → all day).
_AIM_24H = {"deviceID": "d", "transcoderInterval": 15}


def _cur_feed(feed_id: str, count: int, aimpoint: dict | None = None) -> FeedRecord:
    routers = ()
    if aimpoint is not None:
        routers = (DeviceRecord(device_id=feed_id, aimpoint_json=json.dumps(aimpoint)),)
    return FeedRecord(
        feed_id=feed_id, status="yellow", count=count, location="", observed_time="t",
        latitude=0.0, longitude=0.0, feed_type="", source_system="", routers=routers,
    )


def test_current_feed_band_is_green_when_count_matches_expected_so_far():
    assert current_feed_band(_cur_feed("f", 48, _AIM_24H), _NOON) == "green"


def test_current_feed_band_allows_plus_or_minus_one_tolerance():
    # Off by one (either direction) still counts as green — timing jitter grace.
    assert current_feed_band(_cur_feed("f", 49, _AIM_24H), _NOON) == "green"
    assert current_feed_band(_cur_feed("f", 47, _AIM_24H), _NOON) == "green"


def test_current_feed_band_is_yellow_beyond_tolerance_never_red():
    # More than ±1 off → yellow (never red), either direction.
    assert current_feed_band(_cur_feed("f", 50, _AIM_24H), _NOON) == "yellow"
    assert current_feed_band(_cur_feed("f", 46, _AIM_24H), _NOON) == "yellow"


def test_current_feed_band_is_gray_when_nothing_delivered():
    # A zero file count is gray (nothing to assess) — e.g. a configured device
    # that isn't producing — at any time of day.
    midnight = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert current_feed_band(_cur_feed("f", 0, _AIM_24H), midnight) == "none"
    assert current_feed_band(_cur_feed("f", 0, _AIM_24H), _NOON) == "none"


def test_current_feed_band_is_gray_without_aimpoint():
    assert current_feed_band(_cur_feed("f", 5), _NOON) == "none"


def test_current_feed_band_respects_operating_hours():
    # 09:00-18:00 window; at 12:00 that tz, 180 min elapsed → 12 files expected.
    aim = {"deviceID": "d", "transcoderInterval": 15, "hours": {"tz": "UTC", "hrs": ["0900-1800"]}}
    assert current_feed_band(_cur_feed("f", 12, aim), _NOON) == "green"
    assert current_feed_band(_cur_feed("f", 20, aim), _NOON) == "yellow"


def test_rollup_band_is_worst_feed():
    assert rollup_band(["green", "yellow", "orange"]) == "orange"
    assert rollup_band(["green", "red"]) == "red"
    assert rollup_band([]) == "red"          # no feeds → no delivery


def test_rollup_band_none_is_non_contributing_but_all_none_is_none():
    # "none" (no aimpoint) never wins against a real band...
    assert rollup_band(["green", "none"]) == "green"
    assert rollup_band(["none", "red"]) == "red"
    # ...but when every child is "none" the rollup is gray, not red.
    assert rollup_band(["none", "none"]) == "none"


def test_none_band_has_an_icon():
    from domain_feed_health_dashboard.status import BAND_ICONS, NONE_BAND
    assert NONE_BAND == "none"
    assert "none" in BAND_ICONS


def test_filter_treats_none_as_a_first_class_band_option():
    import pandas as pd
    summary = pd.DataFrame([
        {"domain_id": "d1", "domain_name": "gray", "domain_band": "none", "red_feeds": 0},
        {"domain_id": "d2", "domain_name": "grn", "domain_band": "green", "red_feeds": 0},
    ])
    # "none" is a selectable filter box → it filters like any other band.
    assert filter_domain_band_summary(summary, "", ["none"], False) == {"d1"}
    assert filter_domain_band_summary(summary, "", ["green"], False) == {"d2"}
    assert filter_domain_band_summary(summary, "", ["green", "none"], False) == {"d1", "d2"}


def test_none_is_a_filter_option():
    from domain_feed_health_dashboard.status import BAND_OPTIONS
    assert "none" in BAND_OPTIONS


def test_current_domain_band_is_worst_feed_and_never_red():
    # One green feed + one deviating (yellow) feed → domain yellow (worst wins).
    domain = DomainRecord(
        domain_name="d1", domain_id="d1", last_observed_time="t",
        feeds=(_cur_feed("a", 48, _AIM_24H), _cur_feed("b", 40, _AIM_24H)),
    )
    row = build_domain_band_summary((domain,), _NOON).iloc[0]
    assert row["domain_band"] == "yellow"
    assert (row["green_feeds"], row["yellow_feeds"], row["red_feeds"]) == (1, 1, 0)

    all_green = DomainRecord(
        domain_name="d2", domain_id="d2", last_observed_time="t",
        feeds=(_cur_feed("a", 48, _AIM_24H), _cur_feed("b", 48, _AIM_24H)),
    )
    assert build_domain_band_summary((all_green,), _NOON).iloc[0]["domain_band"] == "green"


def test_current_domain_is_gray_when_no_aimpoint_at_all():
    domain = DomainRecord(
        domain_name="d1", domain_id="d1", last_observed_time="t",
        feeds=(_cur_feed("a", 5), _cur_feed("b", 0)),  # no aimpoints
    )
    assert build_domain_band_summary((domain,), _NOON).iloc[0]["domain_band"] == "none"


def test_band_overall_metrics_and_filter():
    domains = (
        DomainRecord(domain_name="alpha", domain_id="d1", last_observed_time="t", feeds=(_cur_feed("a", 48, _AIM_24H),)),   # green
        DomainRecord(domain_name="beta", domain_id="d2", last_observed_time="t", feeds=(_cur_feed("b", 40, _AIM_24H),)),    # yellow
    )
    summary = build_domain_band_summary(domains, _NOON)
    metrics = band_overall_metrics(summary)
    assert metrics["green_domains"] == 1 and metrics["yellow_domains"] == 1
    # Status filter limits to the requested bands; search matches domain name.
    assert filter_domain_band_summary(summary, "", ["yellow"], False) == {"d2"}
    assert filter_domain_band_summary(summary, "alph", [], False) == {"d1"}


def make_feed(feed_id: str, status: str) -> FeedRecord:
    return FeedRecord(
        feed_id=feed_id,
        status=status,  # type: ignore[arg-type]
        count=1,
        location="Test Location",
        observed_time="2026-06-09T12:00:00+00:00",
        latitude=40.0,
        longitude=-75.0,
        feed_type="telemetry",
        source_system="test-generator",
        details="Test feed.",
    )


def test_status_from_count_thresholds():
    # At or below half the expected count is RED.
    assert status_from_count(0, 10) == "red"
    assert status_from_count(5, 10) == "red"
    # Between half and full is YELLOW.
    assert status_from_count(6, 10) == "yellow"
    # At or above expected is GREEN.
    assert status_from_count(10, 10) == "green"
    assert status_from_count(12, 10) == "green"


def test_status_from_count_with_no_expected_window():
    # No expected files: GREEN only if something was delivered, else RED.
    assert status_from_count(3, 0) == "green"
    assert status_from_count(0, 0) == "red"


def test_status_from_count_handles_non_numeric():
    assert status_from_count("x", 10) == "red"  # type: ignore[arg-type]


def test_cell_health_band_scales_by_percentage_of_expected():
    # 95-100% green, 80-94% yellow, 70-79% orange, 0-69% red.
    assert cell_health_band(96, 96) == "green"     # 100%
    assert cell_health_band(95, 100) == "green"    # 95%
    assert cell_health_band(94, 100) == "yellow"   # 94%
    assert cell_health_band(80, 100) == "yellow"   # 80%
    assert cell_health_band(79, 100) == "orange"    # 79%
    assert cell_health_band(70, 100) == "orange"    # 70%
    assert cell_health_band(69, 100) == "red"      # 69%
    assert cell_health_band(0, 96) == "red"        # 0%


def test_cell_health_band_over_delivery_is_red():
    assert cell_health_band(97, 96) == "red"       # > 100%
    assert cell_health_band(200, 96) == "red"


def test_cell_health_band_with_no_expected_is_red():
    assert cell_health_band(10, 0) == "red"
    assert cell_health_band(0, 0) == "red"


def test_domain_status_is_red_if_any_feed_is_red():
    feeds = [make_feed("a", "green"), make_feed("b", "yellow"), make_feed("c", "red")]
    assert domain_status_from_feeds(feeds) == "red"


def test_domain_status_is_yellow_when_no_red_but_yellow_exists():
    feeds = [make_feed("a", "green"), make_feed("b", "yellow")]
    assert domain_status_from_feeds(feeds) == "yellow"


def test_domain_status_is_green_when_all_feeds_are_green():
    feeds = [make_feed("a", "green"), make_feed("b", "green")]
    assert domain_status_from_feeds(feeds) == "green"


def test_domain_status_is_yellow_for_zero_feeds():
    assert domain_status_from_feeds([]) == "yellow"


def test_feed_status_counts_include_all_status_keys():
    counts = feed_status_counts([make_feed("a", "green"), make_feed("b", "green"), make_feed("c", "red")])
    assert counts == {"red": 1, "yellow": 0, "green": 2}


def test_domain_summary_counts_red_yellow_green_feeds():
    domain = DomainRecord(
        domain_name="example.test",
        feeds=(
            make_feed("red-1", "red"),
            make_feed("yellow-1", "yellow"),
            make_feed("green-1", "green"),
            make_feed("green-2", "green"),
        ),
        last_observed_time="2026-06-09T12:00:00+00:00",
    )
    summary = build_domain_summary([domain])
    row = summary.iloc[0]
    assert row["domain_name"] == "example.test"
    assert row["domain_status"] == "red"
    assert row["total_feeds"] == 4
    assert row["red_feeds"] == 1
    assert row["yellow_feeds"] == 1
    assert row["green_feeds"] == 2


def test_select_domain_prefers_new_selection():
    assert select_domain("old.example.net", "new.example.net") == "new.example.net"


def test_select_domain_preserves_current_selection_without_new_selection():
    assert select_domain("old.example.net", None) == "old.example.net"


def test_domain_summary_includes_stable_domain_id():
    domain = DomainRecord(
        domain_name="example.test",
        feeds=(make_feed("green-1", "green"),),
        last_observed_time="2026-06-09T12:00:00+00:00",
        domain_id="DOMAIN-TEST",
    )
    summary = build_domain_summary([domain])
    row = summary.iloc[0]
    assert row["domain_id"] == "DOMAIN-TEST"
    assert row["domain_name"] == "example.test"
