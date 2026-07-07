# ACB-Generator — Bug Fix Log

A record of bugs/errors resolved in the Domain Feed Health Dashboard (Streamlit)
and how each was fixed. Grouped by area. File references are under
`src/domain_feed_health_dashboard/` unless noted.

---

## Data ingestion / parsing

### 1. File counts were always 0
- **Symptom:** The "File Count" column showed 0 for every feed; the live SQLite had `count = 0` for all rows.
- **Cause:** `apply_feed_line_to_tally` read the count from a `"count"` key that the current `dBoardData` feed format does not contain (`int(data.get("count", 0))` → always 0), and it *replaced* the `FeedTally` on every line so nothing accumulated. Each delivered line *is* one file.
- **Fix:** `services/log_parser.py` — accumulate the feed count by +1 per delivered line (`prior_count + 1`), preserving an explicit legacy `"count"` field if present.

### 2. Feed status was always YELLOW
- **Symptom:** Every feed rendered yellow.
- **Cause:** Feed status was read from a `"status"` key absent in the `dBoardData` format (`data.get("status", "yellow")`).
- **Fix:** `services/log_parser.py` — derive feed status from delivered-vs-expected counts via `status.status_from_count` (later superseded by the percentage bands for UI coloring). Explicit legacy `"status"` honored if present.

### 3. Expected file count (formula) — `log_parser.expected_file_count(aimpoint)`
- **Formula:** `files_expected = operation_minutes // transcoderInterval`, where `transcoderInterval` is minutes-per-file (default 15) and `operation_minutes` is the summed `hours.hrs` window durations (`"HHMM-HHMM"`, overnight/`0000-0000` wrap to full day) plus `hours.rndm` (when non-zero). **No `hours` → 24h operation** (so the default is `1440 / 15 = 96` files/day).
- **History:** originally `compute_expected_count(op_start, op_end)` counted 15-min cycles in a clock window; it returned 0 for `00:00-00:00` and 95 for the `23:45` default. That was fixed (wrap → 96), then **replaced** by `expected_file_count`, which additionally honors `transcoderInterval` and `rndm` and sums multiple windows. Placeholder devices (no aimpoint) use `expected_file_count({})` → 96; the first delivered file is counted too. `op_window_start/end` are still derived/stored from `hrs[0]` for reference but no longer drive the count.

### 4. Date path components (`2026`, `06`) ingested as domains/feeds
- **Symptom:** Rows named `2026`, `06`, etc. appeared as domains/feeds.
- **Cause:** `parse_feed_line` derived the domain from delivered-path index 2 and the device from index 3 with no validation, so malformed/empty path segments shifted the `YYYY/MM/DD` date into those slots.
- **Fix:** `services/log_parser.py` — added `_date_start_index`; skip a line when the date starts before index 4 (date shifted into domain/device slots) or the domain/device segment is empty.

---

## Aimpoint (device) data

### 5. Device panel showed network fields, not the aimpoint structure
- **Symptom:** The device detail showed hostname/IP/MAC/vendor/etc. (mostly empty), not the aimpoint fields.
- **Cause:** `DeviceRecord`/`DeviceTally`, the parser, schema, repository, and generator modeled a network device, not the aimpoint JSON.
- **Fix:** Full re-model to the aimpoint structure (`aimpoint_structure.txt`): `deviceID, hpID, collEnabled, collRegions, decoy, proxy, collectionType, hours(tz+hrs), longLat, singleCollector, dstBucket, deliveryKey, bucketPrefixTemplate, filenameBase, finalFileSuffix, monitoringData` + status + file metrics. Touched `data_model.py`, `db/schema.py`, `services/log_parser.py` (`parse_device_json`), `services/generator.py`, `db/repository.py`, `table_data.py` (`device_field_value_rows`).

