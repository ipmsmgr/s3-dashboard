# AGENTS.md

## Project purpose

Maintain a live operator dashboard for domain/feed/device (aimpoint) health backed by real
delivery and aimpoint data in S3. A single Streamlit + AgGrid web UI
(`src/domain_feed_health_dashboard/app.py`) over the `Generator` (live S3 tally) + `Repository`
(30-day SQLite history) pipeline.

## Non-negotiable scope rules

- Do not add a simulated/demo-data mode. The dashboard must only ever show real data.
- The `devices` table in `db/schema.py` stores the **full aimpoint structure** as raw JSON in a
  single `aimpoint_json` column (see `aimpoint_structure.txt`), plus the device's status and
  file-count metrics and the derived op window. The device panel is rendered by flattening
  `aimpoint_json` (`table_data._flatten_aimpoint`) — adding an aimpoint field needs no schema/model
  change. Do not reintroduce per-field aimpoint columns, and do not change this schema or its
  **30-day retention contract** without a clear, evidence-backed reason.
- Keep non-UI logic (status/band rollups, table/pivot shaping, parsing) importable and testable
  without a running Streamlit session. `ui.py` itself is not unit tested, by convention — see
  `table_data.py`, `grid_config.py`, `history_data.py`, `status.py` for the testable layer.
- Do not store nested list/dict objects directly in pandas DataFrame cells for AgGrid
  master/detail data; serialize hidden nested payloads as JSON strings (`feed_rows_json`,
  `router_rows_json` — see `table_data.py`/`history_data.py`) and parse them in AgGrid JavaScript
  detail callbacks.
- `RouterAccessPoint` is an alias for `DeviceRecord` (see `data_model.py`). Real device records
  use `device_id`, not `router_id` — do not reintroduce a `router_id` field.
- The device detail is a two-column Field/Value layout showing the real aimpoint structure parsed
  from the S3 aimpoint JSON by the `Generator`/`Repository` pipeline. `Expected / Day` /
  `Files Expected` are derived from the aimpoint's working hours — do not invent a new field.
- The dashboard has exactly two tabs — Current and Historical. The Historical tab's day-pivot
  window defaults to 30 days and is configurable from 1 to 31 (`history_data.py`'s
  `DEFAULT_HISTORY_WINDOW_DAYS`/`MIN_HISTORY_WINDOW_DAYS`/`MAX_HISTORY_WINDOW_DAYS`) — keep the
  sidebar slider's bounds in sync with those constants rather than hardcoding 1/31 elsewhere.

## Coding rules

- Prefer small, readable modules.
- Use deterministic test fixtures (literal `DomainRecord`/`FeedRecord`/`DeviceRecord` objects, or
  a temporary SQLite database via `db.schema.open_db`) — no live AWS calls in tests. `moto[s3]`
  is available as a dev dependency if a test needs to exercise S3-calling code.
- Do not add placeholder-only functions that pretend to work.
- Do not add heavy frontend tooling.
- Do not commit cache directories, build artifacts, virtual environments, local secrets, or
  generated SQLite/log files produced by manual testing.

## Run commands

Install with development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run the dashboard:

```bash
streamlit run src/domain_feed_health_dashboard/app.py
```

Run tests:

```bash
python -m pytest
```

## Health-band / status rules

- UI coloring uses **percentage health bands** (`status.cell_health_band`), keyed on
  delivered ÷ expected files: 95–100% green, 80–94% yellow, 70–79% orange, 0–69% or > 100%
  (over-delivery) red. A non-positive expected count is red.
- Lowest color propagates upward: a feed's band is the worst of its day cells; a domain's band is
  the worst of its feeds (`status.rollup_band`). On the Historical tab the feed band is the worst
  cell across the selected window, so any red day makes the domain red and the window size can
  change a domain's color.
- The metric cards, the domain Status cell, the per-band feed counts, and the sidebar status
  filter are all band-based (green/yellow/orange/red), shared by both tabs.
- `status.py` also retains the legacy 3-level `green`/`yellow`/`red` rollup
  (`status_from_count`, `domain_status_from_feeds`, `feed_status_counts`, `build_domain_summary`)
  used by the `Generator`'s SQLite write path. Keep band logic and these helpers in `status.py`;
  do not duplicate or diverge the rules.

## Areas to avoid changing without confirmation

- Replacing Streamlit with another framework.
- Changing the SQLite schema (including the `devices` aimpoint columns) or its 30-day retention
  behavior.
- Making the S3 bucket/prefixes configurable on `Generator` (currently fixed module constants in
  `services/generator.py`, e.g. `S3_BUCKET`/`FEED_PREFIX`/`DEVICE_PREFIX`) without checking every
  caller.
- The aimpoint fetch path (`{DEVICE_PREFIX}<delivered-prefix>/<device_id>.json`) and the per-process
  aimpoint cache in `Generator` — these are load-bearing for both correctness (device fields) and
  load time.
- Adding authentication, persistent multi-user state, or export workflows.
```
