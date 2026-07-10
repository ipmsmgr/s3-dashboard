"""Reusable AgGrid configuration helpers for Streamlit tables."""

from __future__ import annotations

from typing import Any

import pandas as pd

from domain_feed_health_dashboard.history_data import MISSING_DAY_LABEL, STATUS_COLUMN_SUFFIX

try:  # pragma: no cover - exercised when streamlit-aggrid is installed locally.
    from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, GridUpdateMode, JsCode
except ImportError:  # pragma: no cover - lets tests run in minimal environments.
    AgGrid = None  # type: ignore[assignment]
    DataReturnMode = None  # type: ignore[assignment]
    GridOptionsBuilder = None  # type: ignore[assignment]
    GridUpdateMode = None  # type: ignore[assignment]
    JsCode = None  # type: ignore[assignment]


# Colors a Current-tab feed cell (File Count) by its hidden "band" field. On the
# Current tab the band is green (delivered == expected-so-far), yellow (any
# deviation), or gray "none" (no aimpoint) — never red (see status.current_feed_band).
BAND_CELL_STYLE_JS = """
function(params) {
    var band = params.data ? params.data.band : null;
    if (band === 'red') { return {'backgroundColor': '#dc2626', 'color': '#ffffff', 'fontWeight': '700'}; }
    if (band === 'orange') { return {'backgroundColor': '#f97316', 'color': '#7c2d12', 'fontWeight': '700'}; }
    if (band === 'yellow') { return {'backgroundColor': '#facc15', 'color': '#422006', 'fontWeight': '700'}; }
    if (band === 'green') { return {'backgroundColor': '#16a34a', 'color': '#ffffff', 'fontWeight': '700'}; }
    if (band === 'none') { return {'backgroundColor': '#e5e7eb', 'color': '#6b7280'}; }
    return null;
}
"""


# Colors a domain master row's Status cell by its hidden "domain_band" field
# (worst feed band), used by both the Current and Historical domain grids.
DOMAIN_BAND_STYLE_JS = """
function(params) {
    var band = params.data ? params.data.domain_band : null;
    if (band === 'red') { return {'backgroundColor': '#dc2626', 'color': '#ffffff', 'fontWeight': '700'}; }
    if (band === 'orange') { return {'backgroundColor': '#f97316', 'color': '#7c2d12', 'fontWeight': '700'}; }
    if (band === 'yellow') { return {'backgroundColor': '#facc15', 'color': '#422006', 'fontWeight': '700'}; }
    if (band === 'green') { return {'backgroundColor': '#16a34a', 'color': '#ffffff', 'fontWeight': '700'}; }
    if (band === 'none') { return {'backgroundColor': '#e5e7eb', 'color': '#6b7280', 'fontWeight': '700'}; }
    return null;
}
"""


# Colors a historical day-pivot count cell by its sibling "<date>__status"
# field (the visible cell shows the delivered file count, not a status letter).
HISTORY_CELL_STYLE_JS = f"""
function(params) {{
    if (!params.data) {{ return null; }}
    var status = params.data[params.colDef.field + '{STATUS_COLUMN_SUFFIX}'];
    if (status === 'red') {{
        return {{'backgroundColor': '#dc2626', 'color': '#ffffff', 'fontWeight': '700'}};
    }}
    if (status === 'orange') {{
        return {{'backgroundColor': '#f97316', 'color': '#7c2d12', 'fontWeight': '700'}};
    }}
    if (status === 'yellow') {{
        return {{'backgroundColor': '#facc15', 'color': '#422006', 'fontWeight': '700'}};
    }}
    if (status === 'green') {{
        return {{'backgroundColor': '#16a34a', 'color': '#ffffff', 'fontWeight': '700'}};
    }}
    if (status === 'none') {{
        return {{'backgroundColor': '#e5e7eb', 'color': '#6b7280'}};
    }}
    return null;
}}
"""


