## 1. Indicator rule set (data)

- [x] 1.1 Define the rule schema in `indicator_rules.json`: each entry has `name`, `aliases`, `module`, `subgroup`, `applies_to` (`industry`, `sub_types`, `companies`, `exclude_companies`), `source_type` (`akshare`|`report`|`computed`), and source spec (`{statement, field}` | `selectors[]` + `extractor` + `schema_hint` | `{formula, inputs}`), `unit`, `period_type`, `direction`, `note`.
- [x] 1.2 Seed `indicator_rules.json` from `indicators.md` covering every module + **every bank-specific indicator** (资本充足率 family, 净利差/净息差, 流动性覆盖率/流动性比例, 不良率/拨贷比/拨备覆盖率, 各类贷款迁徙率, 逾期/重组贷款率, 风险加权资产合计, 员工人数, 前十大股东, 分红, 区域收入). Mark standard line items `akshare`, narrative ones `report`, derived ones `computed`.
- [x] 1.3 For each `report` rule, curate the **concrete `selectors[]` chain** per the bank annual-report TOC (see design D4 table): default section selector + company-specific overrides for the 国有大行 + major 股份制 banks + a fallback section.
- [x] 1.4 Tag company-only indicators with `applies_to.companies: ["<ticker>"]` (and sub-type-scoped ones with `sub_types`) so non-applicable companies skip them.
- [x] 1.5 Sanity-load the JSON and eyeball module/subgroup coverage + selector chains against `indicators.md`.

## 2. indicators_client.py — rules load + name resolution

- [x] 2.1 Create `indicators_client.py`. Implement `load_rules()` returning `{modules: [...], rules: [...]}` (mirror `cninfo_client.load_categories`), loading `indicator_rules.json` from the module dir.
- [x] 2.2 Implement `rules_hash(rules)` → `sha1(json.dumps(rules, sort_keys=True))[:16]` for cache-busting.
- [x] 2.3 Implement `resolve_rule(name)`: exact `name` → `aliases` → normalized (strip whitespace/punctuation) substring over `name`+`aliases`. Return entry or `None`.
- [x] 2.4 Implement `list_rules(module=None, query=None, company=None)` returning grouped entries + `count`; when `company` is set, filter by `applicable_rules` and include the resolved `{industry, sub_type}`.

## 3. indicators_client.py — company profiling + applicability

- [x] 3.1 Implement `profile_company(stock_code, name="")` → `{industry, sub_type}`: curated ticker→sub-type lookup for the ~40 listed banks; name-keyword heuristic fallback (城市/城商 → 城商行, 农村/农商 → 农商行); default `{industry: "unknown", sub_type: None}`.
- [x] 3.2 Implement `applies_to(rule, profile, stock_code)` predicate per design D2 (industry AND sub_types AND exclude_companies AND companies).
- [x] 3.3 Implement `applicable_rules(stock_code, name="")` → filtered rule list + the profile. Used by lookup/batch/script.

## 4. indicators_extractors.py — pluggable extractors

- [x] 4.1 Create `indicators_extractors.py` with `EXTRACTORS = {}` registry and `register(name, fn)` / `get(name)`.
- [x] 4.2 Implement 2–3 starter Python extractors: `regex_amount` (numeric with unit extraction), `table_row` (locate a row label and read its period column), `percent_value` (strip %, normalize). Each is a pure `(section_text, rule, period) -> {value, unit, note}`.
- [x] 4.3 Register the starters at import time; document the `(section_text, rule, period) -> {value, unit, note}` contract in the module docstring (this is the "Adding a new extractor" extension point).

## 5. indicators_client.py — source routing + extraction

- [x] 5.1 Implement `_resolve_via_akshare(company, rule, year, period)` → `financials_client.get_statements`, select `source.statement` + `source.field` for the period row. Return uniform `{value, unit, source, source_type, extractor, period, provenance}` or `{value: null, note}`.
- [x] 5.2 Implement `_resolve_section(text, outline, rule, stock_code)` → walk `selectors[]` (company-filtered first) via `resolve_selector`; return `(section_text, matched_selector)` or `(None, tried_list)`.
- [x] 5.3 Implement `_run_extractor(section_text, rule, period, extractor_mode)` → dispatch `llm` (build per-section schema, call `ai_extract`/`call_llm_json`), `python:<name>` (dispatch via `indicators_extractors.get`), or `auto`. Honor `extractor_mode` override (`llm`/`python` forces; `python` mode skips `llm` rules → `unresolved`).
- [x] 5.4 Implement `_resolve_via_report(company, filing, rule, year, period, extractor_mode, cache_ctx)` → `report_cache.get_or_fetch` + `parse_outline` + `_resolve_section` + `_run_extractor`. Return uniform object with `pdf_url` provenance; missing section → `{value: null, note}` and `missing` entry.
- [x] 5.5 Implement `_resolve_via_computed(base_values, rule)` → look up each `source.inputs` in `base_values`, evaluate `formula` with the safe evaluator (`+ - * / ()`, numeric literals, name refs); missing/non-numeric → `{value: null, note: "missing input: <name>"}`.

## 6. indicators_client.py — single + batch entry points

