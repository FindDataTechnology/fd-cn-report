## Context

`cnreport-mcp` already has a banking-indicator engine: `indicator_rules.json` (46 rules) + `indicators_client.py` (rule load → company profile → applicability filter → section resolve → extractor dispatch → compute → cache) + `indicators_extractors.py` (pluggable python extractors) + `report_cache.py` (one-PDF-fetch caching). Five capabilities are specced: `indicator-rules`, `indicator-catalog`, `indicator-lookup`, `indicator-batch-extract`, `indicator-extraction-script`.

`docs/indicators_position.csv` is a separate, broader catalog: 319 unique indicators (352 rows), each mapped to `indicator` (zh), `indicator_cn` (en), `section_en`/`section_cn` (where it lives), and `report_type` (which periodic reports contain it). Only 44 overlap with the existing 46 rules; 273 are unreachable from the engine today. The CSV spans banking statements plus non-bank sections (HR, shareholders, suppliers, customer info, segment, profit distribution, risk management, market data). Two data-quality defects: 2 rows where a `section_cn` value (`现金流量表 — 经营活动`) leaked into the `report_type` column.

The user wants the CSV to drive indicator extraction from financial reports, merged into the existing engine (single rule set, single engine) with a dedicated MCP tool + CLI surface.

## Goals / Non-Goals

**Goals:**
- Make `docs/indicators_position.csv` the maintained source of the rule set: a migration step converts each CSV row into a rule in `indicator_rules.json`, growing it 46 → 319.
- All 319 indicators reachable from the existing `list_indicators` / `get_indicator` / `extract_indicators` / `scripts/extract_indicators.py` with no contract change.
- A dedicated `extract_indicators_by_position` MCP tool + `scripts/extract_indicators_by_position.py` CLI that extract the indicator set named in a position CSV for one company/year, reusing the batch engine.
- Honest scope boundary: indicators not present in the report PDF (实时 / external market data) are classified `source_type: "external"` and reported in a `skipped` list — never sent to the PDF or LLM.
- Non-bank companies (e.g. 600519 贵州茅台) are profiled and served universal indicators, not rejected by the banking-only profiling path.

**Non-Goals:**
- Fetching realtime/external market indicators (PE-TTM, PB, 市值, 基金持仓) from akshare or any market-data source — they are classified and skipped here; a future route may add them.
- Re-tuning per-indicator extractors for high precision across all 273 new rules — the migration assigns sane defaults (python-first for line items, llm for narrative); precision tuning is ongoing data-driven work.
- Restructuring `indicator_rules.json` into per-module files — single file stays the source of truth.
- Changing the contracts of `get_indicator`, `extract_indicators`, `list_indicators`, or the existing `scripts/extract_indicators.py`.

## Decisions

### Decision 1: CSV row → rule mapping (mechanical, idempotent)
Each CSV row becomes one rule with fields derived by a deterministic mapping (no per-rule hand-authoring):

| Rule field | Source |
|---|---|
| `name` | `indicator` (zh, exact) |
| `aliases` | `[indicator_cn]` (en) + normalized variants |
| `module` | map from `section_en` prefix: `Balance Sheet`→`balance_sheet`, `Income Statement`→`income_statement`, `Cash Flow Statement`→`cashflow`, `Statement of Comprehensive Income`→`income_statement`, `Computed`→`financial_ratio`, everything else→`report_section` |
| `subgroup` | `section_cn` |
| `applies_to` | `{industry: "*", sub_types: ["*"], companies: ["*"], exclude_companies: []}` (universal) |
| `source_type` | see Decision 2 |
| `source.selectors` | `[{section: section_cn, fallback: true}]`; when `section_en` contains ` / Notes`, append a second entry targeting the notes section |
| `extractor` | `python:table_row` for statement line items (sections with 一、二、 ordinals), `python:percent_value` for ratio/percent indicators (names matching 率/比率/比例 or `Computed`), `llm` for narrative sections (Mgmt Discussion, risk text), `auto` otherwise |
| `unit` | `%` for percent indicators, `人` for HR sections, `股` for share-change sections, `元` default |
| `period_type` | `annual` if `report_type` ⊆ {年报, 年度, 年报/半年报, 年报/半年报/季报, 季报/半年报/年报}, `quarterly` if `report_type` = 季报/半年报, else `annual` |
| `direction` | `none` |
| `note` | `sourced from indicators_position.csv (section: <section_cn>)` |

