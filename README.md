# Domain Feed Health Dashboard

A live operator dashboard for reviewing domain, feed, and device (aimpoint) health, backed by
real delivery/aimpoint data in S3. A single Streamlit + AgGrid web UI over the `Generator`
(live S3 tally) and `Repository` (30-day SQLite history) data pipeline.

## What this repository contains

| Component | Entry point | Data pipeline |
|---|---|---|
| Streamlit + AgGrid web dashboard | `streamlit run src/domain_feed_health_dashboard/app.py` | `Generator` (live S3 tally) + `Repository` (30-day SQLite history, default `domain_feed_health_dashboard.sqlite3`) |

The dashboard reads from the S3 bucket `acb-highwaypatrol-coruscant` (default) for the live view
and from a local SQLite history database for the 30-day view.

## Streamlit web dashboard

The dashboard has two tabs — **Current** and **Historical**. Both tabs share the same building
blocks: percentage-based health-band coloring, band-based metric cards, the same sidebar filters,
and a nested **domain → feed → device (aimpoint)** master/detail AgGrid.

There is no simulated/demo-data mode. The dashboard only ever shows real data read from S3
(Current tab) and the local SQLite history database (Historical tab).

### Health bands (the coloring model)

Cell/feed/domain colors are driven by the **delivered ÷ expected** file percentage, shared by
both tabs (`status.cell_health_band`):

| Band | Delivered ÷ expected | Meaning |
|---|---|---|
| 🟢 green | 95–100% | Good |
| 🟡 yellow | 80–94% | Slightly low |
| 🟠 orange | 70–79% | Degraded |
| 🔴 red | 0–69% **or** > 100% (over-delivery) | Broken / anomalous |

- A feed's band = its delivered count vs. its device's expected daily files.
- A domain's band = the **worst** feed band — the lowest color propagates upward
  (device cell → feed → domain).
- On the Current tab the band migrates through the day as files accumulate toward expected
  (red → orange → yellow → green; over-delivery is red).
- A device that runs the full day uses a `00:00`–`00:00` op window, which is treated as a 24h
  window = **96 expected files** at the 15-minute cadence.

The `Generator` also writes a separate 3-level `green`/`yellow`/`red` feed/domain status to
SQLite (the legacy worst-feed/worst-device rollup in `status.py`); the UI coloring uses the
4-band model above.

### Current tab

- **Metric cards** (band counts, reflecting the active filters): Visible domains, Visible feeds,
  Green/Yellow/Orange/Red domains, and Green/Yellow/Orange/Red feeds.
- **Per-domain AgGrid master table** with columns *Domain, Status, Total Feeds, Green, Yellow,
  Orange, Red, Last Checked*. The Status cell is colored by the domain band.
- Clicking a domain row expands it inline to show that domain's **feeds** — columns *Device ID,
  Status, File Count, Expected / Day, Location, Collection Type, System ID, Last Checked*. The
  Status and File Count cells are colored by the feed's band, and `Expected / Day` comes from the
  feed's attached device's `files_expected`.
- Clicking a feed row expands it inline to show that feed's **device aimpoint** as a two-column
  **Field / Value** grid (the full aimpoint structure plus status and file metrics — see
  "Device = aimpoint" below).

### Historical tab

- The **same** nested master/detail (domain → feed×day pivot → device aimpoint), the same
  band-based metric cards, and the same sidebar filters as the Current tab.
- **Domain Status is the window aggregate**: the worst day cell across the selected window
  propagates up, so any red day makes the domain red — and shrinking the window can drop bad days
  and change a domain's color (e.g. red over 30 days, green over 10).
- The feed detail is a **feed × day pivot**: one row per feed, one column per completed UTC day
  (newest day first), each cell the delivered file count colored by that day's band; `—` marks a
  day the feed was not present.
- **Line graph**: selecting a domain row renders, just below the grid, an Altair line graph of
  that domain's feeds' daily delivered counts — x-axis = day (most recent day on the **left**,
  oldest on the right), y-axis = count, one line per feed.
- The device aimpoint detail uses the **most recent (live) aimpoint**, falling back to the stored
  historical device row.
- The window defaults to 30 days and is configurable from 1 to 31 days back from today via a
  sidebar slider.

### Sidebar controls (apply to both tabs)

- **SQLite history database path** (`DASHBOARD_DB_PATH`).
- **Refresh now** — forces the next S3 poll and clears the aimpoint cache so aimpoint metadata is
  re-pulled.
- **Search domains**, **Domain status filter** (green/yellow/orange/red bands), **Show only
  domains with red feeds** — these filters apply to both the Current and Historical tabs.
- **Max expanded feed rows per domain** (Current tab feed expansion).
- **Historical window (days)** — 1 to 31.

### How live data flows

1. `Generator.rebuild_tally()` replays today's S3 feed files into an in-memory tally, and
   `Generator.backfill_history()` fills any missing completed days into SQLite. Both run once per
   Streamlit process (cached via `st.cache_resource`).
2. On each Streamlit rerun, `Generator.run_cycle()` is called again only if at least
   `CYCLE_SECONDS` (15 minutes) have passed since the last call, to avoid polling S3 on every UI
   interaction. The sidebar "Refresh now" button forces the next call through immediately.
