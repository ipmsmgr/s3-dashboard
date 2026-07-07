# Agent-Tool Implementation Prompt: Existing Project Change

## Project Mode

- [x] Existing Project Change

## Intended Coding Agent

This prompt is tool-neutral. Use it with any coding agent or LLM tool that can read Markdown, run shell commands, and read/write files in a local repository.

## Project Name

`acb-generator` — this is the existing repository being modified. Its installed Python package is `domain_feed_health_dashboard` (currently version `2.0.0` per `pyproject.toml`).

## Source Package

You are working with two local repositories on the same machine:

1. **Target repository (modify this one):** `acb-generator` — the repository you are running in / pointed at. Inspect it before changing anything.
2. **Source-to-merge repository (read from this one, do not modify it):** `Dashboard-Prototype`, located as a sibling directory to `acb-generator` (i.e. `../Dashboard-Prototype` relative to `acb-generator`, or wherever it is mounted in your environment — locate it by directory name `Dashboard-Prototype` if the relative path differs). If this repository is not present in your environment, stop and report it as a blocker — the required source files (`app.py`, `ui.py`, `grid_config.py`, `table_data.py`) listed below do not exist anywhere else.

Do not invent files, functions, modules, commands, or behavior beyond what is described below or what you verify by inspecting both repositories. Inspect both repositories before writing code.

## Confirmed Codebase Assessment

### Repository Summary — acb-generator (target)

- Repository/package name: `acb-generator` / `domain_feed_health_dashboard`, v2.0.0.
- Apparent purpose: polls S3 for feed-delivery and device JSON files, maintains a live daily in-memory tally, persists completed UTC days to SQLite with 30-day retention, and exposes that data through a Textual terminal UI. No web UI exists yet, even though `streamlit`, `streamlit-aggrid`, and `pandas` are already listed as dependencies in `pyproject.toml`.
- Language/runtime: Python ≥3.11.
- License: none found in the repository.
- Existing agent instructions: none found (no `AGENTS.md` / `CLAUDE.md` in `acb-generator`).
- Test coverage: **no `tests/` directory exists in `acb-generator` today.** The only validation script is `scripts/manual_test_generator.py`, which requires live AWS credentials and is not a pytest suite.

### Repository Structure — acb-generator

```text
src/domain_feed_health_dashboard/
  data_model.py        # DomainRecord / FeedRecord / DeviceRecord (V2, real-data fields).
                        # RouterAccessPoint = DeviceRecord (alias kept on purpose, see its own
                        # docstring, "so existing UI code compiles without changes").
  status.py             # STATUS_SEVERITY, domain_status_from_feeds, build_domain_summary,
                         # overall_metrics — API-IDENTICAL to Dashboard-Prototype's status.py.
  services/generator.py # Generator class: S3 polling, in-memory DomainSetTally,
                         # midnight SQLite push, 30-day prune (DB_RETENTION_DAYS = 30).
  services/log_parser.py# feed-line + device-JSON parsing, folder/date extraction.
  db/schema.py           # SQLite DDL: domain_sets, devices, feeds, snapshot_meta. 30-day retention.
  db/repository.py       # Repository (read-only): get_history_domains(set_date=None, days=30),
                          # available_dates(), domain_set_summary(set_date=None).
                          # Returns the SAME DomainRecord/FeedRecord/DeviceRecord tuples used
                          # everywhere else in this package.
  aws/scanner.py, aws/s3_client.py   # S3 listing/reading helpers used by Generator.
  utils/cache.py, utils/logger.py
scripts/run_generator.py
  # Textual TUI app ("Aimpoint Dashboard"). Has its OWN, SEPARATE data pipeline:
  # AimpointRecord dataclass, S3Source, open_cache()/scan_deliveries()/get_delivery_counts()
  # writing to a DIFFERENT SQLite schema (seen_deliveries, delivery_scan_cursor in
  # aimpoint_cache.sqlite3) — this does NOT use Generator, Repository, or DomainRecord/
  # FeedRecord at all. It has its own "Today" and "History" tabs.
  # _repaint_history_feed_grid() (around line 1071) builds the reference UI behavior for the
  # "30-day grid for feed": one row per device, one column per day (newest day leftmost),
  # cell = that day's file count colored RED/YELLOW/GREEN via status_label()/_RYG.
scripts/manual_test_generator.py   # live-AWS smoke test, not pytest.
```

