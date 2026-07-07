from domain_feed_health_dashboard.data_model import DeviceRecord, DomainRecord, FeedRecord
from domain_feed_health_dashboard.status import (
    band_overall_metrics,
    build_domain_band_summary,
    build_domain_summary,
    cell_health_band,
    domain_status_from_feeds,
    feed_health_band,
    feed_status_counts,
    filter_domain_band_summary,
    rollup_band,
    select_domain,
    status_from_count,
)


def _band_feed(feed_id: str, count: int, expected: int) -> FeedRecord:
    device = DeviceRecord(device_id=feed_id, files_expected=expected)
    return FeedRecord(
        feed_id=feed_id, status="yellow", count=count, location="", observed_time="t",
        latitude=0.0, longitude=0.0, feed_type="", source_system="", routers=(device,),
    )


def test_feed_health_band_migrates_with_count():
    bands = [feed_health_band(_band_feed("f", count, 96)) for count in (0, 50, 75, 90, 96, 100)]
    assert bands == ["red", "red", "orange", "yellow", "green", "red"]


def test_rollup_band_is_worst_feed():
    assert rollup_band(["green", "yellow", "orange"]) == "orange"
    assert rollup_band(["green", "red"]) == "red"
    assert rollup_band([]) == "red"          # no feeds → no delivery


def test_build_domain_band_summary_counts_each_band():
    domain = DomainRecord(
        domain_name="d1", domain_id="d1", last_observed_time="t",
        feeds=(_band_feed("a", 96, 96), _band_feed("b", 75, 96), _band_feed("c", 50, 96)),
    )
    row = build_domain_band_summary((domain,)).iloc[0]
    assert row["domain_band"] == "red"       # worst of green/orange/red
    assert (row["green_feeds"], row["orange_feeds"], row["red_feeds"]) == (1, 1, 1)


def test_current_tab_domain_band_propagates_worst_feed():
    # Lowest color propagates up on the Current tab too: one red feed among
    # green feeds makes the domain red (parity with the history tab).
    domain = DomainRecord(
        domain_name="d1", domain_id="d1", last_observed_time="t",
        feeds=(_band_feed("goodcam", 96, 96), _band_feed("worldcam", 30, 96)),
    )
    row = build_domain_band_summary((domain,)).iloc[0]
    assert row["domain_band"] == "red"
    assert (row["green_feeds"], row["red_feeds"]) == (1, 1)

    # The worst band is preserved, not collapsed to red: green + orange → orange.
    orangeish = DomainRecord(
        domain_name="d2", domain_id="d2", last_observed_time="t",
        feeds=(_band_feed("a", 96, 96), _band_feed("b", 75, 96)),
    )
    assert build_domain_band_summary((orangeish,)).iloc[0]["domain_band"] == "orange"


def test_band_overall_metrics_and_filter():
    domains = (
        DomainRecord(domain_name="alpha", domain_id="d1", last_observed_time="t", feeds=(_band_feed("a", 96, 96),)),
        DomainRecord(domain_name="beta", domain_id="d2", last_observed_time="t", feeds=(_band_feed("b", 75, 96),)),
    )
    summary = build_domain_band_summary(domains)
    metrics = band_overall_metrics(summary)
    assert metrics["green_domains"] == 1 and metrics["orange_domains"] == 1
    # Status filter limits to the requested bands; search matches domain name.
    assert filter_domain_band_summary(summary, "", ["orange"], False) == {"d2"}
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
