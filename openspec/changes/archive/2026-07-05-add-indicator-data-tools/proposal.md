## Why

`indicators.md` defines a ~200-item banking-industry financial indicator catalog, but the server cannot answer "what is indicator X for company Y in period Z" in one call, and has no batch path. The decisive complication: **different banks expose the same indicator in different annual-report sections** (资本充足率 lives under "风险管理" at some banks, under a standalone "资本充足率" section at others), and **some indicators only appear for certain companies/bank types** (逾期90天重组贷款率, 境内/境外区域收入, specific 贷款迁徙率 breakdowns). A flat registry cannot express this. We need a **rule per indicator** that names the concrete report section(s), declares which companies it applies to, and picks an extractor (deterministic Python **or** LLM). The rule layer must be the extension point — the user will keep adding rules and processing logic — and there must be a standalone script so different companies can be run through different rule sets in batch.

## What Changes

- Replace the flat registry concept with an **indicator rules engine** (`indicator_rules.json`). Each rule maps one indicator to: applicable company profile, a **section selector chain** (company-specific override → default → fallback), an **extractor type** (`"llm"` or `"python:<name>"`), a post-process, unit, and period semantics. Adding a rule = editing JSON.
- Add **company profiling + applicability filtering**: `profile_company(stock_code)` → `{industry, sub_type}` (bank sub-type: 国有大行 / 股份制 / 城商行 / 农商行). Each rule carries `applies_to: {industry, sub_types, companies, exclude_companies}`. `get_indicator` / `extract_indicators` filter rules per company, so **different companies run different rule subsets** — the core "process different company in different process rules" requirement. Company-specific indicators (only shown by special companies) are tagged `companies: [...]` and skipped for everyone else.
- Add **pluggable extractors**: `"llm"` routes through the existing `ai_extract` path; `"python:<name>"` dispatches to a registered deterministic parser (regex/table). Adding a new Python extractor = add a function + register it. The rule decides per-indicator which to use.
- Add a **standalone extraction script** `scripts/extract_indicators.py` — a CLI that runs the full pipeline for one company/year (or a list) with a selectable rule set, fetches the PDF once, applies the company's applicable rules, and writes JSON + CSV. Supports `--extractor llm|python|auto` and `--rules <file>` overrides so the user can process different companies with different rule files.
- Add tools `get_indicator`, `extract_indicators`, `list_indicators` (rule-driven, company-filtered) wired into `cnreport_tools.py` / `server.py`.
- Add **`docs/indicators-methodology.md`** documenting, per indicator: the concrete report section(s), extractor type, applicability (which companies), unit, and process note — plus a "How to add a new rule" and "How to add a new extractor" section. Generated from `indicator_rules.json`; `indicators.md` stays as the human catalog.

## Capabilities

### New Capabilities
- `indicator-rules`: The rules engine — rule structure (indicator → applicability + section selector chain + extractor + post-process), company profiling, applicability filtering, pluggable extractor dispatch (llm | python), and the data-driven + code-plugin extensibility contract (add rules by JSON, add extractors by Python).
- `indicator-lookup`: Resolve one named indicator to a value for a company + period by selecting the applicable rule, fetching the section, and running the rule's extractor. Returns `{value, unit, source, extractor, period, provenance}`.
- `indicator-batch-extract`: Extract all (applicable) indicators for one company/year in one pass — one PDF fetch, group applicable rules by section, one LLM call per section, deterministic Python extractors run locally, derived ratios computed. Caches the bundle to disk.
- `indicator-extraction-script`: Standalone `scripts/extract_indicators.py` CLI — run the pipeline for a company or list, with selectable rule file and extractor mode, output JSON + CSV. The batch-processing entry point for "different company, different process rules."
- `indicator-catalog`: Browse/search the rule set (by module, company applicability, extractor type) so callers know valid indicator names and which rules apply to a given company before retrieval.

### Modified Capabilities
<!-- None. No existing spec files under openspec/specs/. The new tools/script are additive and do not change the contract of get_financials / get_financial_statements / ai_extract. -->

## Impact

- **New files**: `indicators_client.py` (rules load/resolve, company profiling, applicability filter, extractor dispatch, ratio compute, methodology render), `indicator_rules.json` (data), `indicators_extractors.py` (Python extractor plugins + registry), `scripts/extract_indicators.py` (CLI), `docs/indicators-methodology.md`.
- **Modified files**: `cnreport_tools.py` (3 `@_tool_safe` helpers), `server.py` (3 `@app.tool`), `report_cache.py` (`.indicators.json` bundle + size accounting), `README.md` (new "Indicators" layer + script usage).
- **Reused**: `report_cache.get_or_fetch`, `parse_outline` / `resolve_selector` / `extract_section_text`, `ai_extract`'s `call_llm_json` + schema validation, `cninfo_client.lookup_company` / `query_announcements`, `financials_client.get_statements`.
- **New dependencies**: none. LLM and ES env reused as-is.
- **Tests**: extend `test_cnreport.py` with rule-fixture, applicability-filter, extractor-dispatch, and script-smoke tests (offline, mocked LLM/PDF).
- **Non-goals**: real-time/quarterly snapshots beyond akshare; non-bank industries in the seed rule set (format is industry-agnostic; a second rule file can be added later); cross-company ranking/aggregation; auto-discovering section titles without a curated selector (the user curates selectors; the engine tries the chain).