# Renders a domain's pre-rendered PNG line sparkline (the ``trend_img`` data:
# URI, built by history_data.domain_trend_png) as the Trend cell's BACKGROUND
# IMAGE. This build is AG Grid 34 with reactiveCustomComponents=true, so a
# cellRenderer returning markup/DOM is escaped or crashes React (#31) — but a
# cellStyle function only returns a plain style object (same mechanism as the
# band-colour styles above), which React applies safely. TREND_HIDE_VALUE_JS
# blanks the raw data-URI text so only the image shows.
TREND_IMAGE_STYLE_JS = """
function(params) {
    if (!params.value) { return null; }
    return {
        'backgroundImage': 'url("' + params.value + '")',
        'backgroundRepeat': 'no-repeat',
        'backgroundPosition': 'center',
        'backgroundSize': '100% 100%'
    };
}
"""

TREND_HIDE_VALUE_JS = "function(params) { return ''; }"

# Selects the clicked domain row (single-select) — attached ONLY to the Trend
# cell. With suppressRowClickSelection on the grid, this is the only way a row
# becomes selected, so the enlarged plot (which opens on selection change) opens
# only when the sparkline itself is clicked, not on any other cell/row click.
TREND_CELL_CLICK_JS = """
function(event) {
    if (event.node) { event.node.setSelected(true, true); }
}
"""


# Renders a missing (null) history count cell as the em-dash placeholder.
HISTORY_COUNT_FORMATTER_JS = f"""
function(params) {{
    if (params.value === null || params.value === undefined) {{ return '{MISSING_DAY_LABEL}'; }}
    return params.value;
}}
"""


DETAIL_GET_FEED_ROWS_JS = """
function(params) {
    try {
        const rows = params.data.feed_rows_json ? JSON.parse(params.data.feed_rows_json) : [];
        params.successCallback(Array.isArray(rows) ? rows : []);
    } catch (error) {
        console.warn('Failed to parse feed_rows_json', error);
        params.successCallback([]);
    }
}
"""


DETAIL_GET_ROUTER_ROWS_JS = """
function(params) {
    try {
        const rows = params.data.router_rows_json ? JSON.parse(params.data.router_rows_json) : [];
        params.successCallback(Array.isArray(rows) ? rows : []);
    } catch (error) {
        console.warn('Failed to parse router_rows_json', error);
        params.successCallback([]);
    }
}
"""


ROW_CLICK_EXPAND_JS = """
function(event) {
    if (event.node && event.node.master) {
        event.node.setExpanded(!event.node.expanded);
    }
}
"""


FEED_ROW_CLICK_EXPAND_JS = """
function(event) {
    if (event.node && event.node.master) {
        event.node.setExpanded(!event.node.expanded);
    }
}
"""


# History feed×day pivot: a click on a DAY cell opens (or refreshes) the device
# detail for that specific day; a click on the feed-id (or any non-day) cell
# clears the day and toggles the detail with the default (most recent) aimpoint.
# Re-expanding forces getDetailRowData to recompute for the chosen day.
HISTORY_FEED_PIVOT_CELL_CLICK_JS = """
function(event) {
    var node = event.node;
    if (!node || !node.master) { return; }
    var field = event.column ? event.column.getColId() : '';
    if (/^\\d{4}-\\d{2}-\\d{2}$/.test(field)) {
        node.data._selected_day = field;
        node.setExpanded(false);
        node.setExpanded(true);
    } else {
        node.data._selected_day = null;
        node.setExpanded(!node.expanded);
    }
}
"""


# History device detail: resolves the aimpoint rows for the clicked day.
# With a selected day, show that EXACT day's stored aimpoint (aimpoint_by_day),
# or "No aimpoint exists" if that day has none (no fall-back to a previous day).
# With no day selected, use the default (current/most-recent) router_rows_json.
HISTORY_DETAIL_GET_ROUTER_ROWS_JS = """
function(params) {
    var placeholder = [{field: 'Aimpoint', value: 'No aimpoint exists'}];
    try {
        var data = params.data || {};
        var day = data._selected_day;
        var rows = null;
        if (day) {
            var byDay = data.aimpoint_by_day_json ? JSON.parse(data.aimpoint_by_day_json) : {};
            var days = byDay.days || {};
            if (Object.prototype.hasOwnProperty.call(days, day)) {
                rows = (byDay.variants || [])[days[day]] || null;
            }
        } else {
            rows = data.router_rows_json ? JSON.parse(data.router_rows_json) : null;
        }
        if (!Array.isArray(rows) || rows.length === 0) { rows = placeholder; }
        params.successCallback(rows);
    } catch (error) {
        params.successCallback(placeholder);
    }
}
"""


