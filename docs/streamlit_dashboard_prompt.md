# Final Project Prompt: Domain Feed Health Dashboard with Streamlit AgGrid Nested Master/Detail

## Intended Coding Agent

This prompt is tool-agnostic. Use it with any coding agent or LLM tool that can read Markdown, create files, run commands, and work with a local project repository.

## Project Mode

- [ ] New Project Genesis
- [x] Existing Project Change
- [ ] Fork Existing Project Into New Project
- [ ] Audit / Evaluation Before Implementation

As of this revision, the app is wired to `acb-generator`'s real data layer (no simulated-data mode remains). This revision changes the existing AgGrid UI's column headers to match `acb-generator`'s Textual TUI, ports the Textual TUI's day-pivot history grid into AgGrid, and restructures the UI into two explicit views (Current, Historical) with a configurable 1–31-day historical window.

## Confirmed User Goal

Create a **Streamlit web app** for analysts using **AgGrid via `streamlit-aggrid`** for every interactive data grid. The app displays the real domains produced by `acb-generator`'s data layer — `Generator` (today's live in-memory tally, polled from S3) for the **Current** view and `Repository` (the 30-day SQLite history) for the **Historical** view. **No simulated, fabricated, or placeholder data exists anywhere in this app.** Each domain is color-coded as green, yellow, or red based on the worst feed/device under that domain. The dashboard summary must include an AgGrid per-domain metrics table showing each domain and its counts of red, yellow, and green feeds, using the same column headers as `acb-generator`'s existing Textual TUI (`scripts/run_generator.py`)'s `DOMAIN_COLS`. **Clicking a domain row in that table must expand the row in place and show that domain's feeds inside the same AgGrid table using master/detail row expansion. Do not implement the domain-to-feed drilldown as two separate top-level tables.** Overall dashboard metrics must be displayed as individual card-style summary tiles. Device (router access point) metadata must be shown by expanding a feed row inside the expanded domain row, creating a nested domain → feed → device drilldown inside the same AgGrid table surface, displayed as the same Field/Value layout the Textual TUI uses (`DEVICE_COLS`).

