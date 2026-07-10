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

### 4b. Domain shown as full path; straight-to-date paths (no device folder) were dropped
- **Symptom:** (1) Domains displayed only the 3rd path segment (e.g. `24oko`, `worldcam`) instead of the full key. (2) Deliveries whose path went straight from the domain to the date — `up/eg/makaniBeachClub/2026/07/09/<file>` (no device folder) — were never ingested.
- **Cause:** `parse_feed_line` (dBoardData branch) set `domain_id = parts[2]` and required `date_start >= 4` (assuming a device folder), so `date_start == 3` paths were skipped.
- **Fix:** `services/log_parser.py` — the **domain is the full 3-segment key** `"/".join(parts[:3])` (`up/<country>/<name>`, e.g. `up/ru/powernet.com.ru`, `up/bb/worldcam`), set as both `domain_id` and `domain_name`. The **device** is `parts[date_start - 1]` — `parts[3]` when a device folder is present (`date_start == 4`), or `parts[2]` (the domain's last segment, e.g. `makaniBeachClub`) when the path goes straight to the date (`date_start == 3`). Accept `date_start >= 3`; still skip when the date is shifted into the first three slots (`< 3`) or any domain/device segment is empty. The aimpoint fetch path (`{DEVICE_PREFIX}<folder>/<device_id>.json`, `folder = parts[:date_start]` from `extract_folder_and_date`) then resolves correctly for both — e.g. `dboard/aimpoints/up/eg/makaniBeachClub/makaniBeachClub.json`.
- **Gotcha:** `domain_id` values changed (short name → full path). **Existing history rows keep their old short `domain_id`/`domain_name`** — delete/regenerate the SQLite DB (or re-backfill) so the Historical tab shows full paths and old/new days don't split into separate domains. The Current tab picks up full paths on the next poll.

### 4. Date path components (`2026`, `06`) ingested as domains/feeds
- **Symptom:** Rows named `2026`, `06`, etc. appeared as domains/feeds.
- **Cause:** `parse_feed_line` derived the domain from delivered-path index 2 and the device from index 3 with no validation, so malformed/empty path segments shifted the `YYYY/MM/DD` date into those slots.
- **Fix:** `services/log_parser.py` — added `_date_start_index`; skip a line when the date starts before index 4 (date shifted into domain/device slots) or the domain/device segment is empty.

---

## Aimpoint (device) data

### 4c. Device id collision across domains → wrong aimpoint / shared device tally
- **Symptom:** For `up/ru/sharyaOnline` (devices `24`, `29`, `212`), device `24`'s panel showed `Delivery Key = up/ru/lanoptic/24` (another domain's aimpoint). `up/ru/lanoptic/24` was mixing into `up/ru/sharyaOnline/24`.
- **Cause:** `Generator` keyed `device_folder_map` and `device_tallies` (and `apply_feed_line_to_tally`'s lookup) by **`device_id` alone**. Device ids like `24` are only unique *within a domain*, so `up/ru/sharyaOnline/24` and `up/ru/lanoptic/24` collided — one folder won (wrong aimpoint fetched) and both domains' device 24 shared a single `DeviceTally` (so `files_actual` also cross-contaminated).
- **Fix:** key all three by the **`(domain_id, device_id)` pair**: `services/generator.py` `device_folder_map` / `_fetch_device_files` (returns `{(domain_id, device_id): DeviceTally}`) and `services/log_parser.py` `apply_feed_line_to_tally` (`device_tallies.get((domain_id, device_id))`). Each (domain, device) now fetches and stores its own aimpoint. The S3 aimpoint cache stays keyed by the unique S3 key.
- **Gotcha:** existing history DB rows were written with the collided aimpoints — **delete/regenerate the SQLite DB (or re-backfill)** to correct them. A device only appears as a feed if it has deliveries in the window; the fix corrects each delivering device's aimpoint but does not invent feeds for devices with no deliveries.

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

### 7b. Aimpoint filename ≠ device folder → "No aimpoint exists" (up/ru/vtomske, up/ru/sharyaOnline)
- **Symptom:** Whole domains (e.g. `up/ru/vtomske` with device folders `01/11/21/29`, `up/ru/sharyaOnline` with `24/29/212`) showed "No aimpoint exists" in the UI though the aimpoints existed.
- **Cause:** the aimpoint file inside a device folder is **not** named `<device_id>.json` — e.g. `up/ru/vtomske/01/` contains `tomsk01.json`. The Generator fetched `…/01/01.json` (built from the delivered-path segment), which 404s.
- **Fix:** `services/generator.py` — `_fetch_device_files` now **discovers** the actual `.json` by listing the folder's parent subtree once (`_aimpoint_keys_under`, cached per process, keyed by the folder's parent; cleared with the aimpoint cache at rollover/`clear_aimpoint_cache`). The file's **base name** (`tomsk01`) becomes the device name. `apply_feed_line_to_tally` (`log_parser.py`) now derives the device/feed identity from the fetched `DeviceTally.device_id` (the base name), falling back to the delivered-path segment when no aimpoint is found. There is one `.json` per device folder, so the single file is used (preferring an exact `<device_id>.json` if present is unnecessary — just take the one in the folder).
- **Gotchas:** (1) `feed_id == device_id` now (the feed IS the device); the legacy explicit-`feed_id` path is gone. (2) device ids in the UI/DB are now the aimpoint base names (`tomsk01`), not `01`. (3) **regenerate the history DB** so old rows pick up the discovered aimpoints/names. (4) the FakeScanner in tests must include the aimpoint object in `objects` (listable), not just `contents`.