def aggrid_available() -> bool:
    """Return whether streamlit-aggrid is importable in this runtime."""

    return AgGrid is not None and GridOptionsBuilder is not None


def _base_builder(data: pd.DataFrame, row_id_column: str) -> Any:
    if GridOptionsBuilder is None:
        raise RuntimeError("streamlit-aggrid is not installed")

    builder = GridOptionsBuilder.from_dataframe(data)
    builder.configure_default_column(
        filter=True,
        sortable=True,
        resizable=True,
        wrapText=False,
        autoHeight=False,
    )
    builder.configure_selection(selection_mode="single", use_checkbox=False)
    # No pagination — the grid shows every row (height is sized to fit them all).
    builder.configure_column(row_id_column, hide=True)
    if JsCode is not None:
        builder.configure_grid_options(
            getRowId=JsCode(f"function(params) {{ return params.data.{row_id_column}; }}"),
        )
    return builder


def _configure_domain_band_columns(builder: Any, *, count_flex: float | None = None) -> None:
    """Configure the shared domain master columns for both tabs.

    Domain / Total Feeds / Green / Yellow / Orange / Red / Last Checked. There is
    no separate Status column — the Domain (first) cell itself is coloured by the
    hidden ``domain_band`` (worst feed band).

    ``count_flex`` gives the count columns a proportional ``flex`` width (instead
    of fixed pixels) so they stretch to fill the grid — used by the Historical
    tab. When ``None`` (Current tab) they keep compact fixed widths.
    """
    # NOTE: GridOptionsBuilder.configure_column() overwrites headerName back to
    # the field name on every call that omits header_name, so a field that
    # needs both a label and a cellStyle must get both in the SAME call.
    builder.configure_column(
        "domain_name",
        header_name="Domain",
        minWidth=250,
        pinned="left",
        cellRenderer="agGroupCellRenderer",
        cellStyle=JsCode(DOMAIN_BAND_STYLE_JS) if JsCode is not None else None,
    )
    builder.configure_column("status_label", hide=True)
    builder.configure_column("domain_band", hide=True)
    if count_flex is None:
        builder.configure_column("total_feeds", header_name="Total Feeds", type=["numericColumn"], width=120)
        builder.configure_column("green_feeds", header_name="Green", type=["numericColumn"], width=100)
        builder.configure_column("yellow_feeds", header_name="Yellow", type=["numericColumn"], width=100)
        builder.configure_column("orange_feeds", header_name="Orange", type=["numericColumn"], width=100)
        builder.configure_column("red_feeds", header_name="Red", type=["numericColumn"], width=90)
    else:
        # minWidth is sized to fit each header label (incl. the sort/padding) so
        # the full text always shows without manual widening; flex still lets the
        # columns grow to fill extra width.
        builder.configure_column("total_feeds", header_name="Total Feeds", type=["numericColumn"], flex=count_flex, minWidth=135)
        builder.configure_column("green_feeds", header_name="Green", type=["numericColumn"], flex=count_flex, minWidth=95)
        builder.configure_column("yellow_feeds", header_name="Yellow", type=["numericColumn"], flex=count_flex, minWidth=100)
        builder.configure_column("orange_feeds", header_name="Orange", type=["numericColumn"], flex=count_flex, minWidth=105)
        builder.configure_column("red_feeds", header_name="Red", type=["numericColumn"], flex=count_flex, minWidth=90)
    # "Last Checked" is hidden on both tabs (no timestamp column in the domain master).
    builder.configure_column("last_observed_time", hide=True)


def _router_detail_grid_options() -> dict[str, Any]:
    """Device detail grid: two-column Field/Value layout (Field, Value),
    populated from the real ``DeviceRecord`` aimpoint fields (see
    ``table_data.device_field_value_rows``).
    """
    return {
        # autoHeight so the detail row grows to show every aimpoint field (the
        # parent grid's detailRowAutoHeight reads this grid's content height).
        "domLayout": "autoHeight",
        "defaultColDef": {
            "filter": True,
            "sortable": True,
            "resizable": True,
            "wrapText": False,
            "autoHeight": False,
        },
        "pagination": False,
        "rowSelection": "single",
        "suppressRowClickSelection": False,
        "columnDefs": [
            {"field": "field", "headerName": "Field", "minWidth": 180, "pinned": "left"},
            {"field": "value", "headerName": "Value", "minWidth": 260},
        ],
        "overlayNoRowsTemplate": "<span style='padding: 10px;'>No device metadata for this feed.</span>",
    }