3. At UTC midnight, `Generator` pushes the completed day to the SQLite history database. The
   30-day history view reads only from that database via `Repository`, so it keeps working even
   if S3 is temporarily unreachable.

Aimpoint (device) files are fetched from `dboard/aimpoints/<delivered-prefix>/<device>.json`
(e.g. `.../up/ru/24oko/glazok1080/glazok1080.json`, where the prefix is the feed's delivered
path). Each aimpoint is **cached per process** (downloaded once even though a device recurs across
many feed files and backfill days) and the cache-misses are fetched in parallel — the per-aimpoint
S3 round-trip is the dominant load-time cost.

### Configuration

- `DASHBOARD_DB_PATH` environment variable overrides the default SQLite history database path
  (`domain_feed_health_dashboard.sqlite3`).
- The S3 bucket and key prefixes used by `Generator` are fixed module constants in
  `src/domain_feed_health_dashboard/services/generator.py` (`S3_BUCKET`, `FEED_PREFIX`,
  `DEVICE_PREFIX`); they are not currently configurable from the Streamlit UI.

## Device = aimpoint

The device detail is the **full aimpoint structure** (see `aimpoint_structure.txt`). The complete
raw aimpoint JSON is stored verbatim (the `devices.aimpoint_json` column / `DeviceRecord.aimpoint_json`)
and rendered field-by-field in the device panel by flattening it (`table_data._flatten_aimpoint`:
nested objects become `Parent · Child` rows, arrays are joined, booleans show as `true`/`false`),
so the complete and evolving structure — `collEnabled`, `collRegions`, `collectionType`, `accessUrl`,
`pollFrequency`, `firstContactData`, `hours`, `extractAudio`, `longLat`, `transcodeOptions`,
`monitoringData`, etc. — is shown without hand-mapping each key. Only present fields are shown
(nothing is fabricated). Appended below the aimpoint are the device's health status and Files Actual /
Files Expected. `Files Expected` = operation minutes ÷ `transcoderInterval` (minutes-per-file,
default 15), where operation minutes is the summed `hours.hrs` window durations plus any `hours.rndm`;
with no `hours`, 24-hour operation is assumed (so the default is `1440 / 15 = 96` files/day). See
`log_parser.expected_file_count`. `RouterAccessPoint` is a backward-compatible alias for `DeviceRecord`.

## Requirements

- Python >= 3.11
- See `pyproject.toml` for the full dependency list (`streamlit`, `streamlit-aggrid`, `pandas`,
  `boto3`, `botocore`, `tenacity`; dev: `pytest`, `moto[s3]`). The Historical line graph uses
  Altair, which ships with Streamlit.
- AWS credentials resolved by boto3's standard chain (environment variables, `~/.aws/credentials`,
  or an IAM/ECS task role) are required for the "Current" view to show live data. The Historical
  view only needs the local SQLite file, not live AWS access.

## Setup

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
streamlit run src/domain_feed_health_dashboard/app.py
```

## Test

```bash
python -m pytest
```

Tests use fixture `DomainRecord`/`FeedRecord`/`DeviceRecord` objects and a temporary SQLite
database (via `db/schema.open_db`) — no live AWS credentials are required to run the test suite.

## Project structure

```text
src/domain_feed_health_dashboard/
  app.py              # Streamlit entry point
  ui.py               # Streamlit UI: Current + Historical tabs, cards, filters, history line graph
  grid_config.py      # AgGrid configuration helpers (band cellStyle + master/detail JS callbacks)
  table_data.py       # Non-UI table-shaping helpers (band-based domain master, feed rows, device rows)
  history_data.py     # Non-UI history shaping (band rollup, day-pivot, domain master, line-graph series)
  data_model.py       # DomainRecord / FeedRecord / DeviceRecord (aimpoint) dataclasses
  status.py           # Health bands + legacy 3-level status rollups
  services/
    generator.py      # Generator: S3 polling, aimpoint cache, in-memory tally, midnight SQLite push
    log_parser.py     # Feed-line and aimpoint-JSON parsing, expected-count math
  db/
    schema.py         # SQLite DDL (domain_sets, devices[aimpoint], feeds, snapshot_meta)
    repository.py     # Repository: read-only 30-day history access
  aws/
    s3_client.py      # boto3 S3 client factory
    scanner.py        # S3 listing/reading helpers
  utils/
    cache.py, logger.py
tests/
  test_status.py, test_grid_config.py, test_table_data.py,
  test_history_data.py, test_generator_backfill.py, test_log_parser.py
docs/
  streamlit_dashboard_prompt.md   # Historical build prompt the Streamlit UI was ported/extended from
```

## Known limitations

- The Streamlit UI cannot currently override the S3 bucket or key prefixes used by `Generator`
  (they are fixed module constants in `services/generator.py`); only the SQLite history database
  path is configurable, via `DASHBOARD_DB_PATH`.
- Aimpoint metadata is cached for the lifetime of the Streamlit process; "Refresh now" clears it
  to re-pull. (File counts always update every cycle regardless, since they come from delivery
  lines, not the aimpoint file.)

## Future work ideas

- Make the S3 bucket/prefixes configurable per `Generator` instance instead of module constants.
- CSV/JSON export from the UI.
```