### 6. Unexposed aimpoint fields were fabricated
- **Symptom:** Booleans defaulted to `false` and coordinates to `0.0` even when the JSON didn't expose them.
- **Cause:** Non-optional defaults invented values.
- **Fix:** Made `coll_enabled`, `decoy`, `single_collector`, `longitude`, `latitude`, `last_monitored` `Optional` — populated only when the JSON exposes them, else `None` (stored `NULL`), rendered as `—`. An exposed `false` stays distinct from an absent field.

### 7. Aimpoint files were never fetched (wrong S3 path)
- **Symptom:** Aimpoint fields stayed empty; only file counts populated.
- **Cause:** `_fetch_device_files` fetched `dboard/aimpoints/data/{domain}/{device}/cerium-{device}.json`, which doesn't match the real layout.
- **Fix:** `services/generator.py` — fetch `dboard/aimpoints/<delivered-prefix>/<device>.json` (e.g. `.../up/ru/24oko/glazok1080/glazok1080.json`), i.e. `{DEVICE_PREFIX}{folder}/{device_id}.json`, deriving `folder` from the delivered path.

### 8. History device panel stayed empty even after the path fix
- **Symptom:** Current tab showed aimpoint fields, but the Historical tab did not.
- **Cause:** History reads stored SQLite device rows, which were written before aimpoint capture worked.
- **Fix:** `history_data.build_history_domain_master` accepts a `live_routers` map ({(domain_id, feed_id): routers}); the device detail prefers the most recent (live) aimpoint, falling back to the stored row. `ui.py` passes the live domains' devices through.

---

## Coloring / status model (percentage bands)

### 9. Health coloring didn't use a consistent percentage scale
- **Symptom:** Loose 3-level thresholds; colors didn't migrate as counts grew.
- **Fix:** Introduced `status.cell_health_band(actual, expected)` — bands by delivered ÷ expected: 95–100% green, 80–94% yellow, 70–79% orange, 0–69% **or** >100% (over-delivery) red; non-positive expected → red. Used consistently for feeds, domains, cards, and filters via `feed_health_band`, `rollup_band`, `build_domain_band_summary`, `band_overall_metrics`, `filter_domain_band_summary`.

### 10. History day cells showed R/Y/G letters instead of counts
- **Symptom:** Cells displayed a status letter, not the delivered count.
- **Fix:** `history_data.py` — each cell now holds the delivered count with a hidden `<date>__status` band sibling driving the color; `grid_config.py` colors via that sibling.

### 11. Arrow serialization error on the history grid
- **Symptom:** `pyarrow.lib.ArrowTypeError: Expected bytes, got a 'int' object` — the day column mixed `int` counts with the `"—"` string.
- **Fix:** Keep the count column single-typed (`None` for missing, not `"—"`); render `—` via a JS `valueFormatter` (`HISTORY_COUNT_FORMATTER_JS`). The non-AgGrid fallback renders all-string cells.

### 12. Domain color didn't propagate the worst cell (window average bug)
- **Symptom:** A feed with red day-cells (e.g. "worldcam") still rolled up to a green domain; and a 30-day window with one zero day showed green.
- **Cause:** The history domain rollup used a *window average* (Σ delivered ÷ Σ expected).
- **Fix:** `history_data.build_history_domain_master` — a feed's window band is the **worst** of its day cells (`rollup_band`), and the domain is the worst feed. Lowest color propagates device cell → feed → domain; any red day makes the domain red, and shrinking the window can change the color.

---

## UI behavior

### 13. Metric cards missing on the Historical tab
- **Fix:** `ui.py` — `_render_overall_metrics` takes a band-summary DataFrame and renders on both tabs, computed from the filtered visible domains.

### 14. Sidebar filters didn't apply to the Historical tab
- **Symptom:** Search / status filter / "only red feeds" only affected the Current tab.
- **Fix:** `status.filter_domain_band_summary` is shared; `ui._render_history_section` filters the history master by the same widgets. Status filter options are the four bands.