**Alternatives considered:** hand-author 273 rules (rejected — unsustainable, defeats data-driven ethos); keep CSV separate at runtime (rejected by user — chosen merge).

### Decision 2: `report_type` → `source_type` classification
- Periodic-report values (`年报`, `年度`, `年报/半年报`, `年报/半年报/季报`, `季报/半年报/年报`, `季报/半年报`) → `source_type: "report"`.
- `实时` (8 indicators: PE-TTM, PB, PS-TTM, PCF-TTM, 市值, etc., sections `Market Data (External)` / `Fund Holdings (External)`) → `source_type: "external"`.
- The 2 buggy rows (`report_type = "现金流量表 — 经营活动"`) → corrected in the CSV first (move back into `section_cn`), then classified `report`.
- Adds a new optional `report_type` field on the rule (additive; existing rules unaffected) and a new `source_type: "external"` value.

### Decision 3: Overlap reconciliation (44 shared indicators)
For the 44 indicators present in BOTH the CSV and the existing 46 rules: **keep the existing rule** (it carries richer, bank-specific `selectors[]` chains, `applies_to`, `direction`) and annotate it with `report_type` + ensure `aliases` includes the CSV's `indicator_cn`. The 273 CSV-only indicators are appended. The 2 banking rules not in the CSV (`拨备覆盖率`, `拨贷比_coverage`) stay as-is. This preserves the curated banking behavior while folding in the CSV's breadth.

### Decision 4: Non-bank company profiling + universal applicability
Extend `profile_company` so non-bank companies (not in the bank ticker lookup AND name has no `银行` keyword) return `{industry: "general"|"non-bank"|<derived>, sub_type: null}` instead of failing/unprofileable. Applicability already matches `applies_to.industry: "*"` against any industry, so universal CSV rules apply to non-banks automatically; bank-scoped rules (`industry: "bank"`) correctly stay bank-only. The banking profiling path (国有大行/股份制/城商行/农商行) is unchanged for banks.

### Decision 5: Section-selector normalization for descriptive labels
The CSV's `section_cn` values are descriptive (`资产负债表 — 一、资产`, `管理层讨论与分析 — 财务概要`, `财务报表附注`), not exact TOC titles. Extend `resolve_selector` to normalize both selector and TOC titles before matching: strip ordinals (`一、二、（一）`), em-dashes, and whitespace; match exact → substring → regex. For statement modules (`balance_sheet`/`income_statement`/`cashflow`), resolve via `get_financial_statements` first (it already returns the 合并 statement text via TOC, robust to title variance) and fall back to `get_section`. This reuses existing PDF/cache infra — no new fetch path.

### Decision 6: New tool/CLI are thin entry points over the batch engine
`extract_indicators_by_position(ticker_or_name, year, csv_path="docs/indicators_position.csv", extractor="auto", indicators=None)`:
1. Read the CSV's `indicator` column → the target indicator set (intersect with `indicators` if given).
2. Resolve each name to a rule in the merged set (name → alias → normalized substring). Unknown names → `missing`.
3. Partition by `source_type`: `external` → `skipped` (note: `realtime/external — not in report PDF`); `report`/`akshare`/`computed` → delegate to the existing `extract_indicators` batch path (one PDF fetch, batched LLM per section, python extractors, computed ratios, `{stem}.indicators.json` bundle cache).
4. Return `{stock_code, company_name, year, form, pdf_url, cached, indicators, missing, unresolved, skipped, csv_path}`.

