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

The dashboard has two tabs — **Current** and **Historical**. Both use a nested
**domain → feed → device (aimpoint)** master/detail AgGrid and the same sidebar filters, but they
**color health differently**: the Current tab is a time-aware *on-track* check (green / yellow /
gray, never red), while the Historical tab uses **delivered ÷ expected** percentage bands.

There is no simulated/demo-data mode. The dashboard only ever shows real data read from S3
(Current tab) and the local SQLite history database (Historical tab).

### Health coloring

**Current tab — on-track check (green / yellow / gray, never red).** A feed starts green and stays
green while its delivered count is within **±1** of the files expected *by the current time* (from
the aimpoint's operating hours — see `log_parser.expected_file_count_so_far`). A larger deviation
(extra *or* missing files for now) is **yellow**. A feed with no aimpoint is **gray**. The domain is
the worst of its feeds (yellow > green); a domain whose feeds are *all* gray is gray. See
`status.current_feed_band`.

**Historical tab — percentage bands (`status.cell_health_band`).** Each day cell is colored by that
day's **delivered ÷ expected**:

| Band | Delivered ÷ expected | Meaning |
|---|---|---|
| 🟢 green | 95–100% | Good |
| 🟡 yellow | 80–94% | Slightly low |
| 🟠 orange | 70–79% | Degraded |
| 🔴 red | 0–69% **or** > 100% (over-delivery) | Broken / anomalous |
| ⚪ gray | — (no aimpoint) | No aimpoint exists — can't be assessed |

- A feed's window band = the **worst** of its day cells; a domain = the worst of its feeds (the
  lowest color propagates upward). "Gray" (no aimpoint) never wins a rollup; a domain whose feeds
  all lack an aimpoint is itself gray.
- A feed with **no aimpoint at all** shows gray day cells with a delivered count of **0** (no
  aimpoint → no files generated).
- A device that runs the full day uses a `00:00`–`00:00` op window, treated as a 24h window =
  **96 expected files** at the 15-minute cadence.

The `Generator` also writes a separate 3-level `green`/`yellow`/`red` feed/domain status to
SQLite (the legacy worst-feed/worst-device rollup in `status.py`); the UI coloring uses the
band models above.

### Current tab

- **Metric cards** (band counts, reflecting the active filters): Visible domains, Visible feeds,
  Green/Yellow/Orange/Red domains, and Green/Yellow/Orange/Red feeds. (Current-tab health is only
  green/yellow/gray, so the Orange and Red cards are always 0.)
- **Per-domain AgGrid master table** with columns *Domain, Total Feeds, Green, Yellow, Collection
  Region, Proxy*. There is no separate Status column — the **Domain** cell itself is colored by the
  domain band. The Orange/Red columns are hidden on this tab (kept in the data). Collection Region
  and Proxy come from any of the domain's feed devices' aimpoints.
- Clicking a domain row expands it inline to show that domain's **feeds** — columns *Device ID,
  File Count, Expected / Day, Location, Collection Type, Collection Region, Proxy*. The **File
  Count** cell is colored by the feed's band; `Expected / Day` is the device's full-day
  `files_expected`; and Location (`longLat`), Collection Type (`collectionType`), Collection Region
  (`collRegions`), and Proxy (`proxy`) all come from the feed's device aimpoint.
- Clicking a feed row expands it inline to show that feed's **device aimpoint** as a two-column
  **Field / Value** grid (the full aimpoint structure plus file metrics — see "Device = aimpoint"
  below). A gray (no-aimpoint) feed instead shows a single **"No aimpoint exists"** row.

### Historical tab

- The **same** nested master/detail (domain → feed×day pivot → device aimpoint), the same
  band-based metric cards, and the same sidebar filters as the Current tab.
- **Per-domain master table** with columns *Domain, Total Feeds, Green, Yellow, Orange, Red,
  Collection Region, Proxy, Trend*. The columns flex to fill the grid width, with **Trend** at 1.5×.
  The Domain cell is colored by the domain's **window band** (worst day cell across the window
  propagates up), so any red day makes the domain red — and shrinking the window can drop bad days
  and change a domain's color (e.g. red over 30 days, green over 10). A domain whose feeds have **no
  aimpoint at all** is gray.
- **Trend** column: an inline PNG line **sparkline** of the domain's daily delivered counts (one
  line per feed, colored to match the enlarged chart). Clicking the sparkline cell opens an enlarged,
  interactive per-feed Altair line graph in a modal dialog — x-axis = day (most recent on the
  **left**), y-axis = delivered count. (A "🔍 Enlarge trend" button reopens it for the current
  domain.)
- The feed detail is a **feed × day pivot**: one row per feed, one column per completed UTC day
  (newest day first), each cell the delivered file count colored by that day's band; `—` marks a
  day the feed was not present. A feed with no aimpoint at all shows **gray cells with a count of 0**.
