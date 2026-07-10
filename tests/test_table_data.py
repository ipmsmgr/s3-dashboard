import json

import pandas as pd

from domain_feed_health_dashboard.data_model import DomainRecord, FeedRecord, RouterAccessPoint
from domain_feed_health_dashboard.table_data import (
    FEED_DETAIL_COLUMNS,
    FEED_VISIBLE_COLUMNS,
    device_field_value_dataframe,
    device_field_value_rows,
    domain_master_detail_dataframe,
    feed_detail_rows,
)


def _router(device_id: str = "DEV-001", files_expected: int = 96):
    aimpoint = {
        "deviceID": device_id,
        "collEnabled": True,
        "collRegions": ["United States (N. Virginia)"],
        "proxy": "mendeleev-op.whirl.dom:8080",
        "decoy": False,
        "collectionType": "M3U",
        "accessUrl": "https://example.test/stream.m3u8",
        "pollFrequency": 5,
        "hours": {"tz": "US/Eastern", "hrs": ["0900-1800"]},
        "longLat": [-97.7431, 30.2672],
        "dstBucket": "thorium-ch-prod",
        "monitoringData": {"lastMonitoredIsoDate": "2025-12-16T20:39:05+00:00"},
    }
    return RouterAccessPoint(
        device_id=device_id,
        aimpoint_json=json.dumps(aimpoint),
        health_status="yellow",
        op_window_start="09:00",
        op_window_end="18:00",
        files_expected=files_expected,
    )


def _feed(feed_id: str, status: str, routers=()):
    return FeedRecord(
        feed_id=feed_id,
        status=status,  # type: ignore[arg-type]
        count=7,
        location="Austin, TX",
        observed_time="2026-06-09T12:00:00+00:00",
        latitude=30.2672,
        longitude=-97.7431,
        feed_type="telemetry",
        source_system="collector-a",
        details="test fixture",
        routers=routers,
    )


def test_feed_detail_rows_has_required_eight_visible_columns_plus_hidden_router_rows():
    domain = DomainRecord(domain_id="DOMAIN-001", domain_name="alpha.example.net", feeds=(_feed("FEED-001", "green"),), last_observed_time="now")
    rows = feed_detail_rows(domain)
    assert list(rows[0].keys()) == FEED_DETAIL_COLUMNS
    assert len(FEED_VISIBLE_COLUMNS) == 8


def test_feed_detail_rows_gray_feed_device_panel_says_no_aimpoint():
    # A feed with no aimpoint is gray → its device panel says "No aimpoint exists".
    domain = DomainRecord(domain_id="DOMAIN-001", domain_name="alpha.example.net", feeds=(_feed("FEED-001", "green"),), last_observed_time="now")
    row = feed_detail_rows(domain)[0]
    assert row["band"] == "none"
    assert json.loads(row["router_rows_json"]) == [{"field": "Aimpoint", "value": "No aimpoint exists"}]


def test_feed_detail_rows_derives_expected_per_day_from_attached_device():
    domain = DomainRecord(
        domain_id="DOMAIN-001",
        domain_name="alpha.example.net",
        feeds=(_feed("FEED-001", "green", routers=(_router("DEV-001", files_expected=96),)),),
        last_observed_time="now",
    )
    row = feed_detail_rows(domain)[0]
    assert row["expected_per_day"] == 96


def test_feed_detail_rows_populate_location_region_proxy_from_device_aimpoint():
    domain = DomainRecord(
        domain_id="DOMAIN-001",
        domain_name="alpha.example.net",
        feeds=(_feed("FEED-001", "green", routers=(_router("DEV-001"),)),),
        last_observed_time="now",
    )
    row = feed_detail_rows(domain)[0]
    # Collection Type / Location / Collection Region / Proxy come from the device aimpoint.
    assert row["feed_type"] == "M3U"
    assert row["location"] == "-97.7431, 30.2672"
    assert row["coll_region"] == "United States (N. Virginia)"
    assert row["proxy"] == "mendeleev-op.whirl.dom:8080"


def test_feed_detail_rows_location_region_proxy_empty_with_no_device():
    domain = DomainRecord(domain_id="DOMAIN-001", domain_name="alpha.example.net", feeds=(_feed("FEED-001", "green"),), last_observed_time="now")
    row = feed_detail_rows(domain)[0]
    assert row["feed_type"] == ""
    assert row["location"] == ""
    assert row["coll_region"] == ""
    assert row["proxy"] == ""


def test_domain_master_dataframe_region_and_proxy_from_any_feed_device():
    domain = DomainRecord(
        domain_id="DOMAIN-001",
        domain_name="alpha.example.net",
        # First feed has no device; the values come from the second feed's device.
        feeds=(_feed("FEED-000", "green"), _feed("FEED-001", "green", routers=(_router("DEV-001"),))),
        last_observed_time="now",
    )
    df = domain_master_detail_dataframe((domain,))
    assert df.iloc[0]["coll_region"] == "United States (N. Virginia)"
    assert df.iloc[0]["proxy"] == "mendeleev-op.whirl.dom:8080"