def _feed_detail_grid_options() -> dict[str, Any]:
    """Feed detail grid: Device ID, File Count, Expected / Day, Location,
    Collection Type, Collection Region, Proxy. Location / Collection Region /
    Proxy are populated from the feed's device aimpoint.
    """
    # File Count is coloured by the feed's hidden "band" (delivered vs. expected
    # percentage), so the color migrates as today's count grows. There is no
    # separate Status column — the File Count cell's color conveys it.
    band_style = JsCode(BAND_CELL_STYLE_JS) if JsCode is not None else None
    feed_options: dict[str, Any] = {
        # autoHeight so this detail grid grows to all feeds (and its own expanded
        # device rows), and the parent domain row grows to fit it.
        "domLayout": "autoHeight",
        "defaultColDef": {
            "filter": True,
            "sortable": True,
            "resizable": True,
            "wrapText": False,
            "autoHeight": False,
        },
        "pagination": False,
        "rowSelection": "single",
        "suppressRowClickSelection": False,
        "columnDefs": [
            {"field": "feed_id", "headerName": "Device ID", "minWidth": 155, "pinned": "left", "cellRenderer": "agGroupCellRenderer"},
            {"field": "count", "headerName": "File Count", "type": "numericColumn", "width": 120, "cellStyle": band_style},
            {"field": "expected_per_day", "headerName": "Expected / Day", "type": "numericColumn", "width": 140},
            {"field": "location", "headerName": "Location", "minWidth": 170},
            {"field": "feed_type", "headerName": "Collection Type", "minWidth": 150},
            {"field": "coll_region", "headerName": "Collection Region", "minWidth": 190},
            {"field": "proxy", "headerName": "Proxy", "minWidth": 170},
            {"field": "band", "hide": True},
            {"field": "router_rows_json", "hide": True},
        ],
        "overlayNoRowsTemplate": "<span style='padding: 10px;'>No feeds for this domain.</span>",
    }
    if JsCode is not None:
        feed_options.update(
            {
                "masterDetail": True,
                "detailRowHeight": 260,
                "detailRowAutoHeight": True,
                "isRowMaster": JsCode("function(dataItem) { return true; }"),
                "onRowClicked": JsCode(FEED_ROW_CLICK_EXPAND_JS),
                "detailCellRendererParams": {
                    "detailGridOptions": _router_detail_grid_options(),
                    "getDetailRowData": JsCode(DETAIL_GET_ROUTER_ROWS_JS),
                },
            }
        )
    return feed_options


def build_domain_master_detail_grid_options(data: pd.DataFrame) -> dict[str, Any]:
    """Build AgGrid options for nested domain -> feed -> device expansion.

    Clicking a domain row toggles first-level master/detail expansion. The
    expanded detail panel is a child AgGrid feed table nested inside the same
    domain metrics table. Clicking a feed row in that child grid toggles a
    second-level detail row showing device metadata for that feed.
    Hidden nested payloads are JSON strings instead of list/dict DataFrame cells
    to avoid Streamlit non-hashable DataFrame warnings.
    """

    builder = _base_builder(data, row_id_column="domain_id")
    _configure_domain_band_columns(builder)
    # Current tab is never orange/red (green/yellow/gray only — see
    # status.current_feed_band), so hide the Orange/Red count columns. The data
    # is still present on the row (just hidden) in case they're needed later.
    builder.configure_column("orange_feeds", hide=True)
    builder.configure_column("red_feeds", hide=True)
    # Populated from any of the domain's feed devices (aimpoint collRegions / proxy).
    builder.configure_column("coll_region", header_name="Collection Region", minWidth=190)
    builder.configure_column("proxy", header_name="Proxy", minWidth=170)
    builder.configure_column("displayed_feed_rows", hide=True)
    builder.configure_column("feed_rows_json", hide=True)
    # autoHeight so the outer grid grows to fit expanded feed/device detail rows.
    builder.configure_grid_options(domLayout="autoHeight")
    if JsCode is not None:
        builder.configure_grid_options(
            masterDetail=True,
            detailRowHeight=430,
            detailRowAutoHeight=True,
            isRowMaster=JsCode("function(dataItem) { return true; }"),
            onRowClicked=JsCode(ROW_CLICK_EXPAND_JS),
            detailCellRendererParams={
                "detailGridOptions": _feed_detail_grid_options(),
                "getDetailRowData": JsCode(DETAIL_GET_FEED_ROWS_JS),
            },
        )
    return builder.build()