- **Per-day aimpoint**: clicking a specific **day cell** shows that feed's device aimpoint *for that
  exact day*. If that day has no aimpoint, the panel says **"No aimpoint exists"** (no fall-back to a
  previous day) — aimpoints occasionally change, so each day shows its own. Clicking the feed-id cell
  (no day selected) shows the current/most-recent aimpoint, which prefers the **live** aimpoint,
  falling back to the stored historical device row.
- The window defaults to 30 days and is configurable from 1 to 31 days back from today via a
  sidebar slider.

### Sidebar controls (apply to both tabs)

Every control has a help (`?`) tooltip describing it.

- **SQLite history database path** (`DASHBOARD_DB_PATH`).
- **Refresh now** — forces the next S3 poll and clears the aimpoint cache so aimpoint metadata is
  re-pulled.
- **Search domains** — name-contains filter.
- **Domain status filter** — colored boxes labeled by percentage range only (🟢 95-100%, 🟡 80-94%,
  🟠 70-79%, 🔴 <70% or >100%, ⚪ 0% = no aimpoint). The gray box selects no-aimpoint domains. The
  selected boxes stack full-width so their labels show in full.
- **Historical window (days)** — 1 to 31.
- **Feed history** — a subheader whose help tooltip explains the Historical drilldown, plus a
  **Backfill / refresh history now** button.

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

Aimpoint (device) files live under `dboard/aimpoints/<delivered-prefix>/` — one `.json` per device
folder — but the file name need **not** match the device folder (e.g.
`up/ru/vtomske/01/tomsk01.json`). The `Generator` therefore **discovers** the actual `.json` by
listing each folder's parent subtree once (cached per process), and uses that file's **base name**
(`tomsk01`) as the device name. Each aimpoint file is then downloaded once (cached; cache-misses
fetched in parallel — the per-aimpoint S3 round-trip is the dominant load-time cost). Device ids are
only unique within a domain, so aimpoints are keyed by `(domain_id, device_id)`.

**Configured devices that deliver nothing still appear.** The pipeline is delivery-driven, so a
device that produces no files would otherwise be invisible. After processing deliveries, the
`Generator` enumerates every aimpoint under a domain and adds any missing device as a feed with a
**zero** delivered count — surfacing "configured but not delivering" as a health problem (Current →
yellow, Historical → red) rather than hiding it.

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
(nothing is fabricated). Appended below the aimpoint are **Files Actual** and **Files Expected**;
on the **Current tab** a **Current Expected Files** row is also appended — the files expected *by
now* from the aimpoint's operating hours (`log_parser.expected_file_count_so_far`), the value the
Current-tab band compares Files Actual against. `Files Expected` = operation minutes ÷
`transcoderInterval` (minutes-per-file, default 15), where operation minutes is the summed
`hours.hrs` window durations plus any `hours.rndm`; with no `hours`, 24-hour operation is assumed
(so the default is `1440 / 15 = 96` files/day). See `log_parser.expected_file_count`. A feed with no
aimpoint shows a single **"No aimpoint exists"** row instead of a panel. `RouterAccessPoint` is a
backward-compatible alias for `DeviceRecord`.

## Requirements

- Python >= 3.11
- See `pyproject.toml` for the full dependency list (`streamlit`, `streamlit-aggrid`, `pandas`,
  `boto3`, `botocore`, `tenacity`, `pillow`; dev: `pytest`, `moto[s3]`). The Historical line graph
  uses Altair (ships with Streamlit); the Historical **Trend** sparkline PNGs are drawn with Pillow.
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
  ui.py               # Streamlit UI: Current + Historical tabs, cards, filters, trend enlarge dialog
  grid_config.py      # AgGrid config (band/gray cellStyle, sparkline background, master/detail JS)
  table_data.py       # Non-UI table-shaping helpers (current-tab domain master, feed rows, device rows)
  history_data.py     # Non-UI history shaping (band rollup, day-pivot, domain master, trend PNG + change-points)
  data_model.py       # DomainRecord / FeedRecord / DeviceRecord (aimpoint) dataclasses
  status.py           # Health bands (percentage + current-tab time-aware) + legacy 3-level rollups
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
- Aimpoint metadata is cached per process; "Refresh now" clears it to re-pull, and it is also
  cleared automatically at the **UTC-midnight rollover** so each day snapshots its own aimpoint.
  (File counts always update every cycle regardless, since they come from delivery lines, not the
  aimpoint file.)
- **Per-day aimpoint history only accrues going forward.** S3 keeps a single current, non-dated
  aimpoint per device, so each completed day is snapshotted (and frozen — a re-push/backfill won't
  overwrite it) with the aimpoint as of that day. Day-to-day differences appear only once the S3
  aimpoint actually changes over subsequent days; days that were bulk-backfilled at once share the
  aimpoint that was current then (there is no historical aimpoint in S3 to reconstruct).

## Future work ideas

- Make the S3 bucket/prefixes configurable per `Generator` instance instead of module constants.
- CSV/JSON export from the UI.
```