def test_feed_detail_rows_expected_per_day_is_none_with_no_device():
    domain = DomainRecord(domain_id="DOMAIN-001", domain_name="alpha.example.net", feeds=(_feed("FEED-001", "green"),), last_observed_time="now")
    row = feed_detail_rows(domain)[0]
    assert row["expected_per_day"] is None


def test_feed_detail_rows_embeds_device_field_value_rows_for_nested_feed_expansion():
    domain = DomainRecord(
        domain_id="DOMAIN-001",
        domain_name="alpha.example.net",
        feeds=(_feed("FEED-001", "green", routers=(_router("DEV-001"),)),),
        last_observed_time="now",
    )
    row = feed_detail_rows(domain)[0]
    decoded_device_rows = json.loads(row["router_rows_json"])
    assert decoded_device_rows[0] == {"field": "Device ID", "value": "DEV-001"}
    # Current tab embeds the device panel including the current-expected row.
    fields = {r["field"] for r in decoded_device_rows}
    assert {"Files Actual", "Files Expected", "Current Expected Files"} <= fields


def test_master_detail_dataframe_embeds_feed_rows_per_domain():
    domain = DomainRecord(
        domain_id="DOMAIN-001",
        domain_name="alpha.example.net",
        feeds=(_feed("FEED-001", "green"), _feed("FEED-002", "red")),
        last_observed_time="now",
    )
    df = domain_master_detail_dataframe((domain,), max_feed_rows=1)
    assert df.iloc[0]["domain_id"] == "DOMAIN-001"
    assert df.iloc[0]["total_feeds"] == 2
    assert df.iloc[0]["displayed_feed_rows"] == 1
    assert json.loads(df.iloc[0]["feed_rows_json"]) == [feed_detail_rows(domain, max_feed_rows=1)[0]]


def test_zero_feed_domain_still_has_master_detail_row():
    domain = DomainRecord(domain_id="DOMAIN-EMPTY", domain_name="empty.example.net", feeds=(), last_observed_time="now")
    df = domain_master_detail_dataframe((domain,))
    assert df.iloc[0]["total_feeds"] == 0
    assert df.iloc[0]["displayed_feed_rows"] == 0
    assert json.loads(df.iloc[0]["feed_rows_json"]) == []


def test_device_field_value_rows_is_empty_with_no_device():
    assert device_field_value_rows(()) == []


def test_device_field_value_rows_current_expected_only_when_requested():
    from datetime import datetime, timezone
    router = _router()  # hours 09:00-18:00 US/Eastern, 15-min interval
    # Default (Historical): no "Current Expected Files" row.
    assert "Current Expected Files" not in {r["field"] for r in device_field_value_rows((router,))}
    # Current tab: appended = expected-so-far. 17:00 UTC = 12:00 EST → 180 min → 12.
    noon_est = datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc)
    rows = device_field_value_rows((router,), include_current_expected=True, now=noon_est)
    cur = next(r for r in rows if r["field"] == "Current Expected Files")
    assert cur["value"] == 12


def test_feed_detail_rows_device_panel_includes_current_expected_files():
    domain = DomainRecord(
        domain_id="DOMAIN-001", domain_name="alpha.example.net",
        feeds=(_feed("FEED-001", "green", routers=(_router("DEV-001"),)),), last_observed_time="now",
    )
    device_fields = {r["field"] for r in json.loads(feed_detail_rows(domain)[0]["router_rows_json"])}
    assert "Current Expected Files" in device_fields


def test_device_field_value_rows_has_no_health_status_row():
    fields = {row["field"] for row in device_field_value_rows((_router(),))}
    assert "Health Status" not in fields


def test_device_field_value_rows_flattens_full_aimpoint_structure():
    fields = {row["field"] for row in device_field_value_rows((_router(),))}
    # Full aimpoint structure is shown (labeled), including newer fields.
    assert {"Device ID", "Collection Type", "Access URL", "Poll Frequency (s)", "Dst Bucket"} <= fields
    # Nested objects flatten to "Parent · Child".
    assert "Working Hours · Timezone" in fields
    # File-count metrics are appended (no Health Status row).
    assert {"Files Actual", "Files Expected"} <= fields
    # Nothing fabricated / no non-aimpoint network fields.
    assert not ({"Hostname", "IP Address", "MAC Address"} & fields)


def test_device_field_value_dataframe_uses_field_value_columns():
    router = _router()
    df = device_field_value_dataframe((router,))
    assert list(df.columns) == ["field", "value"]
    assert df.iloc[0]["field"] == "Device ID"
    assert df.iloc[0]["value"] == "DEV-001"


def test_master_detail_dataframe_contains_only_hashable_cells():
    domain = DomainRecord(
        domain_id="DOMAIN-001",
        domain_name="alpha.example.net",
        feeds=(_feed("FEED-001", "green", routers=(_router("DEV-001"),)),),
        last_observed_time="now",
    )
    df = domain_master_detail_dataframe((domain,))

    # This mirrors the Streamlit hashing path that used to warn when the
    # DataFrame contained list/dict cells for nested AgGrid rows.
    nested_cell_count = sum(isinstance(value, (list, dict)) for value in df.to_numpy().ravel())
    assert nested_cell_count == 0
    assert len(pd.util.hash_pandas_object(df, index=False)) == len(df)
