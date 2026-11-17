## 1. CSV data fix + migration tooling

- [x] 1.1 Fix the 2 rows in `docs/indicators_position.csv` where `section_cn` (`现金流量表 — 经营活动`) leaked into the `report_type` column — restore correct `section_cn`/`report_type` values.
- [x] 1.2 Add a CSV→rule mapping module (e.g. `indicators_csv_migration.py`) implementing the deterministic mapping from the design (Decision 1): `indicator`→`name`, `indicator_cn`→alias, `section_en`→`module`, `section_cn`→`subgroup`/`selectors[]`, `report_type`→`source_type`+`period_type`, default universal `applies_to`.
- [x] 1.3 Implement `report_type` → `source_type` classification (Decision 2): periodic values → `report`; `实时` → `external`; assign `extractor` per section (`python:table_row` for statement line items, `python:percent_value` for ratio/percent, `llm` for narrative, `auto` otherwise).
- [x] 1.4 Add `scripts/migrate_indicators_csv.py` CLI: reads `docs/indicators_position.csv`, reconciles into `indicator_rules.json` (append CSV-only rules, annotate the 44 overlapping rules with `report_type`+`indicator_cn` alias, preserve hand-authored rules, Decision 3), idempotent. Add `--check`/dry-run flag.
- [x] 1.5 Run the migration; commit regenerated `indicator_rules.json` (46 → 321 rules). Verify `list_indicators()` count and module grouping.

## 2. Engine extensions (`indicators_client.py`)

- [x] 2.1 Extend `profile_company` to return `{industry: <non-bank>, sub_type: null}` for non-bank companies (Decision 4); keep the bank path unchanged.
- [x] 2.2 Confirm `applicable_rules` already admits universal `applies_to.industry: "*"` rules for non-bank profiles; add a regression test if needed.
- [x] 2.3 Add section-selector normalization (Decision 5): strip ordinals (`一、二、（一）`), em-dashes, whitespace; match exact → substring → regex against parsed TOC titles.
- [x] 2.4 For statement modules (`balance_sheet`/`income_statement`/`cashflow`), resolve via `get_financial_statements` first, fall back to `get_section`.
- [x] 2.5 Add `external` `source_type` handling in the batch path: `external` rules go to `unresolved` (note `external source — not extractable from report`) for `extract_indicators`/`get_indicator`; no PDF fetch, no LLM call.
- [x] 2.6 Add a loader entry point for a position CSV: read the `indicator` column → target name list (+ optional `indicators` intersection) → resolve to rules → partition by `source_type`. Reused by the tool + CLI.

## 3. MCP tool (`server.py`)

- [x] 3.1 Implement `extract_indicators_by_position(ticker_or_name, year, csv_path="docs/indicators_position.csv", extractor="auto", indicators=None)` in `indicators_client` (core logic, testable without the server).
- [x] 3.2 Partition: `external` → `skipped` (note `realtime/external — not in report PDF`); `report`/`akshare`/`computed` → delegate to `extract_indicators` batch path.
- [x] 3.3 Return shape: `{stock_code, company_name, year, form, pdf_url, cached, indicators, missing, unresolved, skipped, csv_path}` (Decision 6 + position-extract spec).
- [x] 3.4 Honor `extractor` mode override (`auto`/`llm`/`python`) with the same semantics as the extraction script.
- [x] 3.5 Register `@app.tool extract_indicators_by_position` in `server.py` wrapped in `@_tool_safe`.
- [x] 3.6 Verify reuse: no independent PDF/LLM/caching code — all delegation to `indicators_client` + `report_cache`.

## 4. CLI script (`scripts/extract_indicators_by_position.py`)

- [x] 4.1 Implement the standalone CLI mirroring `scripts/extract_indicators.py`: accept ticker/name + `--year`, `--from-file`, `--csv`, `--extractor {auto|llm|python}`, `--indicators`, `--out-dir`.
- [x] 4.2 Write JSON (`<stock>_<year>.json`) matching the tool result shape (incl. `skipped`, `csv_path`, extractor mode in provenance).
- [x] 4.3 Write CSV (`<stock>_<year>.csv`) flat table `indicator,value,unit,source_type,extractor,period,note,status` — one row per attempted indicator; `missing`/`unresolved`/`skipped` rows with empty value + note + `status`.
- [x] 4.4 Confirm the script imports `indicators_client` + `report_cache` only — no logic duplication.

## 5. Docs regeneration

- [x] 5.1 Regenerate `docs/indicators-methodology.md` (`uv run python indicators_client.py --render-methodology`) — now covers 319 indicators across non-bank modules.
- [x] 5.2 Refresh `docs/indicators-coverage.{md,csv}` to reflect the merged rule set.
- [x] 5.3 Update `README.md` indicator section: mention the CSV-sourced rule set, the new `extract_indicators_by_position` tool, and the migration script.

## 6. Tests + selfcheck

- [x] 6.1 Add a CSV-migration round-trip test (Decision 1 + idempotency + overlap-preservation scenarios from `indicator-rules` spec).
- [x] 6.2 Add a non-bank profiling test (600519 → `{industry: <non-bank>, sub_type: null}`; universal rules apply, bank-scoped rules excluded).
- [x] 6.3 Add an `external`-skip test: `PE-TTM`/`PB` appear in `skipped`, no PDF fetch / LLM call recorded.
- [x] 6.4 Add `extract_indicators_by_position` tool tests (default CSV, `--csv` override, `indicators` intersection, unknown name → `missing`, `extractor` mode override) using `test_fixtures/`.
- [x] 6.5 Add CLI tests: JSON+CSV output files exist; CSV includes `skipped`/`unresolved`/`missing` rows with correct `status`.
- [x] 6.6 Add a section-selector normalization test (descriptive `section_cn` resolves against a real TOC outline fixture).
- [x] 6.7 Run `.venv/bin/python -m pytest test_cnreport.py -v -p no:logfire` (per the test-runner gotcha — `uv run` fails on missing `../models`).
- [x] 6.8 Run `uv run python selfcheck.py` and `uv run python selfcheck_cache.py` (offline).
- [x] 6.9 Run `openspec validate "extract-indicators-by-position"` and fix any spec drift.