**Important architectural note — two independent pipelines exist in `acb-generator` today:**

1. `services/generator.py` (`Generator`) + `db/schema.py` + `db/repository.py` (`Repository`) — produces `DomainRecord`/`FeedRecord`/`DeviceRecord` objects. This is the pipeline the rest of this prompt wires the new Streamlit UI to.
2. `scripts/run_generator.py`'s own inline `AimpointRecord`/`S3Source`/`scan_deliveries` pipeline, with its own separate SQLite cache file and schema, used only by the Textual TUI.

These two pipelines read overlapping but not identical S3 data using different parsing logic, and they are **not** guaranteed to produce identical counts. **Do not merge them, do not make the new Streamlit UI call into pipeline 2, and do not modify pipeline 2.** The 30-day grid being added to the Streamlit UI must be built from pipeline 1 (`Repository`), reproducing the *visual pattern* of `_repaint_history_feed_grid()` (device/feed rows × day columns, colored RED/YELLOW/GREEN, newest day first) using `Repository` data — not by copying `scripts/run_generator.py`'s scanning code.

### Repository Structure — Dashboard-Prototype (source to port from; read-only)

```text
src/domain_feed_health_dashboard/
  app.py          # Streamlit entry point -> ui.main().
  ui.py            # Sidebar controls, CSS, overall-metric cards, _render_master_detail_domain_table().
  grid_config.py   # AgGrid GridOptionsBuilder helpers; JS cell-style + master/detail JsCode callbacks.
  table_data.py    # domain_master_detail_dataframe(), feed_detail_rows(), router_rows() — nested
                    # payloads are JSON strings in hidden DataFrame columns (feed_rows_json,
                    # router_rows_json), not Python list/dict objects, specifically to avoid
                    # Streamlit's "DataFrame contains non-hashable data" warning.
  sample_data.py   # Deterministic simulated-data generator — DO NOT PORT (see decision below).
  data_model.py / status.py  # V1 versions of the same dataclasses/status module.
tests/  test_status.py, test_sample_data.py, test_grid_config.py, test_table_data.py
```

### Confirmed Field-Compatibility Evidence (acb-generator V2 `data_model.py` vs. Dashboard-Prototype V1 usage)

Verified compatible — no change needed:
- `status.py`: identical public API in both repos.
- `FeedRecord`: `feed_id`, `status`, `count`, `location`, `observed_time`, `latitude`, `longitude`, `feed_type`, `source_system`, `routers` all exist in both V1 and V2 with the same names and types. `table_data.FEED_VISIBLE_COLUMNS` only reads fields that exist on the V2 `FeedRecord`.
- `Repository.get_history_domains()` / the live `Generator.tally.to_domain_records()` both already return V2 `DomainRecord`/`FeedRecord` tuples — the data layer needs no changes to support the ported UI.

**Confirmed required adaptation (one concrete gap):**
- Dashboard-Prototype's `table_data.router_rows()` reads `router.router_id` and `grid_config._router_detail_grid_options()` defines an AgGrid column `{"field": "router_id", ...}`. The V2 `DeviceRecord` (aliased as `RouterAccessPoint`) has **no `router_id` field** — it has `device_id` instead (data_model.py's own docstring: "Device (replaces RouterAccessPoint for real data)"). When porting `table_data.py` and `grid_config.py`, rename every `router_id` reference to `device_id` (both the Python dict key/column constant and the AgGrid `columnDefs` field/headerName). This is the only required field-name fix to make the ported UI run against real V2 records; do not change any other field names without similar verified evidence.

### Confirmed Decisions From User (do not revisit these)

| Decision | Confirmed Answer |
|---|---|
| Project name to use in code, docs, this prompt | `acb-generator` |
| Dashboard-Prototype's `sample_data.py` simulated-data path | **Remove** — do not port `sample_data.py`. The merged dashboard only ever shows real data from `Generator`/`Repository`. |
| `scripts/run_generator.py` (Textual TUI) | **Keep completely untouched.** It must keep working exactly as today, unmodified, running independently alongside the new Streamlit dashboard. |
| Coding agent naming in this prompt | Keep tool-neutral (no vendor-specific tool name). |