def _history_feed_pivot_detail_grid_options(date_headers: list[tuple[str, str]]) -> dict[str, Any]:
    """Feed×day pivot as a master/detail child grid (the History domain's feeds).

    One pinned Feed ID column and one count column per day (newest-first), cells
    coloured by the delivered-vs-expected band (gray when the feed has no
    aimpoint at all). Each feed row is expandable to its device's aimpoint
    Field/Value rows: clicking a specific DAY cell shows that exact day's aimpoint
    (``aimpoint_by_day_json``), and clicking the feed id shows the default most
    recent aimpoint (``router_rows_json``).
    """
    cell_style = JsCode(HISTORY_CELL_STYLE_JS) if JsCode is not None else None
    count_formatter = JsCode(HISTORY_COUNT_FORMATTER_JS) if JsCode is not None else None
    column_defs: list[dict[str, Any]] = [
        {"field": "feed_id", "headerName": "Feed ID", "minWidth": 160, "pinned": "left", "cellRenderer": "agGroupCellRenderer"},
    ]
    for field, header_name in date_headers:
        # Visible cell shows the delivered file count; its hidden sibling
        # "<field>__status" carries the band the cellStyle reads.
        day_column: dict[str, Any] = {
            "field": field,
            "headerName": header_name,
            "width": 90,
            "type": "numericColumn",
            "cellStyle": cell_style,
        }
        if count_formatter is not None:
            day_column["valueFormatter"] = count_formatter
        column_defs.append(day_column)
        column_defs.append({"field": f"{field}{STATUS_COLUMN_SUFFIX}", "hide": True})
    column_defs.append({"field": "router_rows_json", "hide": True})
    column_defs.append({"field": "aimpoint_by_day_json", "hide": True})

    options: dict[str, Any] = {
        # autoHeight so this pivot grows to all feeds (and its own expanded
        # device rows), and the parent domain row grows to fit it.
        "domLayout": "autoHeight",
        "defaultColDef": {"sortable": True, "resizable": True, "filter": False},
        "pagination": False,
        "rowSelection": "single",
        "suppressRowClickSelection": False,
        "columnDefs": column_defs,
        "overlayNoRowsTemplate": "<span style='padding: 10px;'>No feeds for this domain in the window.</span>",
    }
    if JsCode is not None:
        options.update(
            {
                "masterDetail": True,
                "detailRowHeight": 320,
                "detailRowAutoHeight": True,
                "isRowMaster": JsCode("function(dataItem) { return true; }"),
                # Per-day: a day-cell click drives which day's aimpoint shows.
                "onCellClicked": JsCode(HISTORY_FEED_PIVOT_CELL_CLICK_JS),
                "detailCellRendererParams": {
                    "detailGridOptions": _router_detail_grid_options(),
                    "getDetailRowData": JsCode(HISTORY_DETAIL_GET_ROUTER_ROWS_JS),
                },
            }
        )
    return options