The app has exactly **two top-level views**: **Current** (today's live tally) and **Historical** (the day-pivot feed/device grid). The Historical view's day-pivot grid must be implemented in AgGrid — not `st.dataframe`/pandas `Styler` — so that it looks and behaves like the Textual TUI's `_repaint_history_feed_grid()` (one row per feed/device, one column per day, newest day first, RED/YELLOW/GREEN colored cells, click-to-drill). The Historical view defaults to a 30-day window ending yesterday (UTC) and must let the analyst configure that window to any span from 1 to 31 days back from the current day.

Real log/S3 parsing already exists in `acb-generator` (`services/generator.py`, `services/log_parser.py`, `db/repository.py`) and is explicitly out of scope to reimplement here — this app only consumes `Generator`/`Repository` output.

## Confirmed Project Brief

### 1. Summary

Build a Streamlit web app for analysts to review health status across the real domains tracked by `acb-generator`. Use `streamlit-aggrid` / AgGrid for every interactive grid: the domain metrics table with master/detail row expansion, the nested feed/device detail grids, and the Historical view's 30-day feed/device-by-day pivot grid. Each domain is color-coded red, yellow, or green based on the lowest/worst-status feed or device beneath it. The app has two views:

- **Current** — sourced from `Generator`'s live tally (today, UTC). The dashboard summary includes an AgGrid per-domain metrics table with red/yellow/green feed counts for each domain, using column headers matching the Textual TUI's `DOMAIN_COLS` (Domain, Status, Total Feeds, Red, Yellow, Green, Last Checked). Analysts click a domain row or row expander and the row expands in place to show that domain's feed rows inside the same AgGrid table, using column headers matching the Textual TUI's `FEED_COLS` (Device ID, Status, File Count, Expected / Day, Location, Collection Type, System ID, Last Checked). Device metadata must also be inspectable inline: clicking a feed row in the expanded domain detail grid must expand that feed row and show device metadata below it as Field/Value rows (matching the Textual TUI's `DEVICE_COLS` layout), without using a separate device lookup table.
- **Historical** — sourced from `Repository`'s 30-day SQLite history. An AgGrid feed/device × day pivot grid for a selected domain, newest day first, RED/YELLOW/GREEN colored cells, mirroring the Textual TUI's `_repaint_history_feed_grid()`. The window defaults to 30 days and is configurable from 1 to 31 days back from the current day.

### 2. Target Users

- Analysts reviewing domain, feed, and device (router access point) health, both today and historically.
- Operators or engineers maintaining `acb-generator`'s `Generator`/`Repository` data layer and Textual TUI.

### 3. Application Type

- Streamlit web app.
- Local deployment, reading `acb-generator`'s existing S3/SQLite-backed data layer.
- No authentication.
- No external services beyond the existing AWS S3 access `Generator` already uses.
- No new database; reads the existing SQLite database `Generator` already writes to.

### 4. Core User Workflow

1. Analyst opens the Streamlit app and lands on the **Current** view.
2. App loads real domain/feed/device data: **Current** view from a live `Generator` tally (today, UTC, polled from S3); **Historical** view from `Repository`'s 30-day SQLite history.
3. Analyst sees a dashboard summary with overall metrics and a per-domain metrics table.
4. The per-domain metrics table is implemented with AgGrid and lists the real domains currently tracked, with red/yellow/green feed counts for each domain, using the Textual TUI's `DOMAIN_COLS` headers (Domain, Status, Total Feeds, Red, Yellow, Green, Last Checked).
5. Analyst clicks/selects a domain row in the AgGrid metrics table to expand that domain row in place and reveal that domain's feed list.
6. Each domain is colored:
   - **Green** = good.
   - **Yellow** = unknown.
   - **Red** = broken.
7. Domain color is computed from feed and device statuses using this severity order:
   - Red is worst/lowest.
   - Yellow is middle/unknown.
   - Green is best/good.
8. App displays the selected/expanded domain's feeds in an AgGrid table using the Textual TUI's `FEED_COLS` headers (Device ID, Status, File Count, Expected / Day, Location, Collection Type, System ID, Last Checked).
9. Each feed row has its own red/yellow/green status.
10. Analyst selects a feed row in AgGrid.
11. App displays the device (router access point) associated with that feed inline under the expanded feed row, as Field/Value rows matching the Textual TUI's `DEVICE_COLS` layout.
12. Analyst switches to the **Historical** view.
13. Analyst selects a domain and, optionally, adjusts the history window (1–31 days back from the current day; defaults to 30).
14. App renders an AgGrid feed/device × day pivot grid for that domain and window: one row per feed/device, one column per day (newest day first), each cell colored RED/YELLOW/GREEN for that day's status, mirroring the Textual TUI's `_repaint_history_feed_grid()`.
15. Analyst clicks a row in the historical pivot grid to drill into that feed/device's detail, consistent with the Current view's drilldown pattern.

### 5. Inputs

| Input | Source | Required? | Notes |
|---|---|---:|---|
| Live domain/feed/device tally | `domain_feed_health_dashboard.services.generator.Generator` | Yes | Powers the Current view. Polls S3 and maintains an in-memory tally for the current UTC day. |
| 30-day history | `domain_feed_health_dashboard.db.repository.Repository` | Yes | Powers the Historical view. Reads the SQLite database (`domain_sets`, `devices`, `feeds`, `snapshot_meta`) the Generator pushes to at UTC midnight. |
| Domain/feed/device counts | Derived from `Generator`/`Repository` | Yes | Whatever real counts exist on a given day — no fixed/assumed domain or feed count. |
| Historical window (days) | Sidebar control | Yes | Integer 1–31, default 30. Selects how many UTC days back from the current day to render in the Historical pivot grid. |
| Simulated/fabricated data of any kind | — | No | Explicitly forbidden. No `sample_data.py`-style generator exists in this app. |

### 6. Outputs / Artifacts

| Output | Format | Required? | Notes |
|---|---|---:|---|
| Interactive dashboard | Streamlit UI with two views (Current, Historical) | Yes | Primary deliverable. |
| Dashboard summary metrics | Card-style UI metrics and AgGrid table | Yes | Overall totals in cards plus per-domain red/yellow/green feed counts, real data only. |
| Domain status view (Current) | AgGrid master/detail table | Yes | Lists every real domain currently tracked by `Generator`. |
| Feed detail table (Current) | AgGrid child grid | Yes | Columns matching the Textual TUI's `FEED_COLS` (8 columns; see Implementation Requirements §8). |
| Device detail grid (Current) | AgGrid nested detail grid, Field/Value rows | Yes | Shows device metadata under the expanded feed row, matching the Textual TUI's `DEVICE_COLS` layout. |
| Feed/device × day pivot grid (Historical) | AgGrid grid | Yes | Newest day first, RED/YELLOW/GREEN colored cells, 1–31 day configurable window (default 30). |
| File exports | CSV/JSON/etc. | No | Not required. |

### 7. Explicit Non-Goals

- Reimplementing S3/log parsing (already implemented in `Generator`/`log_parser.py`/`Repository`; this app only consumes their output).
- Authentication.
- User accounts.
- External APIs beyond the existing AWS S3 access already used by `Generator`.
- New database schemas (the existing SQLite schema in `db/schema.py` is unchanged).
- Production deployment.
- Complex alerting.
- Export workflows.
- Automated remediation.
- Network scanning.
- Live router discovery.
- Any simulated, mocked, or placeholder data path in the running app.

### 8. Definition of Done

The first working version is complete when:

- A user can run the app locally with Streamlit against `acb-generator`'s real `Generator`/`Repository` data.
- The Current view displays every real domain in the live tally, with no fixed/assumed domain count.
- The dashboard summary includes an AgGrid per-domain metrics table with red/yellow/green feed counts for every visible domain, headers matching the Textual TUI's `DOMAIN_COLS`.
- Clicking/selecting a domain row in the AgGrid metrics table expands that domain's feed list inline, in the same table.
- Each domain is colored red, yellow, or green.
- Domain color correctly reflects the lowest/worst feed or device status.
- Clicking/expanding a domain displays its AgGrid feed table with headers matching the Textual TUI's `FEED_COLS`.
- Feed tables remain usable regardless of how many real feeds a domain has.
- Clicking/selecting a feed row inside the expanded domain grid expands that feed row and displays device metadata inline as Field/Value rows, matching the Textual TUI's `DEVICE_COLS`.
- A separate Historical view exists, rendering an AgGrid feed/device × day pivot grid (newest day first, RED/YELLOW/GREEN cells) for a selected domain, sourced from `Repository`.
- The Historical view's window defaults to 30 days and is configurable from 1 to 31 days back from the current day.
- No simulated, fabricated, or placeholder data exists anywhere in the running app.
- README explains setup, run, and test commands.
- AGENTS.md exists and captures project-specific coding-agent rules.
- Basic tests or validation checks verify status rollup behavior and the historical pivot logic.

## Source Materials

This app's data layer is `acb-generator`'s existing `domain_feed_health_dashboard` package: `services/generator.py` (`Generator`), `db/repository.py` (`Repository`), `data_model.py` (`DomainRecord`/`FeedRecord`/`DeviceRecord`), and `status.py`. Its column-header and history-grid reference UI is `acb-generator`'s Textual TUI, `scripts/run_generator.py` (`DOMAIN_COLS`, `FEED_COLS`, `DEVICE_COLS`, `_repaint_history_feed_grid()`). Inspect both before changing anything; do not invent fields, commands, or behavior beyond what these source files expose.

The only sources of requirements are this prompt and the `acb-generator` source files named above.

## Non-Negotiable Rules

- Create a working Streamlit app; do not create a static mockup only.
- Use AgGrid through the `streamlit-aggrid` package for every required interactive grid, including the domain/feed/device master/detail table **and** the Historical view's feed/device × day pivot grid. Do not render the pivot grid with `st.dataframe`/pandas `Styler`.
- No simulated, fabricated, or placeholder data anywhere in the app. All data must come from `Generator` (Current view) or `Repository` (Historical view).
- AgGrid column headers for the domain and feed grids must match the Textual TUI's `DOMAIN_COLS`/`FEED_COLS` labels; the device detail grid must use the Textual TUI's `DEVICE_COLS` two-column Field/Value layout. Where a Textual-pipeline field (e.g. `hp_id`, `collection_enabled`) has no equivalent on `DomainRecord`/`FeedRecord`/`DeviceRecord`, do not invent it — use the real field that documented evidence shows is the closest equivalent (see field-mapping tables below), or omit the row/column and note the gap.
- Do not add authentication, external APIs beyond existing S3 access, new databases/schemas, network scanning, or live router discovery.
- No fake success messages.
- No placeholder-only functions that pretend to work.
- Do not invent external services, credentials, private APIs, or datasets.
- Prefer simple architecture unless the requirements clearly demand complexity.
- Keep the app narrow, runnable, and testable.
- The per-domain metrics table is required; do not replace it with cards only.
- The per-domain metrics table must be an AgGrid table with row selection enabled.
- The feed detail grid must be an AgGrid child grid with row expansion enabled for device metadata.
- Domain row expansion from the metrics table must reliably reveal the selected domain's feed grid inline; feed row expansion must reveal device metadata inline.
- The app must expose exactly two views — Current and Historical — clearly distinguished (e.g. tabs), not blended into one scrolling page.
- The Historical view's window control must default to 30 days and accept any value from 1 to 31 days back from the current day.
- Add tests appropriate for the selected stack, including the historical pivot logic.
- Create an `AGENTS.md` file for future coding-agent work.
- Create a `README.md` with setup, run, and test instructions.
- Run available validation commands and report results honestly.
- Clean cache/build artifacts before final packaging or final reporting.

## Implementation Requirements

### 1. Project structure

This app lives inside `acb-generator`'s existing `domain_feed_health_dashboard` package — do not create a separate repository or a second copy of the data layer.

```text
src/domain_feed_health_dashboard/
  __init__.py
  app.py             # Streamlit entry point -> ui.main().
  data_model.py       # Existing: DomainRecord / FeedRecord / DeviceRecord. Do not modify
                       # unless a concrete, evidenced gap is found (see field-mapping tables below).
  status.py            # Existing: STATUS_SEVERITY, domain_status_from_feeds, build_domain_summary,
                        # overall_metrics. Unchanged — shared by both views.
  grid_config.py        # AgGrid GridOptionsBuilder helpers for the Current-view master/detail
                         # table AND the Historical-view day-pivot grid (new columnDefs needed).
  table_data.py          # domain_master_detail_dataframe(), feed_detail_rows(), router_rows() —
                          # column labels updated to match Textual TUI headers (see below).
  history_data.py         # Existing: feed/device x day pivot builder, sourced from Repository.
                           # Add an AgGrid-options builder alongside the existing pandas Styler
                           # helper (or replace it), parameterized by a 1-31 day window.
  ui.py                    # Sidebar controls, CSS, overall-metric cards, two-view (Current/
                            # Historical) layout, render functions for both AgGrid grids.
  services/generator.py     # Existing: Generator — do not modify.
  db/repository.py           # Existing: Repository — do not modify.
tests/
  test_status.py
  test_table_data.py
  test_grid_config.py
  test_history_data.py
```

A different clean structure is acceptable only if it remains simple, documented, easy to run, and does not duplicate or fork `Generator`/`Repository`/`status.py`.

### 2. Use Streamlit with AgGrid

Implement the dashboard using Streamlit and AgGrid via the `streamlit-aggrid` package. Use Streamlit for layout, controls, metrics, page structure, and the Current/Historical view switch (e.g. `st.tabs(["Current", "Historical"])`). Use AgGrid for every required interactive data grid.

At minimum, the implementation must import and use `AgGrid` from `st_aggrid` for:

- the per-domain metrics table (Current view),
- the expanded selected-domain feed table (Current view),
- the expanded selected-feed device detail grid (Current view),
- the feed/device × day pivot grid (Historical view).

Use `GridOptionsBuilder` or equivalent AgGrid configuration to enable single-row selection, sortable/filterable columns, pagination where useful, readable column sizing, and clear status display.

The user should be able to run the app with a command equivalent to:

```bash
streamlit run src/domain_feed_health_dashboard/app.py
```

If using a package entry point or another command, document it clearly in `README.md`.

AgGrid behavior requirements:

- The domain summary grid must return selected row data and update the selected domain.
- The feed grid must return selected row data and update the selected feed.
- Use stable row identifiers such as `domain_id` and `feed_id` rather than relying on visible row indexes.
- Configure grid options in a reusable helper, such as `grid_config.py`, if it keeps `ui.py` simpler.
- Do not duplicate business logic in AgGrid callbacks; keep rollup/status logic in testable Python functions.

### 3. Source real data from `Generator` and `Repository`

No data is generated, simulated, or fabricated by this app.

- **Current view**: construct a `Generator` (same `S3_BUCKET`/`db_path` conventions already used in `services/generator.py` and `ui.py`'s existing `_get_generator()`), and read `generator.tally.to_domain_records()` for the live, in-memory, today's-UTC-day tally.
- **Historical view**: construct a `Repository` against the same SQLite `db_path`, and read `repository.available_dates()` / `repository.get_history_domains(set_date=...)` for completed UTC days.
- Domain, feed, and device counts are whatever the real data contains on a given day — do not assume or hardcode a domain or feed count anywhere in the UI or its tests (use fixture data with varied counts for tests instead).
- Do not add a sidebar/config option to switch into a simulated-data mode. If `Generator`/`Repository` cannot be reached (e.g. no S3/SQLite access), show a clear error state — do not fall back to fabricated data.

### 4. Status severity and rollup logic

This logic already exists in `status.py` and is shared by both views; do not duplicate or reimplement it.

| Status | Meaning | Severity |
|---|---|---:|
| green | good feed/device | 1 |
| yellow | unknown feed/device | 2 |
| red | broken feed/device | 3 |

Domain status rule (`domain_status_from_feeds`):

- Domain status = worst(feed status, device status) across all feeds in the domain — a red device on an otherwise-green feed still makes the domain red.
- If a domain has zero feeds, it is yellow (health unknown).

Add tests for this logic only if a gap is found; `tests/test_status.py` should already cover it.

### 5. Dashboard summary and per-domain metrics table (Current view)

The Current view must include a top-level summary area before the expanded domain/feed details.

Include two parts:

1. Overall summary metrics, such as total domains, total feeds, red domains, yellow domains, green domains, red feeds, yellow feeds, and green feeds. Each overall metric must be displayed inside a distinct card-style tile rather than as plain text only.
2. A per-domain metrics table with one row per real domain currently in `Generator`'s tally.

The per-domain metrics table's AgGrid `columnDefs` must use the Textual TUI's `DOMAIN_COLS` headers, mapped to the real `DomainRecord`/`status.build_domain_summary` fields:

| Textual header (`DOMAIN_COLS`) | AgGrid `field` (`status.summarize_domain` output) |
|---|---|
| Domain | `domain_name` |
| Status | `domain_status` (or `status_label` for the icon+text variant already used today) |
| Total Feeds | `total_feeds` |
| Red | `red_feeds` |
| Yellow | `yellow_feeds` |
| Green | `green_feeds` |
| Last Checked | `last_observed_time` |

The table must be implemented with AgGrid. It must support clicking a domain row or expander icon. When the analyst clicks a domain, the same row must expand in place and show the feed grid for that domain inside the same table surface.

AgGrid implementation requirements:

- Use `AgGrid` from `st_aggrid`; do not rely on `st.dataframe` as the primary implementation for this required table.
- Enable single-row selection.
- Preserve or stabilize row identity (`domain_id`) so AgGrid expansion remains consistent across reruns.
- Configure columns so numeric counts are sortable and status/domain columns are readable.
- Use pagination, quick filtering, or grid sizing as needed to keep however many real domains exist easy to scan.
- Make the selected row obvious in the UI.

Fallback rule:

- A selectbox/dropdown fallback may only be added as a supplemental reliability fallback if AgGrid selection is unavailable in the runtime environment. The AgGrid table must still exist.

The metrics table is required and must not be replaced by cards only. Cards/badges may be added as supplemental visuals.

### 6. Domain list UI (Current view)

The Current view must show every real domain currently in `Generator`'s tally — no fixed or assumed count.

Each domain should display:

- Domain name.
- Domain status: red/yellow/green.
- Feed count.
- Counts of green/yellow/red feeds.
- Last checked / last observed time.

Use visual status indicators that are easy for an analyst to scan. Examples:

- colored badges,
- status icons,
- colored left border,
- compact cards,
- Streamlit expanders with status labels.

The UI should feel like an analyst/operator dashboard, not a toy demo.

### 7. Filtering and search

Add basic dashboard controls (Current view):

- Search domains by name.
- Filter domains by computed domain status.
- Optional checkbox to show only domains with red feeds.
- Optional control to limit how many feed rows are displayed at once for very large domains.

Filters must update both the visible domain list/detail area and the per-domain metrics table, or the UI must clearly label which areas are filtered versus unfiltered.

### 8. Expanded domain feed table (Current view)

When a user expands or clicks a domain, display its feed table using AgGrid.

Each feed row must have its own red/yellow/green status.

The feed table's AgGrid `columnDefs` must use the Textual TUI's `FEED_COLS` headers (8 columns, intentionally not padded to a different count to preserve Textual parity), mapped to the real `FeedRecord`/`DeviceRecord` fields:

| Textual header (`FEED_COLS`) | AgGrid `field` | Real source |
|---|---|---|
| Device ID | `feed_id` | `FeedRecord.feed_id` |
| Status | `status_label` | `FeedRecord.status` (worst of feed/device status) |
| File Count | `count` | `FeedRecord.count` |
| Expected / Day | `expected_per_day` | `FeedRecord.routers[0].files_expected` if a device is attached, else blank — **gap**: `FeedRecord` itself has no per-feed expected value; do not invent one (see Modification v7 below). |
| Location | `location` | `FeedRecord.location` |
| Collection Type | `feed_type` | `FeedRecord.feed_type` |
| System ID | `source_system` | `FeedRecord.source_system` |
| Last Checked | `observed_time` | `FeedRecord.observed_time` |

The AgGrid table should remain usable regardless of how many real feeds exist for a domain. Configure pagination, column sizing, sortable/filterable columns, and single-row selection to support large domains.

If a domain has zero feeds, display a clear empty-state message instead of failing.

### 9. Feed selection

A feed must be selectable/clickable so the analyst can inspect device (router access point) metadata.

AgGrid implementation requirements:

- Use `AgGrid` from `st_aggrid` for feed row selection; do not rely on `st.dataframe` as the primary feed-selection UI.
- Enable single-row selection for feeds.
- Store selected feed identity in `st.session_state`.
- Reset or validate selected feed state when the selected domain changes.
- Configure the grid with pagination or a bounded height so domains with many real feeds remain usable.

Fallback rule:

- A selectbox/dropdown fallback may only be added as a supplemental reliability fallback if AgGrid selection is unavailable in the runtime environment. The AgGrid feed table must still exist.

The feed selection behavior must be reliable and documented.

### 10. Device (router access point) details

Clicking a feed row inside the expanded domain detail grid displays the associated device (router access point) inline under that feed row, **as Field/Value rows** — matching the Textual TUI's `DEVICE_COLS` (`Field`, `Value`) layout, not a flat multi-column row. This intentionally differs from the prior flat-column router grid: the Textual TUI renders one device as a vertical list of (label, value) pairs, and this AgGrid detail grid must reproduce that look.

A selected feed has 0 or 1 real device (`FeedRecord.routers` — at most one `DeviceRecord`, despite the tuple type). Use these Field/Value rows, sourced from the real `DeviceRecord` (the Textual TUI's `DEVICE_COLS` rows come from a different, unrelated pipeline's `AimpointRecord` and are **not** field-compatible — see Modification v7 below for the full gap analysis):

| Field | Value source (`DeviceRecord`) |
|---|---|
| Device ID | `device_id` |
| Hostname | `hostname` |
| IP Address | `ip_address` |
| MAC Address | `mac_address` |
| Vendor | `vendor` |
| Model | `model` |
| Firmware Version | `firmware_version` |
| Interface | `interface` |
| Uptime | `uptime` |
| Last Seen Time | `last_seen_time` |
| Health Status | `health_status` |
| Op Window Start | `op_window_start` |
| Op Window End | `op_window_end` |
| Files Actual | `files_actual` |
| Files Expected | `files_expected` |
| Notes | `notes` |

Display the device's Field/Value rows in a nested AgGrid detail grid (two columns: `field`, `value`) below the clicked feed row. Do not use a separate top-level device lookup table or detail panel for the primary device drilldown. If a selected feed has no device, show a clear empty-state message in the nested detail area.

### 11. Historical view: feed/device × day pivot grid (AgGrid)

The Historical view is a separate top-level view from Current (e.g. a second `st.tabs(...)` entry), not a section appended below the Current view on the same page.

Build it from `Repository.available_dates()` and `Repository.get_history_domains(set_date=...)` only — never from `scripts/run_generator.py`'s separate `AimpointRecord`/S3-scanning pipeline, which uses a different cache file and is not guaranteed to agree with `Repository`'s counts.

Requirements:

- A domain selector (e.g. `st.selectbox`), populated from `history_data.domain_ids_with_history(repository)` or equivalent.
- A history-window control defaulting to **30 days** and configurable from **1 to 31 days** back from the current day (e.g. `st.slider("History window (days)", min_value=1, max_value=31, value=30)`). Pass this value into the pivot builder (`history_data.build_feed_history_pivot(repository, domain_id, max_days=window)`).
- The pivot grid itself **must be rendered with AgGrid**, not `st.dataframe` or a pandas `Styler` — this is the capability being ported from the Textual TUI's `_repaint_history_feed_grid()` into the web UI:
  - One row per feed (or per device, if that is the more useful grain — match whichever grain `_repaint_history_feed_grid()` uses for the selected domain).
  - One pinned identifier column (`feed_id` or `device_id`), then one column per day in the window, **newest day first** (left-to-right), matching `_repaint_history_feed_grid()`'s `days_newest_first = list(reversed(window))` ordering.
  - Each day cell shows that day's status for the row (e.g. a short `R`/`Y`/`G` label or the raw count, consistent with the existing accessibility convention of pairing color with text) and is colored RED/YELLOW/GREEN via an AgGrid `cellStyle` JS callback, mirroring `grid_config.STATUS_STYLE_JS`/`DETAIL_STATUS_STYLE_JS`.
  - A day with no data for that row renders an empty-state marker (e.g. `—`), not a blank cell that could be mistaken for green.
  - Clicking a row should be able to drill into that feed/device's detail (e.g. expand a detail row, or update a selection used elsewhere on the page), consistent with the Current view's click-to-drill pattern — this is the specific Textual-TUI capability ("click row for device details") being ported, not just the static coloring.
- If the selected domain has no history in the configured window, show a clear empty-state message instead of an empty or broken grid.

### 12. Overall dashboard metrics

Add compact top-level overall metrics such as:

- Total domains.
- Total feeds.
- Red domains.
- Yellow domains.
- Green domains.
- Red feeds.
- Yellow feeds.
- Green feeds.

These overall metrics are separate from, and supplemental to, the required per-domain metrics table described above. Each metric must be contained in a visible card. The summary should update according to current filters only if that makes sense; otherwise document whether it reflects all visible (filtered) real domains or every real domain.

### 13. Visual design guidance

Aim for a professional analyst dashboard.

Do:

- Use a clear page title and short subtitle.
- Use compact sections.
- Use consistent status labels and colors.
- Keep dense data readable.
- Make the Current/Historical view distinction obvious (e.g. tab labels, not just a scroll position).
- Avoid clutter.

Avoid:

- Toy-like language.
- Excessive animations.
- Hard-to-read color combinations.
- Unclear status semantics.
- Hidden controls that make the app hard to evaluate.

### 14. Tests

Add tests for the core non-UI logic.

At minimum test:

- Domain status is red if any feed or device is red.
- Domain status is yellow if no red feeds/devices exist but at least one yellow feed/device exists.
- Domain status is green if all feeds and devices are green and at least one feed exists.
- Domain status is yellow when a domain has zero feeds.
- Per-domain summary counts correctly count red, yellow, and green feeds, using fixture `DomainRecord`/`FeedRecord`/`DeviceRecord` objects (no live S3/SQLite calls).
- The AgGrid `columnDefs` for the domain, feed, and device-detail grids expose the field/headerName pairs documented in Implementation Requirements §5/§8/§10.
- The historical pivot builder (`history_data.build_feed_history_pivot`) honors a configurable day window from 1 to 31, defaults to 30, orders columns newest-first, and marks missing days distinctly from a real status.
- Selecting a domain identifier updates the selected-domain state or equivalent non-UI selection helper, if such logic is separated from the Streamlit UI.

Use `pytest` unless there is a strong reason not to. Use `moto[s3]` or fixture/mock `Repository`/`Generator` objects — no live AWS credentials required for any test.

### 15. Documentation

Create `README.md` with:

- Project overview.
- Clear statement that this app reads real `Generator`/`Repository` data only — no simulated-data mode exists.
- Requirements.
- Setup instructions.
- Run command.
- Test command.
- Project structure.
- Status semantics.
- The Current vs. Historical view distinction and the 1–31 day configurable history window.
- Known limitations.
- Future work ideas.

Create `AGENTS.md` with:

- Project purpose.
- Coding rules.
- No simulated-data path may be reintroduced.
- The two-pipeline architecture note (this app uses `Generator`/`Repository`; `scripts/run_generator.py`'s separate `AimpointRecord` pipeline is a different, untouched system).
- How to run and test the project.
- Areas future agents should avoid changing without confirmation (`scripts/run_generator.py`, `db/schema.py`).

### 16. Dependency and tooling expectations

Use a simple dependency setup. All required dependencies are already declared in `acb-generator/pyproject.toml`:

- `streamlit`
- `streamlit-aggrid`
- `pandas`
- `pytest`
- `boto3` / `botocore` (already used by `Generator`)

Do not add a new runtime dependency without first checking whether one of these already covers the need. Do not add heavy frontend build tooling.

### 17. Accessibility and usability

- Do not rely on color alone. Include text labels such as `RED / Broken`, `YELLOW / Unknown`, and `GREEN / Good` (and the historical pivot's short `R`/`Y`/`G` labels).
- Tables should have readable column names, matching the Textual TUI headers per the mapping tables above.
- Empty states must be clear.
- Domains/feeds with large real counts should not make the UI unusable.

## Explicit Non-Goals

- Do not implement new log ingestion or S3-scanning logic (already implemented in `Generator`/`log_parser.py`).
- Do not connect to routers.
- Do not scan networks.
- Do not implement remediation workflows.
- Do not add login/authentication.
- Do not add a new database or schema (the existing SQLite schema in `db/schema.py` is unchanged).
- Do not add cloud deployment.
- Do not add CSV/JSON exports unless doing so is trivial and does not distract from the app.
- Do not use vendor-specific APIs beyond the existing AWS S3 access already used by `Generator`.
- Do not reintroduce a simulated-data mode of any kind.
- Do not build the Historical view from `scripts/run_generator.py`'s separate `AimpointRecord`/`scan_deliveries` pipeline.

## Assumptions and Confirmed Defaults

| Item | Assumption or Default | Confirmed by User? | Notes |
|---|---|---:|---|
| Project name | Domain Feed Health Dashboard | Yes, default accepted | Working title. |
| Project type | Web app | Yes | User requested web app. |
| Framework | Streamlit + AgGrid (`streamlit-aggrid`) | Yes | User requested Streamlit and later requested AgGrid in Streamlit. |
| Users | Analysts | Yes | Analyst-facing UI. |
| Data source | Real `Generator` (Current) / `Repository` (Historical) data from `acb-generator` | Yes | No simulated data anywhere in the app. |
| Domain/feed counts | Whatever the real data contains | Yes | No fixed/assumed count anywhere in the UI. |
| Per-domain metrics table | Required AgGrid table, headers matching Textual TUI `DOMAIN_COLS` | Yes | Must show red/yellow/green feed counts per domain and drive domain detail selection. |
| Domain status rollup | Worst feed/device status determines domain color | Yes | Red worst, yellow unknown, green good. |
| Zero-feed domain status | Yellow / unknown | Defaulted | Necessary because no feed exists to compute a lowest feed. |
| Feed table columns | 8 columns matching Textual TUI `FEED_COLS` | Yes | Intentionally not the prior 10-column layout; Textual-header parity takes precedence. |
| Device detail layout | Field/Value rows matching Textual TUI `DEVICE_COLS` | Yes | Content uses real `DeviceRecord` fields, since Textual's own `DEVICE_COLS` rows are sourced from a field-incompatible separate pipeline (see Modification v7). |
| Views | Two: Current and Historical | Yes | Mirrors the Textual TUI's Today/History tabs. |
| Historical window | Default 30 days, configurable 1–31 days back from current day | Yes | Matches `scripts/run_generator.py --days` default and `Repository`'s 30-day retention. |
| Historical grid implementation | AgGrid (not `st.dataframe`/pandas `Styler`) | Yes | Required to port the Textual TUI's day-pivot capability, not just its visual coloring. |
| Authentication | None | Yes | User said no. |
| Outputs/exports | None required | Yes | UI only. |

## Stop Conditions

Stop and ask for clarification if:

- the implementation would require new S3/log parsing or schema changes beyond consuming `Generator`/`Repository`,
- the implementation would require external credentials beyond the existing S3 access `Generator` already uses,
- requirements conflict with the "real data only, two views" scope confirmed above,
- AgGrid/`streamlit-aggrid` cannot support a reliable domain/feed row-selection interaction, or cannot support a day-pivot grid with per-cell styling, without changing the UI approach,
- a `DOMAIN_COLS`/`FEED_COLS`/`DEVICE_COLS` field has no reasonable real-data equivalent beyond what's documented in Modification v7 below,
- safety concerns arise around live router discovery or network scanning.

## Diff Discipline

This changes the existing `acb-generator` `domain_feed_health_dashboard` package — it is not a new project. Make the smallest coherent diff against the existing `app.py`/`ui.py`/`grid_config.py`/`table_data.py`/`history_data.py`.

- Do not add unused scaffolding.
- Do not add unrelated example apps.
- Do not add cache directories.
- Do not commit virtual environments.
- Do not add generated build artifacts.
- Do not reformat unrelated files or rename unrelated symbols.
- Keep files small and understandable.
- Every file must have a clear purpose.

## Regeneration Readiness

The resulting project should be understandable and reproducible by another coding agent.

At minimum, include:

- `README.md`
- `AGENTS.md`
- setup instructions
- run instructions
- test instructions
- project structure explanation
- status rollup explanation
- known limitations
- future work notes

## Validation Matrix

| Validation | Command or Method | Required? | Expected Result |
|---|---|---:|---|
| Install dependencies | `pip install -e ".[dev]"` (from `acb-generator/`) | Yes | Dependencies install successfully; no new dependencies needed. |
| Run tests | `python -m pytest` | Yes | All tests pass, including coverage for the Textual-parity column mapping and the historical pivot's configurable 1–31 day window. |
| Run Streamlit smoke test | `streamlit run src/domain_feed_health_dashboard/app.py` | Yes | App starts without import/runtime errors and renders real `Generator`/`Repository` data — not simulated data — in both the Current and Historical views. |
| Historical AgGrid check | Manual review / UI walkthrough | Yes | The Historical view's feed/device × day pivot is rendered with AgGrid (not `st.dataframe`/`Styler`), newest day first, RED/YELLOW/GREEN colored cells, window defaulting to 30 and adjustable from 1 to 31. |
| Textual TUI unaffected | Inspect `scripts/run_generator.py` diff | Yes | Zero diff against its pre-change state. |
| Lint/typecheck | Use only if configured | No | Report result if run. |
| Documentation check | Manual review | Yes | README and AGENTS.md match actual code and commands. |

If a command cannot be run in the environment, state that honestly and explain why.

## Repository Cleanliness Gate

Before packaging or final reporting:

- remove `__pycache__` directories,
- remove `.pytest_cache`,
- remove virtual environments,
- remove build artifacts unless required,
- remove temporary files,
- remove secrets or local credentials,
- confirm the final repository does not include junk artifacts.

## Final Response Requirements for the Coding Agent

Report:

- what changed,
- files changed/created and why,
- commands to install, run, and test,
- validation commands actually run,
- validation results,
- the exact field mappings applied for any Textual-header column that has no direct real-data equivalent (see Modification v7),
- confirmation that `scripts/run_generator.py` is byte-for-byte unchanged,
- known limitations,
- cleanup performed.


## Modification v4: Required AgGrid Master/Detail Behavior

The domain metrics table must use AgGrid master/detail row expansion. Clicking a domain row, or its expander icon, must expand that same row and render the domain's feed list inline beneath it. This replaces the earlier two-table design where selecting a domain in one table displayed a separate feed table elsewhere on the page. The feed child grid should support sorting/filtering/resizing where practical. Domains with zero feeds should still be represented in the metrics table and should expand to an empty or clear “no feeds” child area.

> **Superseded by Modification v7 below:** the feed child grid is no longer a fixed 10-column layout — its columns now match the Textual TUI's 8-column `FEED_COLS` headers.

Router access point metadata must be displayed through feed-row expansion inside the expanded domain feed grid. Do not reintroduce a separate top-level feed table or separate router lookup table unless the user explicitly asks for that behavior.


## Modification v5: Metric Cards and Nested Feed-to-Router Expansion

Add the following requirements on top of the prior AgGrid master/detail behavior:

1. Overall metrics at the top of the UI must be displayed as individual card-style summary tiles. Do not render the top metrics as bare `st.metric` blocks without a card container.
2. The per-domain metrics table remains the primary drilldown surface.
3. Clicking a domain row expands that row in place and shows that domain's feeds inside the same AgGrid table.
4. Clicking a feed row inside the expanded domain detail grid expands that feed row in place and shows router access point metadata for that feed.
5. The primary drilldown path must be nested: domain row → feed rows → device/router rows.
6. Do not implement the device/router information as a separate top-level lookup table, side panel, or separate feed-selection workflow unless explicitly requested later.
7. Continue to avoid live router access, network scanning, credentials, or external services beyond the S3 access `Generator` already uses.

> **Superseded by Modification v7 below:** item 7 originally said "keep all records simulated for Version 1." That requirement is reversed — no simulated data is permitted anywhere in this app; all records come from `Generator`/`Repository`.


### Hash-safe nested AgGrid payload requirement

For AgGrid master/detail data, do **not** place Python `list` or `dict` objects directly inside pandas DataFrame cells. Streamlit may attempt to hash those DataFrames and emit warnings such as `DataFrame contains non-hashable data`. Instead:

- Keep the visible parent grid data as normal scalar DataFrame columns.
- Store hidden nested domain-to-feed and feed-to-router payloads as JSON strings, for example `feed_rows_json` and `router_rows_json`.
- Parse those JSON strings inside AgGrid JavaScript `getDetailRowData` callbacks before calling `params.successCallback(...)`.
- Add tests that verify the DataFrame used for AgGrid contains no list/dict cells and can be hashed with `pandas.util.hash_pandas_object`.
- This applies equally to the Historical view's day-pivot grid if its per-row, per-day detail is ever nested rather than flattened into one row per day-column.


## Modification v7: Real-Data Sourcing, Textual-TUI Column Parity, AgGrid-Ported History Grid, and Current/Historical Views

This modification supersedes every remaining reference to simulated/fabricated data elsewhere in this document (the original body, and item 7 of Modification v5) and makes five changes:

### 1. No simulated data anywhere

Remove every simulated/fabricated data path. All domain, feed, and device data must come from `acb-generator`'s real data layer:

- **Current view** → `domain_feed_health_dashboard.services.generator.Generator` (live, in-memory, today's UTC tally, polled from S3).
- **Historical view** → `domain_feed_health_dashboard.db.repository.Repository` (read-only SQLite, 30-day retention, populated by `Generator` at UTC midnight).

Do not port `sample_data.py` or any equivalent generator. Do not add a "demo mode" toggle.

### 2. AgGrid columns match the Textual TUI's headers

`acb-generator`'s Textual TUI (`scripts/run_generator.py`) already defines three reference column sets for its own (separate) `AimpointRecord` pipeline:

```python
DOMAIN_COLS = {"domain": "Domain", "status": "Status", "total_feeds": "Total Feeds",
               "red": "Red", "yellow": "Yellow", "green": "Green", "last_checked": "Last Checked"}
FEED_COLS   = {"device_id": "Device ID", "status": "Status", "file_count": "File Count",
               "expected": "Expected / Day", "location": "Location", "coll_type": "Collection Type",
               "system_id": "System ID", "last_checked": "Last Checked"}
DEVICE_COLS = {"field": "Field", "value": "Value"}
```

The AgGrid UI's `headerName`s must match these labels. The **field-level data** comes from the real, field-compatible `DomainRecord`/`FeedRecord`/`DeviceRecord` pipeline (`Generator`/`Repository`), not from `AimpointRecord` — these are two independent pipelines reading overlapping but not identical data, per `acb_generator_final_prompt.md`'s existing architectural note. Do not wire this AgGrid UI to `AimpointRecord`, `scan_deliveries`, or `aimpoint_cache.sqlite3`.

**Domain grid** — direct match, no gaps:

| `DOMAIN_COLS` header | Real field (`status.summarize_domain`) |
|---|---|
| Domain | `domain_name` |
| Status | `domain_status` / `status_label` |
| Total Feeds | `total_feeds` |
| Red | `red_feeds` |
| Yellow | `yellow_feeds` |
| Green | `green_feeds` |
| Last Checked | `last_observed_time` |

**Feed grid** — one confirmed gap (`Expected / Day`):

| `FEED_COLS` header | Real field (`FeedRecord`/`DeviceRecord`) | Gap? |
|---|---|---|
| Device ID | `feed_id` | No — relabel only. |
| Status | `status` (worst of feed/device) | No. |
| File Count | `count` | No. |
| Expected / Day | — | **Yes.** `FeedRecord` has no per-feed expected value. Derive it from the attached device's `files_expected` (`feed.routers[0].files_expected`) when a device exists; render blank/`—` when it does not. Do not invent a synthetic expected value. |
| Location | `location` | No. |
| Collection Type | `feed_type` | No — relabel only. |
| System ID | `source_system` | No — relabel only. |
| Last Checked | `observed_time` | No — relabel only. |

**Device detail** — `DEVICE_COLS` is a two-column Field/Value *layout*, not a field list, so there is no field-name gap to fix — but the Textual TUI's actual device *rows* (`_build_device_rows`) are populated from `AimpointRecord` fields (`hp_id`, `collection_enabled`, `collection_type`, `coll_regions`, `long_lat`, `decoy`, `proxy`, `single_collector`, `dst_bucket`, `delivery_key`, `bucket_prefix_template`, `filename_base`, `final_file_suffix`, `last_monitored`, `moved_to_monitored`) that **do not exist** on the real `DeviceRecord`. Port the Field/Value *capability* (two-column key/value AgGrid detail grid), not those specific rows. Populate it from `DeviceRecord`'s real fields instead: `device_id`, `hostname`, `ip_address`, `mac_address`, `vendor`, `model`, `firmware_version`, `interface`, `uptime`, `last_seen_time`, `health_status`, `op_window_start`, `op_window_end`, `files_actual`, `files_expected`, `notes` (full mapping in Implementation Requirements §10).

### 3. Port the Textual TUI's history-grid capability into AgGrid

`_repaint_history_feed_grid()` in `scripts/run_generator.py` is the reference behavior: one row per device/feed, one column per day (newest day first), cells showing that day's count colored RED/YELLOW/GREEN, and click-to-drill into device detail. The existing `history_data.py`/`ui.py` already build an equivalent pivot (`build_feed_history_pivot`), but render it with a pandas `Styler` via `st.dataframe`. That rendering must be replaced with (or supplemented by) an AgGrid grid built with `grid_config`-style `columnDefs`/`cellStyle` JS, so the web UI looks and behaves like the Textual TUI's grid, not like a static styled table. See Implementation Requirements §11 for the full column/behavior spec.

### 4. Two views: Current and Historical

Restructure the single scrolling page into two explicit views — e.g. `tab_current, tab_historical = st.tabs(["Current", "Historical"])` — mirroring the Textual TUI's `TabbedContent` with `TabPane("Today", ...)` / `TabPane("History", ...)`. The Current view holds the domain/feed/device master-detail grid and its overall-metric cards; the Historical view holds the domain selector, the history-window control, and the AgGrid day-pivot grid.

### 5. Configurable historical window: default 30, range 1–31

The Historical view's window control must default to 30 days and accept any integer from 1 to 31, counting back from the current day (mirrors `scripts/run_generator.py`'s `--days` flag, default 30, and `Repository`'s 30-day retention ceiling — 31 is allowed as the practical upper bound since `Repository` never retains more than 30 completed days plus today). Pass the chosen value as `max_days` into `history_data.build_feed_history_pivot(repository, domain_id, max_days=window)` (or the AgGrid-equivalent builder from item 3 above).

### Required Devil's-Advocate Check Before Implementing This Modification

| Question | Answer |
|---|---|
| Does any Textual-header column require inventing data that doesn't exist on `DomainRecord`/`FeedRecord`/`DeviceRecord`? | Only `Expected / Day` lacks a direct field; it is derived from the attached device's real `files_expected`, not invented. |
| Does porting `DEVICE_COLS`'s layout require porting `AimpointRecord`-only fields? | No — port the two-column Field/Value layout only; populate it with real `DeviceRecord` fields. |
| Does the new Historical AgGrid grid read from `scripts/run_generator.py`'s pipeline? | No — it must read only from `Repository`. |
| Does any change here touch `scripts/run_generator.py` or `db/schema.py`? | No — both remain unmodified. |

