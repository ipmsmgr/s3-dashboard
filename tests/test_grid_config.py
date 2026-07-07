import pandas as pd

from domain_feed_health_dashboard.grid_config import (
    build_domain_master_detail_grid_options,
    build_history_master_detail_grid_options,
    selected_row_value,
)


def test_selected_row_value_from_list_response():
    response = {"selected_rows": [{"domain_id": "DOMAIN-001", "domain_name": "example.net"}]}
    assert selected_row_value(response, "domain_id") == "DOMAIN-001"


def test_selected_row_value_from_dataframe_response():
    response = {"selected_rows": pd.DataFrame([{"feed_id": "FEED-001"}])}
    assert selected_row_value(response, "feed_id") == "FEED-001"


def test_selected_row_value_returns_none_for_empty_selection():
    assert selected_row_value({"selected_rows": []}, "domain_id") is None


def test_domain_grid_headers():
    data = pd.DataFrame(
        [
            {
                "domain_id": "DOMAIN-001",
                "domain_name": "alpha.example.net",
                "domain_status": "green",
                "status_label": "🟢 GREEN / Good",
                "total_feeds": 1,
                "red_feeds": 0,
                "yellow_feeds": 0,
                "green_feeds": 1,
                "last_observed_time": "now",
                "displayed_feed_rows": 1,
                "feed_rows_json": "[]",
            }
        ]
    )
    options = build_domain_master_detail_grid_options(data)
    cols = {column["field"]: column for column in options["columnDefs"]}
    # Domain master column labels.
    assert cols["domain_name"]["headerName"] == "Domain"
    # No separate Status column — the band color is on the Domain (first) cell.
    assert cols["status_label"].get("hide") is True
    assert cols["domain_name"].get("cellStyle") is not None
    assert cols["total_feeds"]["headerName"] == "Total Feeds"
    assert cols["red_feeds"]["headerName"] == "Red"
    assert cols["yellow_feeds"]["headerName"] == "Yellow"
    assert cols["green_feeds"]["headerName"] == "Green"
    # "Last Checked" and "Expanded feed rows" are removed from the domain master.
    assert cols["last_observed_time"].get("hide") is True
    assert cols["displayed_feed_rows"].get("hide") is True
    # Collection Region / Proxy columns (populated from feed devices).
    assert cols["coll_region"]["headerName"] == "Collection Region"
    assert cols["proxy"]["headerName"] == "Proxy"


def test_feed_detail_grid_headers():
    options = build_domain_master_detail_grid_options(
        pd.DataFrame(
            [
                {
                    "domain_id": "DOMAIN-001",
                    "domain_name": "alpha.example.net",
                    "domain_status": "green",
                    "status_label": "🟢 GREEN / Good",
                    "total_feeds": 0,
                    "red_feeds": 0,
                    "yellow_feeds": 0,
                    "green_feeds": 0,
                    "last_observed_time": "now",
                    "displayed_feed_rows": 0,
                    "feed_rows_json": "[]",
                }
            ]
        )
    )
    feed_grid_options = options["detailCellRendererParams"]["detailGridOptions"]
    headers_by_field = {column["field"]: column.get("headerName") for column in feed_grid_options["columnDefs"]}
    # Feed grid column labels — no Status column; the band color is on File Count.
    assert headers_by_field["feed_id"] == "Device ID"
    assert "status_label" not in headers_by_field
    assert headers_by_field["count"] == "File Count"
    assert headers_by_field["expected_per_day"] == "Expected / Day"
    assert headers_by_field["location"] == "Location"
    assert headers_by_field["feed_type"] == "Collection Type"
    assert headers_by_field["coll_region"] == "Collection Region"
    assert headers_by_field["proxy"] == "Proxy"
    count_col = next(column for column in feed_grid_options["columnDefs"] if column["field"] == "count")
    assert count_col.get("cellStyle") is not None


def test_device_detail_grid_uses_field_value_layout():
    options = build_domain_master_detail_grid_options(
        pd.DataFrame(
            [
                {
                    "domain_id": "DOMAIN-001",
                    "domain_name": "alpha.example.net",
                    "domain_status": "green",
                    "status_label": "🟢 GREEN / Good",
                    "total_feeds": 0,
                    "red_feeds": 0,
                    "yellow_feeds": 0,
                    "green_feeds": 0,
                    "last_observed_time": "now",
                    "displayed_feed_rows": 0,
                    "feed_rows_json": "[]",
                }
            ]
        )
    )
    feed_grid_options = options["detailCellRendererParams"]["detailGridOptions"]
    device_grid_options = feed_grid_options["detailCellRendererParams"]["detailGridOptions"]
    fields = [column["field"] for column in device_grid_options["columnDefs"]]
    assert fields == ["field", "value"]


def _history_master_df():
    return pd.DataFrame(
        [
            {
                "domain_id": "DOMAIN-001",
                "domain_name": "alpha.example.net",
                "domain_status": "red",
                "status_label": "🔴 RED / Broken",
                "total_feeds": 2,
                "red_feeds": 1,
                "yellow_feeds": 1,
                "green_feeds": 0,
                "last_observed_time": "2026-06-17T00:00:00+00:00",
                "feed_rows_json": "[]",
                "trend_img": "data:image/png;base64,AAAA",
            }
        ]
    )


def test_build_history_master_detail_nests_domain_feed_pivot_and_device():
    date_headers = [("2026-06-17", "6/17"), ("2026-06-16", "6/16")]
    options = build_history_master_detail_grid_options(_history_master_df(), date_headers)

    assert options["masterDetail"] is True
    # Master grid: domain columns, with the nested feed payload hidden.
    fields = {column["field"]: column for column in options["columnDefs"]}
    assert fields["domain_name"]["headerName"] == "Domain"
    assert fields["feed_rows_json"]["hide"] is True

    # First-level detail = feed×day pivot grid.
    feed_grid = options["detailCellRendererParams"]["detailGridOptions"]
    feed_cols = feed_grid["columnDefs"]
    assert feed_cols[0]["field"] == "feed_id"
    visible_days = [c for c in feed_cols[1:] if not c.get("hide") and c["field"] != "router_rows_json"]
    assert [c["field"] for c in visible_days] == ["2026-06-17", "2026-06-16"]
    assert all(c.get("cellStyle") is not None for c in visible_days)
    assert feed_grid["masterDetail"] is True

    # Second-level detail = device aimpoint Field/Value grid.
    device_grid = feed_grid["detailCellRendererParams"]["detailGridOptions"]
    assert [c["field"] for c in device_grid["columnDefs"]] == ["field", "value"]


def test_history_master_has_trend_sparkline_column():
    date_headers = [("2026-06-17", "6/17"), ("2026-06-16", "6/16")]
    options = build_history_master_detail_grid_options(_history_master_df(), date_headers)
    cols = {column["field"]: column for column in options["columnDefs"]}
    # Inline sparkline column (last column): a PNG data-URI shown as the cell's
    # background image via a cellStyle function (a cellRenderer returning
    # markup/DOM is escaped or crashes React under AG Grid 34); the raw value
    # text is blanked by the valueFormatter.
    assert cols["trend_img"]["headerName"] == "Trend"
    assert cols["trend_img"].get("valueFormatter") is not None
    assert cols["trend_img"].get("cellStyle") is not None
    assert cols["trend_img"].get("sortable") is False
    # Only the Trend cell selects its row (opens the plot); plain row clicks don't.
    assert cols["trend_img"].get("onCellClicked") is not None
    assert options.get("suppressRowClickSelection") is True
    # Taller master rows give the sparkline vertical room.
    assert options.get("rowHeight") == 40