### 15b. AgGrid custom cell graphic — can't return HTML or a DOM node (AG Grid 34 / React)
- **Symptom:** The Historical "Trend" sparkline column first rendered the raw `<svg …>` markup as literal text; returning a DOM node instead threw **React minified error #31** (`Objects are not valid as a React child … HTMLDivElement`).
- **Cause:** This `streamlit-aggrid` build bundles **AG Grid 34** with **`reactiveCustomComponents: true`** (default since v32.2; confirmed in the frontend bundle, where `reactiveCustomComponents=false` is also flagged *deprecated*). So a `cellRenderer` function's return is treated as a **React child** — an HTML string is escaped, and a DOM element (`createElementNS`/`document.createElement`) is not a valid React child and crashes the component.
- **Fix (final):** Don't return markup from a renderer at all. Pre-render the sparkline **server-side as a PNG** (`history_data.domain_trend_png`, Pillow `ImageDraw` line → base64 `data:image/png;base64,…`, stored in the `trend_img` column) and display it as the cell's **background image** via a **`cellStyle` JsCode function** (`grid_config.TREND_IMAGE_STYLE_JS` returns `{backgroundImage: url(...), backgroundSize: contain}`) — a cellStyle only ever returns a plain style object, the SAME safe mechanism as the band-colour styles, which React applies fine. A `valueFormatter` returning `''` blanks the raw data-URI text. (An intermediate Unicode block-glyph text sparkline via `valueFormatter` also renders, since strings are fine — kept only as a lighter fallback idea.) Added `pillow>=10` to deps. The full interactive graphic lives in the `st.dialog` "Enlarge trend" chart. **Rule of thumb for cell graphics in this stack: emit a `cellStyle` (background image) or plain text — never inject HTML/SVG/DOM from a `cellRenderer` `JsCode`.**

---

## Performance

### 15. Dashboard took minutes to load
- **Symptom:** Several minutes on first load (the SQLite read itself was ~0.2s — not the cause).
- **Cause:** `Generator.rebuild_tally()` / `backfill_history()` did one sequential S3 GET **per device per feed-file** for aimpoint JSON, and the same device recurs across many files/days (~4–5s each).
- **Fix:** `services/generator.py` — cache each aimpoint by S3 key (`_aimpoint_cache`, downloaded once per process, misses cached too) and fetch cache-misses in parallel (`ThreadPoolExecutor`, `DEVICE_FETCH_WORKERS = 16`). "Refresh now" clears the cache (`clear_aimpoint_cache`) to re-pull metadata.

---

## Notes / gotchas for future work

- **The device stores the full aimpoint as raw JSON.** As of the "full aimpoint structure" change, the `devices` table has a single `aimpoint_json` TEXT column (not individual aimpoint columns like `hp_id`, `coll_enabled`, …). `DeviceRecord`/`DeviceTally` keep only `device_id`, `aimpoint_json`, `health_status`, `op_window_*`, `files_actual`, `files_expected`. The device panel is rendered by flattening `aimpoint_json` (`table_data._flatten_aimpoint`: nested objects → `Parent · Child`, arrays joined, `_AIMPOINT_LABELS` for nice labels). Only the op window is derived from `hours.hrs` (for expected counts). To add a new aimpoint field, no schema/model change is needed — just add a label to `_AIMPOINT_LABELS` if you want a nicer name. This replaced the earlier per-field columns/optionals (bugs #5–#7 below are historical).
- **Regenerate the SQLite DB after schema changes.** `db/schema.py` uses `CREATE TABLE IF NOT EXISTS`, so an existing `domain_feed_health_dashboard.sqlite3` won't migrate (e.g. the `devices` column changes). Delete it and re-backfill; it's a generated, gitignored artifact.
- **Aimpoint metadata is cached for the process lifetime.** File counts still update every cycle (they come from delivery lines, not the aimpoint file); use "Refresh now" to re-pull aimpoint metadata.
- **The Textual TUI pipeline was removed** — Streamlit is the only UI. `scripts/run_generator.py` and the `textual` dependency are gone.
- **`status.py` keeps a legacy 3-level rollup** (`status_from_count`, `domain_status_from_feeds`, `build_domain_summary`) for the SQLite write path; UI coloring uses the 4-band model.