## Confirmed Existing Project Change Brief

### Requested Change

Merge Dashboard-Prototype's Streamlit + AgGrid UI layer into `acb-generator`, wire it to `acb-generator`'s real data (`Generator` for "today", `Repository` for 30-day history) instead of simulated data, and add a new 30-day feed-history grid view to that UI that visually mirrors `scripts/run_generator.py`'s existing `_repaint_history_feed_grid()` behavior (device/feed rows × day columns, RED/YELLOW/GREEN colored cells, newest day first) — but sourced from `Repository`, not from `scripts/run_generator.py`'s separate pipeline.

### Current Behavior To Preserve

- `scripts/run_generator.py` — every CLI flag, file path, table layout, drill-down/back/refresh/quit keybinding, and its own separate SQLite cache file (`aimpoint_cache.sqlite3` by default) must keep working exactly as today. Do not edit this file.
- `Generator`, `Repository`, `log_parser`, `db.schema` public APIs and the SQLite schema (`domain_sets`, `devices`, `feeds`, `snapshot_meta`) — unchanged. No migration needed; this change is additive/read-only against this schema.
- `status.py` rollup logic — unchanged; it is already shared and correct for both UIs.
- Existing `pyproject.toml` dependencies (`streamlit`, `streamlit-aggrid`, `pandas`, `boto3`, `botocore`, `tenacity`, `textual`) already cover everything needed; do not add new runtime dependencies without first checking whether one of these already covers the need.

### Proposed Implementation Scope