- [x] 6.1 Implement `get_indicator(indicator, ticker_or_name, year, period="annual")`: resolve company, resolve rule, check applicability (skip with error if not applicable), route by `source_type`, return uniform result + header fields.
- [x] 6.2 Implement `extract_indicators(ticker_or_name, year, indicators=None, form="年度报告", extractor_mode="auto")`:
  - resolve company + top filing + one `report_cache.get_or_fetch`;
  - `applicable_rules` → requested subset (default = all applicable);
  - akshare group: one `get_statements`, pull all fields;
  - report group: sub-partition by resolved section, batch `llm` rules per section, dispatch `python:*` individually;
  - computed group: evaluate formulas after bases populate;
  - merge → `{indicator: {...}}` + `missing` + `unresolved` + `cached`.
- [x] 6.3 Implement `render_methodology()` → markdown per module/subgroup: `name`, `source_type`, `selectors[]` chain, `extractor`, `applies_to`, `unit`, `note`. Wire `python indicators_client.py --render-methodology > docs/indicators-methodology.md`.

## 7. Report cache — indicator bundle

- [x] 7.1 In `report_cache.py`, add `get_cached_indicators(stem, expected_rules_hash)` → bundle dict if present and hash matches, else `None`.
- [x] 7.2 Add `write_cached_indicators(stem, bundle)` → atomic write of `{stem}.indicators.json` (caller stamps `generated_at` and `rules_hash`).
- [x] 7.3 Extend `list_cache` size accounting to include `.indicators.json` in the per-entry size sum.
- [x] 7.4 Confirm `clear_cache` evicts `.indicators.json` (keys on stem); add `.indicators.json` + `.indicators.json.tmp` to the eviction extension list.

## 8. MCP tool registration

- [x] 8.1 In `cnreport_tools.py`, add `@_tool_safe` wrappers `list_indicators`, `get_indicator`, `extract_indicators` delegating to `indicators_client` (late-imported).
- [x] 8.2 In `server.py`, add `@app.tool` registrations with docstrings (Args/Returns): `list_indicators(module, query, company)`, `get_indicator(indicator, ticker_or_name, year, period)`, `extract_indicators(ticker_or_name, year, indicators, extractor_mode)`.
- [x] 8.3 Update `README.md`: add an "Indicators" layer to the tool table (3 rows) + a usage section showing `list_indicators(company=...) → get_indicator` and `extract_indicators`.

## 9. Standalone extraction script

- [x] 9.1 Create `scripts/extract_indicators.py` (argparse CLI): positional `ticker_or_name` (or `--from-file`), `--year`, `--rules`, `--extractor {auto|llm|python}`, `--indicators`, `--out-dir`, `--format`.
- [x] 9.2 Implement the run path: load rules (from `--rules` or default), for each company → `indicators_client.extract_indicators(..., extractor_mode=mode)` (reuse engine — no duplication), write `<stock>_<year>.json` + `.csv` to `--out-dir`.
- [x] 9.3 CSV writer: flat `indicator,value,unit,source_type,extractor,period,note` rows including `missing`/`unresolved` rows.
- [x] 9.4 Record provenance in JSON output: rule-file path, extractor mode, `cached` flag, `rules_hash`.

## 10. Methodology doc

- [x] 10.1 Create `docs/` and run `python indicators_client.py --render-methodology > docs/indicators-methodology.md` from the seed rule set.
- [x] 10.2 Add pinned **"Adding a new rule"** and **"Adding a new extractor"** sections (the extension contract) — append after the generated table or include in the renderer template.
- [x] 10.3 Add a one-line regen instruction to `README.md`.
- [x] 10.4 Verify the doc covers every rule in `indicator_rules.json` (count matches).

## 11. Tests & self-check

- [x] 11.1 Add a rule fixture `test_fixtures/indicator_rules.sample.json` (covering akshare / report-with-selector-chain / computed / company-only / sub-type-scoped rules) + tests for `load_rules` / `rules_hash` / `resolve_rule` / `profile_company` / `applies_to` / `applicable_rules`.
- [x] 11.2 Add extractor tests: register a test extractor, dispatch via `_run_extractor`, assert `python:` no-LLM path and unknown-name → `unresolved`.
- [x] 11.3 Add routing tests with mocks (no network/LLM): `_resolve_via_akshare` (mock `get_statements`), `_resolve_via_computed` (numeric + missing-input), `_resolve_via_report` (mock `get_or_fetch` + outline + `call_llm_json`), including the selector-chain fallback walk.
- [x] 11.4 Add `extract_indicators` grouping test: assert one `get_or_fetch` + one `call_llm_json` per distinct section (not per indicator), and that `python:*` rules bypass the LLM.
- [x] 11.5 Add bundle-cache round-trip test: write → read hit → mutate `rules_hash` → read miss → re-extract.
- [x] 11.6 Add script smoke test: invoke `scripts/extract_indicators.py` via `subprocess` with a mock/fixture rule file, assert JSON + CSV outputs exist and shapes match.
- [x] 11.7 Run `uv run --with pytest python -m pytest test_cnreport.py -v -p no:logfire` green; run `uv run python selfcheck.py` and `selfcheck_cache.py` green (offline).
