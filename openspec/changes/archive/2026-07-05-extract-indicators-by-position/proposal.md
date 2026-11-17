## Why

The banking-indicator engine (`indicator_rules.json` + `indicators_client.py`) only knows 46 banking rules, but `docs/indicators_position.csv` is a curated catalog of 319 indicators mapped to where each one lives in a periodic report — across the three statements, notes, risk management, shareholders, HR, profit distribution, and more. Only 44 overlap with the current rule set. Callers who want "all the indicators from a financial report" have no single path that uses this position catalog; the 273 non-banking indicators are unreachable from the engine today. This change makes the CSV the maintained source of the rule set and exposes a dedicated CSV-driven extraction surface, so a company's annual report can be mined for the full indicator set in one pass.

## What Changes

- Migrate `docs/indicators_position.csv` (319 indicators) into `indicator_rules.json`. Each CSV row becomes one rule: `indicator` → `name`; `indicator_cn` → `alias`; `section_cn`/`section_en` → `selectors[]` chain + `module`/`subgroup`; `report_type` → `period_type` + a `source_type` classification; default `applies_to: {industry: "*", sub_types: ["*"], companies: ["*"]}` so non-bank indicators apply universally.
- Classify each rule by `report_type`: indicators that appear in 年报/半年报/季报/年度 → `source_type: "report"` (extracted from the report PDF); indicators marked `实时` / external market data (PE-TTM, PB, PS-TTM, 市值, etc.) → `source_type: "external"` and are **skipped** during report extraction (listed in `skipped`, never sent to the PDF or LLM), because they are not present in the financial report.
- Extend `indicators_client.py` so company profiling and applicability degrade gracefully for **non-bank** companies: universal rules (`applies_to.industry: "*"`) apply regardless of industry; non-bank companies receive an `industry` without a bank `sub_type` instead of being unprofileable. The banking-specific profiling path is unchanged for banks.
- Add a section-selector normalizer so the CSV's descriptive `section_cn` labels (e.g. `资产负债表 — 一、资产`, `管理层讨论与分析 — 财务概要`, `财务报表附注`) resolve against a report's actual TOC titles via the existing `selectors[]` walk (exact → substring → regex), reusing `report_cache` for the PDF text.
- Fix a data-quality defect in `docs/indicators_position.csv`: 2 rows have a `section_cn` value (`现金流量表 — 经营活动`) leaked into the `report_type` column (a CSV escape error); corrected during migration.
- New MCP tool `extract_indicators_by_position(ticker_or_name, year, csv_path?, extractor?, indicators?)` that extracts the indicator set named in a position CSV (default `docs/indicators_position.csv`) for one company/year, routing each through the merged engine, returning the standard result shape plus a `skipped` list for external/realtime indicators.
- New standalone CLI `scripts/extract_indicators_by_position.py` mirroring the tool offline, with `--csv`, `--extractor {auto|llm|python}`, `--indicators`, and `--out-dir`, writing JSON + CSV (reusing the engine — no logic duplication).

## Capabilities

### New Capabilities
- `indicator-position-extract`: MCP tool `extract_indicators_by_position` that extracts the indicators named in a position CSV for one company/year via the merged engine, with a `skipped` list for external/realtime indicators not present in the report PDF.
- `indicator-position-script`: standalone CLI `scripts/extract_indicators_by_position.py` that runs the CSV-driven extraction offline and writes JSON + CSV output, mirroring the existing `scripts/extract_indicators.py` contract.

### Modified Capabilities
- `indicator-rules`: rule set now sourced/maintained from `docs/indicators_position.csv` (a migration step converts each CSV row to a rule); rules carry a `report_type`-derived classification distinguishing report-PDF indicators from external/realtime ones; company profiling and applicability handle non-bank companies (universal `applies_to.industry: "*"` applies regardless of industry; non-bank companies profile without a bank `sub_type`).

## Impact

- **Data**: `indicator_rules.json` grows 46 → 319 rules; `docs/indicators_position.csv` becomes the maintained human-editable source (re-migrate on edit). 2 CSV rows corrected for the `report_type` escape defect.
- **Code**: `indicators_client.py` extended (non-bank profiling, selector normalization, `external` source-type skip, CSV-driven entry point); `indicators_extractors.py` reused as-is (python-first with LLM fallback); `server.py` gains one `@app.tool`; new `scripts/extract_indicators_by_position.py`.
- **Docs**: `docs/indicators-methodology.md` regenerated (now covers 319 indicators across non-bank modules); `docs/indicators-coverage.{md,csv}` refreshed.
- **APIs**: one new MCP tool `extract_indicators_by_position`; existing `list_indicators` / `get_indicator` / `extract_indicators` automatically gain the 319 indicators (no breaking change to their contracts). `indicator_rules.json` schema gains an optional `report_type` field and a new `source_type: "external"` value — additive, existing rules unaffected.
- **Dependencies**: none new (reuses `report_cache`, `ai_extract`, akshare).
- **Tests**: extend `test_cnreport.py` + `test_fixtures/` with non-bank indicator cases, CSV-migration round-trip, `external` skip behavior, and the new tool/CLI.