The CLI `scripts/extract_indicators_by_position.py` mirrors this offline with `--csv`, `--extractor {auto|llm|python}`, `--indicators`, `--out-dir`, writing `<stock>_<year>.json` + `<stock>_<year>.csv` (CSV includes `skipped`/`missing`/`unresolved` rows with notes). Both import `indicators_client` + `report_cache` — no logic duplication.

**Extractor mode semantics** reuse the existing contract: `auto` uses each rule's declared extractor; `python` skips `llm`-declared report rules (→ `unresolved`); `llm` forces LLM for report rules.

### Decision 7: Migration is a maintained, re-runnable step
A migration function (`migrate_csv_to_rules(csv_path, rules_path)`, exposed as `scripts/migrate_indicators_csv.py`) reads the CSV and reconciles into `indicator_rules.json`: appends CSV-only rules, annotates overlapping rules with `report_type`/`indicator_cn` alias, leaves hand-authored rules intact, and is idempotent (re-running produces the same JSON). The CSV remains the human-editable source of truth; re-running the migration after a CSV edit refreshes the rules. `docs/indicators-methodology.md` + `docs/indicators-coverage.{md,csv}` are regenerated afterward.

## Risks / Trade-offs

- **[CSV section labels are bank-flavored]** Non-bank reports use different TOC titles (e.g. a non-bank balance sheet has no `一、资产` grouping). → Selector normalization (Decision 5) + `get_financial_statements` fallback; indicators that don't resolve land in `missing` with the tried selectors recorded — reported honestly, not silently dropped.
- **[Auto-assigned extractors may have low precision on 273 rules]** Python extractors are conservative (return `null` on no match rather than a wrong number); LLM covers narrative; `unresolved`/`missing` are per-indicator. Tuning is ongoing and data-driven (edit the rule's `extractor`, no code change). Acceptable for a first pass.
- **[`indicator_rules.json` grows to 319 rules]** Still one file loaded once per call; performance unaffected. If it becomes unwieldy, split per-module later (non-goal here).
- **[CSV ↔ rules drift after manual JSON edits]** Migration is one-way (CSV → rules) and idempotent; it preserves non-CSV rules. Document that re-running after a CSV edit is the refresh path. A `--check` diff mode is a possible follow-up, not in scope.
- **[`external` indicators are in the rule set but unextractable]** Classified and `skipped` with a clear note — not an error. Callers see them in `skipped` and know they need a market-data source (future work).

## Migration Plan

1. Fix the 2 CSV escape rows (`report_type` = `现金流量表 — 经营活动` → correct `section_cn`/`report_type`).
2. Run `scripts/migrate_indicators_csv.py` to append 273 CSV-sourced rules + annotate the 44 overlapping rules with `report_type`/`indicator_cn` (Decision 3). Commit the regenerated `indicator_rules.json`.
3. Extend `indicators_client.py`: non-bank profiling (Decision 4), selector normalization (Decision 5), `external` `source_type` skip in the batch path.
4. Add the `extract_indicators_by_position` `@app.tool` in `server.py` and `scripts/extract_indicators_by_position.py` (Decision 6).
5. Regenerate `docs/indicators-methodology.md` + `docs/indicators-coverage.{md,csv}`.
6. Run `selfcheck.py`, `selfcheck_cache.py`, and the pytest suite (`.venv/bin/python -m pytest test_cnreport.py -v -p no:logfire` per the test-runner gotcha).

**Rollback:** `git revert` the `indicator_rules.json` change (back to 46 rules) + remove the new tool/CLI registrations. The CSV is input and remains untouched.

## Open Questions

- Should `extract_indicators_by_position` write a **separate** bundle cache keyed by CSV path, or reuse the existing `{stem}.indicators.json`? → **Decided:** reuse the existing bundle (keyed by applicable-rule-set hash); the CSV only selects the indicator subset, so the cache stays valid. Revisit if a CSV-path-keyed cache is needed for differential runs.