def build_history_master_detail_grid_options(data: pd.DataFrame, date_headers: list[tuple[str, str]]) -> dict[str, Any]:
    """Build AgGrid options for the History tab's nested domain → feed → device grid.

    Mirrors the Current tab's master/detail: clicking a domain row expands its
    feed×day pivot child grid; clicking a feed row there expands that feed's
    device aimpoint detail. Hidden nested payloads
    are JSON strings (``feed_rows_json`` / ``router_rows_json``) to avoid
    Streamlit non-hashable DataFrame warnings.

    Args:
        data: the domain master DataFrame from
            :func:`~domain_feed_health_dashboard.history_data.build_history_domain_master`.
        date_headers: ``(set_date, "M/D")`` pairs newest-first for the feed
            detail grid's day columns.
    """

    builder = _base_builder(data, row_id_column="domain_id")
    # Historical columns stretch to fill the grid width (flex), with Trend 1.5×
    # the count columns.
    _configure_domain_band_columns(builder, count_flex=1)
    # Collection Region / Proxy (from any feed's device aimpoint) between Red and
    # Trend — like the Current tab, but flexed to fill the wider Historical grid.
    builder.configure_column("coll_region", header_name="Collection Region", flex=1, minWidth=200)
    builder.configure_column("proxy", header_name="Proxy", flex=1, minWidth=120)
    builder.configure_column("feed_rows_json", hide=True)
    # Last column: a pre-rendered PNG line sparkline of the domain's daily
    # delivered totals, shown as the cell's background image (the raw data-URI
    # text is blanked). Not sortable/filterable — it's a graphic. Only THIS cell
    # selects its row (onCellClicked below), so only clicking the sparkline opens
    # the enlarged plot; clicks on other cells just expand/collapse the row.
    builder.configure_column(
        "trend_img",
        header_name="Trend",
        flex=1.5,          # 1.5× the other (flex=1) columns
        minWidth=170,
        sortable=False,
        filter=False,
        valueFormatter=JsCode(TREND_HIDE_VALUE_JS) if JsCode is not None else None,
        cellStyle=JsCode(TREND_IMAGE_STYLE_JS) if JsCode is not None else None,
        onCellClicked=JsCode(TREND_CELL_CLICK_JS) if JsCode is not None else None,
    )
    # autoHeight so the grid box (and its border) hugs the rows, with no empty
    # space below the last row; taller master rows give the sparkline room.
    # suppressRowClickSelection: a plain row click no longer selects (so it won't
    # open the plot); selection happens only from the Trend cell's onCellClicked.
    builder.configure_grid_options(domLayout="autoHeight", rowHeight=40, suppressRowClickSelection=True)
    if JsCode is not None:
        builder.configure_grid_options(
            masterDetail=True,
            detailRowHeight=440,
            detailRowAutoHeight=True,
            isRowMaster=JsCode("function(dataItem) { return true; }"),
            onRowClicked=JsCode(ROW_CLICK_EXPAND_JS),
            detailCellRendererParams={
                "detailGridOptions": _history_feed_pivot_detail_grid_options(date_headers),
                "getDetailRowData": JsCode(DETAIL_GET_FEED_ROWS_JS),
            },
        )
    return builder.build()


def selected_row_value(response: Any, row_id_column: str) -> str | None:
    """Extract a selected row ID from common streamlit-aggrid response shapes."""

    if not response:
        return None

    selected_rows = None
    if isinstance(response, dict):
        selected_rows = response.get("selected_rows")
    else:
        selected_rows = getattr(response, "selected_rows", None)

    if selected_rows is None:
        return None

    if isinstance(selected_rows, pd.DataFrame):
        if selected_rows.empty or row_id_column not in selected_rows.columns:
            return None
        value = selected_rows.iloc[0][row_id_column]
        return str(value) if value is not None else None

    if isinstance(selected_rows, list):
        if not selected_rows:
            return None
        first = selected_rows[0]
        if isinstance(first, dict) and row_id_column in first:
            value = first[row_id_column]
            return str(value) if value is not None else None

    if isinstance(selected_rows, dict) and row_id_column in selected_rows:
        value = selected_rows[row_id_column]
        return str(value) if value is not None else None

    return None


def render_aggrid(
    data: pd.DataFrame,
    grid_options: dict[str, Any],
    *,
    key: str,
    height: int,
    enable_enterprise_modules: bool = False,
    fit_columns: bool = False,
) -> Any:
    """Render AgGrid and return its response object.

    ``fit_columns`` sizes the columns to fill the grid width on load (removing
    the empty space on the right when columns do not fill the grid).
    """

    if AgGrid is None or GridUpdateMode is None or DataReturnMode is None:
        raise RuntimeError("streamlit-aggrid is not installed")

    return AgGrid(
        data,
        gridOptions=grid_options,
        key=key,
        height=height,
        width="100%",
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        fit_columns_on_grid_load=fit_columns,
        allow_unsafe_jscode=True,
        enable_enterprise_modules=enable_enterprise_modules,
        theme="streamlit",
    )