| Area | In scope? | Required change |
|---|---:|---|
| New Streamlit UI files (`app.py`, `ui.py`, `grid_config.py`, `table_data.py`) | Yes | Port from `Dashboard-Prototype`, adapted to import and use `acb-generator`'s `data_model.py` (already on the Python path as `domain_feed_health_dashboard.data_model`), fix the `router_id` → `device_id` gap described above, and replace the simulated-data call sites with calls into `Generator`/`Repository` (see "Required Work" below). |
| `sample_data.py` | No | Do not port. Not part of the merged package. |
| New 30-day history view/section in the Streamlit UI | Yes | New code (e.g. a new module such as `history_view.py`, or a clearly separated section/tab inside `ui.py` — your call, document the choice) that uses `Repository.available_dates()` and `Repository.get_history_domains()` to build a feed × day pivot table per domain, colored RED/YELLOW/GREEN, newest day first, matching the visual pattern of `_repaint_history_feed_grid()`. |
| `data_model.py`, `status.py`, `services/*`, `db/*`, `aws/*`, `utils/*` | No changes expected | These already support the ported UI per the verified evidence above. Only touch one of these files if you discover, with concrete evidence, that the UI genuinely cannot function without a change here — if so, stop and report it as a blocker rather than guessing. |
| `scripts/run_generator.py` | Not touched | Must keep working unmodified. |
| Tests | Yes | Add pytest coverage for the ported/adapted UI modules and the new history-grid logic. `acb-generator` has no `tests/` directory today — create one (mirroring Dashboard-Prototype's `test_status.py` / `test_sample_data.py` / `test_grid_config.py` / `test_table_data.py` style, adapted to remove anything that depended on `sample_data.py`). |
| Docs | Yes | Create `README.md` and `AGENTS.md` in `acb-generator` (neither exists today). Document both UIs (`scripts/run_generator.py` Textual TUI and the new `streamlit run src/domain_feed_health_dashboard/app.py` web UI) honestly — what each does, how they relate, and that they read overlapping but separately-implemented data pipelines. |
| Dependencies | No new dependencies | All required packages are already declared in `acb-generator/pyproject.toml`. |

### Acceptance Criteria

- [ ] `pip install -e ".[dev]"` succeeds in `acb-generator`.
- [ ] `streamlit run src/domain_feed_health_dashboard/app.py` starts without import/runtime errors and renders real `Generator`/`Repository`-backed domains and feeds (not simulated data) in the existing nested domain → feed → device(router) AgGrid master/detail table.
- [ ] The new 30-day history view renders a feed × day pivot grid (newest day first) with RED/YELLOW/GREEN colored cells, scoped to a selected domain, built from `Repository` data.
- [ ] `python scripts/run_generator.py --help` (or equivalent non-destructive invocation) still works exactly as before — confirm by diffing its behavior/flags against current behavior, since the file must be untouched.
- [ ] New pytest tests exist for the ported/adapted UI logic and the new history-grid logic; `python -m pytest` passes.
- [ ] `README.md` and `AGENTS.md` exist in `acb-generator` and accurately describe both UIs and the two-pipeline architecture note above.
- [ ] No `sample_data.py`-style simulated-data path exists anywhere in the merged dashboard.

## Non-Negotiable Rules

- No stubs.
- No mocks in runtime/production code (test doubles such as `moto[s3]`, already a dev dependency, are fine inside `tests/`).
- No fake success.
- No synthetic runtime behavior — the merged Streamlit dashboard must show real `Generator`/`Repository` data, never simulated data.
- Do not modify `scripts/run_generator.py`.
- Do not modify the SQLite schema in `db/schema.py`.
- Do not build the new 30-day grid by calling into or duplicating `scripts/run_generator.py`'s separate `AimpointRecord`/`scan_deliveries` pipeline — use `Repository` only.
- Do not port `sample_data.py` or reintroduce a simulated-data mode.
- Preserve unrelated behavior.
- Use minimal diffs; do not reformat unrelated files.
- Do not remove features unless explicitly required (none are required to be removed here other than the simulated-data path, which is explicitly required).
- Update tests/docs/examples when behavior changes.
- Run available validation commands, fix failures in a loop when feasible, rerun failed commands after fixes, and report final results honestly.
- Clean cache/build artifacts (`__pycache__`, `.pytest_cache`, etc.) before considering the work done.

## Required Devil's Advocate Review

Before each implementation iteration and before final delivery, perform this review:

| Question | Answer | Evidence | Result |
|---|---|---|---|
| Is this change directly required by the confirmed scope? | Only port/adapt the four named UI files, add one new history-grid feature backed by `Repository`, add tests/docs. | This brief's "Proposed Implementation Scope" table | PASS |
| Does this preserve unrelated behavior? | `scripts/run_generator.py`, `db/schema.py`, `services/*`, `aws/*` are explicitly not to be touched. | "Current Behavior To Preserve" section | PASS |
| Is there repository evidence for the file, command, API, schema, or behavior being changed? | All claims above cite specific files/line areas inspected in both repositories. | Codebase Assessment section | PASS |
| Is this the smallest safe change? | Reuses existing `Repository`/`Generator`/`status.py` APIs unmodified; only one verified field-name fix (`router_id` → `device_id`) is required. | Field-Compatibility Evidence section | PASS |
| Does this introduce an unapproved dependency, rewrite, public contract change, or artifact change? | No new dependencies; no change to `Generator`/`Repository`/schema public contracts. | "Dependencies" row in scope table | PASS |
| Does this conflict with any non-negotiable rule? | No. | Non-Negotiable Rules section | PASS |
| What is the likely failure mode of this change? | Confusing the two S3-ingestion pipelines and accidentally wiring the new grid to `scripts/run_generator.py`'s cache instead of `Repository`, or silently changing `scripts/run_generator.py`. | Architectural note above | Mitigated by explicit rule above — re-check this specific risk before final delivery |

If any required answer becomes `BLOCKED` during implementation (for example, a second real field gap is discovered beyond the `router_id`/`device_id` one already identified), stop and report the blocker instead of guessing.

## Required Agentic Implementation Loop

The coding agent must work in this loop:

1. Inspect the repository or generated project structure.
2. Identify relevant install, build, run, test, lint, typecheck, packaging, and artifact-validation commands.
3. Make the smallest coherent implementation change.
4. Run the relevant validation commands.
5. If validation fails:
   - capture the exact failing command;
   - capture the relevant error output;
   - identify the likely root cause;
   - make the smallest targeted fix;
   - rerun the same failed command.
6. Repeat the fix/rerun cycle until all required checks pass or a check is blocked by a documented environment, dependency, credential, network, or source limitation (for example: no live AWS credentials are available to run `scripts/manual_test_generator.py` — that script is out of scope for this change and does not need to pass; use `moto[s3]` for any new S3-touching tests instead, consistent with the existing dev dependency).
7. Do not move to packaging or final response while an in-scope failure remains unfixed.
8. Do not claim success for any command that was not actually run.

## Required Work

1. Inspect `acb-generator`'s current structure and `Dashboard-Prototype`'s `app.py`/`ui.py`/`grid_config.py`/`table_data.py` in full before writing code.
2. Copy `app.py`, `ui.py`, `grid_config.py`, `table_data.py` into `acb-generator/src/domain_feed_health_dashboard/`, adapting:
   - all `router_id` references to `device_id` (Python and AgGrid `columnDefs`), per the confirmed field-compatibility evidence;
   - every call site that currently calls `sample_data.generate_domains(...)` to instead source live data from a `Generator` instance and 30-day history from a `Repository` instance (construct these using the same `S3_BUCKET`/`db_path` conventions already established in `services/generator.py` and `scripts/manual_test_generator.py` — do not invent new bucket names or paths);
   - any other reference that fails against the real `data_model.py` once you run the app — investigate each failure against actual `data_model.py` field names before changing anything, and do not guess.
3. Do not port `sample_data.py`. Remove any import of it.
4. Add a new 30-day feed-history view to the Streamlit UI, built from `Repository.available_dates()` and `Repository.get_history_domains()`: a feed × day pivot table for a selected domain, newest day first, cells colored RED/YELLOW/GREEN by that feed's `status` on that day. Keep this visually and conceptually analogous to `scripts/run_generator.py`'s `_repaint_history_feed_grid()`, without reusing or duplicating that function's underlying S3-scanning code.
5. Add or update `tests/` in `acb-generator` covering: the adapted `table_data.py`/`grid_config.py` logic (using fixture `DomainRecord`/`FeedRecord`/`DeviceRecord` objects, no live S3/AWS calls), and the new history-grid pivot logic (using a fixture/mock `Repository`, e.g. via `moto[s3]` or plain fixture data — do not require live AWS credentials for any test).
6. Create `README.md` and `AGENTS.md` in `acb-generator`, documenting setup, both UIs (`scripts/run_generator.py` and `streamlit run src/domain_feed_health_dashboard/app.py`), the two-pipeline architecture note, run/test commands, and known limitations.
7. Run validation commands discovered in the repository (see Validation Matrix).
8. Produce a changed-file summary as part of the final response.

## Validation Matrix

| Check | Command | Required? | Expected Result |
|---|---|---:|---|
| Install dependencies | `pip install -e ".[dev]"` (from `acb-generator/`) | Yes | Installs successfully, no new dependencies needed |
| Run tests | `python -m pytest` (from `acb-generator/`) | Yes | All tests pass, including new ones for the ported UI and history grid |
| Streamlit smoke test | `streamlit run src/domain_feed_health_dashboard/app.py` | Yes | Starts without import/runtime errors |
| Textual TUI unaffected | Inspect `scripts/run_generator.py` diff | Yes | Zero diff against its pre-change state |
| Documentation check | Manual review of `README.md` / `AGENTS.md` | Yes | Matches actual implemented behavior, not aspirational behavior |
| Live-AWS manual script | `python scripts/manual_test_generator.py` | No | Not required to pass in this change (needs live AWS credentials); do not claim it was run unless it actually was |

If a command cannot be run in the environment, state that honestly and explain why.

## Repository Cleanliness Gate

Before considering the work complete:

- remove `__pycache__` directories created during this work;
- remove `.pytest_cache`;
- do not commit/leave behind virtual environments;
- do not introduce secrets or credentials;
- confirm no large generated runtime artifacts (e.g. new SQLite DB files, log files) were added to the repository by your own test runs — clean up anything your own commands generated, leaving pre-existing files (`aimpoint_cache.sqlite3`, `aimpoint_dashboard.log`, `trash/`) untouched.

## Final Response Requirements

Report:

- what changed;
- files changed/created and why, including which files were ported from `Dashboard-Prototype` versus newly written;
- the exact `router_id` → `device_id` fix applied (and any additional field-compatibility fixes discovered, with evidence);
- validation commands actually run and their results;
- confirmation that `scripts/run_generator.py` is byte-for-byte unchanged;
- known limitations (for example, no live-AWS end-to-end validation was possible without credentials);
- cleanup performed.