### 7e. `parse_device_json` overrode the device name with the aimpoint's `deviceID` field
- **Symptom:** even after 7d, `21`/`24` still appeared (with the real counts and a real aimpoint) alongside `tomsk21`/`sharya24` (count 0, `device_pk = NULL`).
- **Cause:** `log_parser.parse_device_json` set `device_id = data.get("deviceID", …)` — the aimpoint's **own** field. Real aimpoints carry a short, folder-scoped id: `tomsk21.json` contains `"deviceID": "21"`. So the delivery resolved the aimpoint correctly but the device came back named `21`; enumeration (keyed by the file **base name** `tomsk21`) didn't see `21`, added a second feed, and at push time `device_pk_map` (keyed by `dev.device_id` = `21` for both) left the enumerated feed's `device_pk` NULL.
- **Fix:** `parse_device_json` now uses the **passed** `device_id` (the aimpoint file's base name / `filenameBase`) as the identity. The aimpoint's `deviceID` is still preserved verbatim inside `aimpoint_json` for display. Both the delivery and enumeration paths pass the base name, so they agree and the device can't duplicate.
- **Test gotcha:** fixtures must set `deviceID` ≠ the file base name (real data does), or this bug is invisible.

### 7d. Same device appeared twice ("24" with the count + "sharya24" with 0)
- **Symptom:** After enumerating aimpoint devices, `up/ru/sharyaOnline` showed **both** `24` (delivered count 80) and `sharya24` (count 0) — the same physical device. Same for `vtomske` (`21` + `tomsk21`).
- **Cause:** delivery-side resolution matched the aimpoint by **exact folder string** (`up/ru/sharyaOnline/24`), which failed for the real layout, so the delivery fell back to the path segment (`24`), while enumeration (keyed by aimpoint base name) added `sharya24` separately. Two code paths, two identities.
- **Fix:** make resolution **layout-agnostic and base-name-keyed** so both paths agree. `_aimpoint_keys_under(domain_id)` now returns the plain **list of aimpoint keys** under the domain (no one-json-per-folder assumption — several `.json` may sit in one folder). `_match_aimpoint(domain_id, folder, filename)` resolves a delivered device by: (1) an aimpoint sitting directly in the delivered device folder, else (2) the aimpoint whose **base name is the delivered file's base name** — deliveries are `<filenameBase>_<suffix>.mp4` and the aimpoint is `<filenameBase>.json` (longest base name wins so `tomsk21` beats `tomsk2`). `_process_feed_file` now collects `(folder, filename)` per device. Enumeration keys by base name too, so a device can never be created twice.
- **Note:** delivery resolution now lists by `domain_id` (not the folder's parent), which is always a prefix of the delivered folder for real `dBoardData` paths. Tests must use realistic delivered paths (the old explicit-`domain_id` legacy fixtures broke this assumption).

### 7c. Configured-but-not-delivering devices were invisible (only 1 of N devices showed)
- **Symptom:** `up/ru/vtomske` shows only device `21` though aimpoints exist for `01/11/21/29`; `up/ru/sharyaOnline` shows only `24` though `212/24/29` exist.
- **Cause:** NOT a parsing bug — the pipeline is **delivery-driven** (a device becomes a feed only when a delivery line references it). Verified in the DB: across 30 days only `.../vtomske/21/…/tomsk21_*.mp4` and `.../sharyaOnline/24/…/sharya24_*.mp4` ever delivered. The other devices are configured (aimpoint folders) but produce no files.
- **Fix:** `services/generator._add_aimpoint_only_devices(tally)` — after delivery processing, for each domain in the tally it lists every aimpoint under `{DEVICE_PREFIX}<domain_id>/` and adds any device not already present as a device + feed with a **zero** delivered count. Called from `rebuild_tally`, `run_cycle`, and `backfill_history` (before the push). Reuses the cached `_aimpoint_keys_under` listing and a new `_cache_aimpoints` parallel reader.
- **Consequence (intended):** a configured device that delivers nothing is now visible and flagged — Current tab → **yellow** (delivered 0 vs expected-so-far); Historical → **red** day cells (0 ÷ expected), which can pull the domain's rollup to red. That surfaces a real problem (device configured but down) instead of hiding it. If intentionally-disabled devices become noisy, filter on the aimpoint's `collEnabled` flag.
- **Gotcha:** regenerate the history DB to pick these devices up in the Historical tab.

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

## History: per-day aimpoint + "no aimpoint" gray

### 16. History feed pivot — per-day aimpoint on cell click + gray "no aimpoint"
- **Ask:** In the Historical feed×day pivot, clicking a specific day cell should show the device aimpoint *for that day* (or the most recent from a previous day); no day selected → default to the most recent aimpoint (unchanged); no aimpoint at all → "No aimpoint exists". A feed with **no aimpoint at all** should be gray (expected 0, not red), and a domain whose feeds are all no-aimpoint should be gray too — but **only** when no aimpoint exists at all (a feed/domain that has an aimpoint stays normally colored).
- **`none` band (gray):** `status.NONE_BAND = "none"` + `BAND_ICONS["none"]`. `rollup_band` now ignores `"none"` (a real band always wins), but returns `"none"` when *every* child is `"none"` (distinct from `"red"` = no delivery at all). `filter_domain_band_summary` always keeps `"none"` domains (no sidebar option for it). Gray = `#e5e7eb`/`#6b7280` in `HISTORY_CELL_STYLE_JS`, `DOMAIN_BAND_STYLE_JS`, and `history_data._STATUS_CELL_STYLE`. A feed is "no aimpoint at all" when `_feed_expected > 0` on **no** day in the window. Current tab is unchanged (its feeds never produce `"none"`).
- **Per-day aimpoint (exact day, no fall-back):** `history_data._aimpoint_by_day` returns `{"days": {date: variant_idx}, "variants": [<device rows>, …]}` — one entry per day that *actually has* a stored aimpoint (identical aimpoints deduped into shared variants). Carried per feed as hidden `aimpoint_by_day_json`. `grid_config.HISTORY_FEED_PIVOT_CELL_CLICK_JS` (an `onCellClicked`, replacing the feed pivot's `onRowClicked`) sets `node.data._selected_day` for a day column (regex `^\d{4}-\d{2}-\d{2}$`) and re-expands; `HISTORY_DETAIL_GET_ROUTER_ROWS_JS` shows `variants[days[selected_day]]` for that EXACT day, or `{Aimpoint: "No aimpoint exists"}` if that day isn't in `days` (NO fall-back to a previous day — updated from the earlier change-points approach). With no day selected it uses the default `router_rows_json`.
- **Note / gotcha:** per-day selection uses **stored** per-day aimpoints; the *default* (no day) still prefers the **live** aimpoint (bug #8). So a feed with a live aimpoint but no stored history shows the live one by default yet "No aimpoint exists" on a day click — intentional (per-day = historical).

### 16b. Per-day aimpoint SNAPSHOTTING (so day-to-day changes are actually captured)
- **Context:** S3 keeps only ONE current, non-dated aimpoint per device (`dboard/aimpoints/<domain>/<device>.json`). Originally the per-process aimpoint cache held it for the whole run and backfill stamped that one value onto every day, so **every stored day was byte-identical** (verified: all 274 multi-day devices, e.g. `up/bb/iwcpinc/accra` × 30 days) — `_aimpoint_by_day` always collapsed to 1 variant.
- **Fix (two parts, `services/generator.py`):** (1) **Re-pull at rollover** — `run_cycle` clears `self._aimpoint_cache` on the UTC-midnight rollover, so each new day fetches (and snapshots) its own current aimpoint instead of reusing the process-cached one. (2) **Freeze once written** — the `devices` upsert (`_push_tally_to_sqlite`) now preserves an existing non-empty `aimpoint_json` (+ derived `op_window_*`, `files_expected`) on conflict via `CASE WHEN devices.aimpoint_json IN ('','{}') … THEN excluded ELSE devices.… END`; only counts/health refresh. So a re-push/backfill never clobbers a day's captured snapshot, and a first-empty day can still be filled.
- **Caveat:** this only accrues **going forward** — real day-to-day variation appears once the S3 aimpoint actually changes over subsequent days. Past days already bulk-backfilled with one value stay uniform (S3 has no historical aimpoint to reconstruct); re-backfilling won't differentiate them.

### 17. Current tab — time-aware green/yellow/gray coloring (never red)
- **Ask:** Current view domains/feeds begin **green** and stay green while the delivered count matches the files expected **by the current time** (from the aimpoint's operating hours). Any deviation (extra or missing file for now) → **yellow**. **Never red.** Gray when no aimpoint is available.
- **Expected-so-far:** `log_parser.expected_file_count_so_far(aimpoint, now)` = elapsed operating minutes today (in `hours.tz`, UTC fallback) // `transcoderInterval`. `_operating_intervals` splits overnight windows into same-day `[start,stop)` ranges; `rndm` is excluded (random daily tail). `now` defaults to current UTC.
- **Band:** `status.current_feed_band(feed, now=None)` → `none` (no `aimpoint_json`), else `green` if `feed.count == expected_so_far` else `yellow`. Lazy-imports `log_parser` (log_parser imports status → avoid circular). `build_domain_band_summary(domains, now=None)` and `table_data.feed_detail_rows` now use it (replaced `feed_health_band`, removed). Domain rollup via existing `rollup_band` (yellow>green; all-none → gray). `grid_config.BAND_CELL_STYLE_JS` gained a gray `none` branch (DOMAIN_BAND_STYLE_JS already had one).
- **Scope/known gaps:** Current tab only — Historical tab keeps the percentage bands (`cell_health_band`). On the Current tab the Orange/Red metric cards are now always 0, the "only red feeds" filter matches nothing, and the feed grid's "Expected / Day" column still shows the **full-day** expected (not expected-so-far) — none of these were in scope. README/AGENTS "health bands" sections describe the *historical* model and are now only partially accurate for Current.

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
