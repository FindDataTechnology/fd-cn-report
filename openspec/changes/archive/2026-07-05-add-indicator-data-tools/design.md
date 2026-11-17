## Context

`cnreport-mcp` already fetches A-share annual reports end-to-end: `cninfo_client` resolves a company and lists filings; `report_cache.get_or_fetch` downloads + caches the PDF and its extracted text/outline; `get_financial_statements` slices the three major statements as text from the TOC; `get_financials` returns akshare's structured line items; `ai_extract` runs LLM structured extraction over section text. Two data-driven files (`cninfo_categories.json`, the report-cache stem scheme) show the project's convention: **add behavior by editing JSON, not code**.

`indicators.md` is a ~200-item **banking-industry** catalog across four modules (资产负债表 / 利润表 / 现金流量表 / 财务指标). The gap: no way to ask "give me indicator X for company Y in year Z" in one call, and no batch path. Three complications drive the design:

1. **Section location is company-specific.** The same indicator lives under different TOC titles at different banks — 资本充足率 may be a standalone section, a "风险管理" subsection, or inside "管理层讨论与分析". A single hardcoded selector fails across banks.
2. **Applicability is company-specific.** Some indicators only appear for certain banks (逾期90天重组贷款率, 境内/境外区域收入, certain 贷款迁徙率 breakdowns, 拨贷比 vs simpler ratios). Processing every company against every indicator wastes LLM calls and yields noise.
3. **The user owns the rule layer.** They will keep adding rules and processing logic, so the rule format and the extractor plugin interface are the stable extension points — not something to hard-code.

Stakeholders: analysts querying the MCP server interactively; downstream agents wanting a whole indicator set per company/year; and the user, who will add rules/extractors over time and run different companies through different rule files via a script.

## Goals / Non-Goals

**Goals:**
- One-call single-indicator lookup and one-call batch extraction, both rule-driven.
- A **rule per indicator** that names the concrete report section(s) it lives in, with a per-company selector override chain.
- **Company-specific separation**: tag each rule with applicability (industry / sub-type / explicit company list) so different companies run different rule subsets. Company-only indicators are skipped for everyone else.
- **Pluggable extractors**: each rule picks `"llm"` (existing `ai_extract` path) or `"python:<name>"` (deterministic parser). Adding a Python extractor = add a function + register.
- A **standalone extraction script** that runs the pipeline for a company (or list) with a selectable rule file and extractor mode, outputting JSON + CSV.
- A methodology doc covering section mapping, extractor per indicator, applicability, and how to add rules/extractors.
- Reuse the existing report cache and LLM path — no new network/PDF/LLM plumbing.

**Non-Goals:**
- Real-time/intra-period snapshots beyond what akshare returns (annual-report-bound).
- Non-bank industries in the seed rule set (format is industry-agnostic; a second rule file can be added later).
- Cross-company ranking, aggregation, or screening.
- Auto-discovering section titles without a curated selector chain (the user curates selectors; the engine tries the chain in order).
- Re-fetching / re-extracting when the same company/year is asked again — bundle cache makes repeat calls free.

## Decisions

### D1. Rules engine, not a flat registry
`indicator_rules.json` (sibling of `cninfo_categories.json`) is the source of truth. One entry per indicator **rule**:

```json
{
  "name": "资本充足率",
  "aliases": ["资本充足率"],
  "module": "balance_sheet",
  "subgroup": "核心指标",
  "applies_to": {"industry": "bank", "sub_types": ["国有大行","股份制","城商行","农商行"], "companies": ["*"], "exclude_companies": []},
  "source_type": "report",
  "selectors": [
    {"company": ["601398","601939"], "section": "三、资本充足率分析"},
    {"section": "资本充足率"},
    {"section": "风险管理", "fallback": true}
  ],
  "extractor": "llm",
  "schema_hint": {"indicator": "资本充足率", "period": "本年", "unit": "%"},
  "post_process": null,
  "unit": "%",
  "period_type": "annual",
  "direction": "higher_is_better",
  "note": "Bank-specific; not in akshare standard statements."
}
```

`source_type` is `akshare` | `report` | `computed`. `selectors[]` is an **ordered chain**: the first entry whose `company` filter matches the target company (or has no `company` filter) is tried first; if its section isn't in the TOC, the next is tried. This is how company-specific section differences are expressed without code. `load_rules()` / `resolve_rule(name)` mirror `cninfo_client.load_categories()` / `resolve_category()`.

**Alt considered**: a flat registry with a single `section` field (original proposal). Rejected — it cannot express "工商银行 puts this under 三、资本充足率分析, 建设银行 under 资本充足率, others under 风险管理", which is exactly the user's "different company, different process rules" concern.

### D2. Company profiling + applicability filtering
`profile_company(stock_code, name)` → `{industry, sub_type}`. Bank sub-type is resolved by a small lookup (the ~40 国有大行/股份制 tickers) with a fallback heuristic (城商行/农商行 by name keywords 城市/农村/农商). Each rule's `applies_to` is evaluated: a rule applies to company C iff `industry` matches AND (`sub_types` is empty/`["*"]` OR C's sub_type is listed) AND C is not in `exclude_companies` AND (`companies` is `["*"]`/empty OR C is listed). `applicable_rules(company)` returns the filtered list. `get_indicator`/`extract_indicators`/the script all call this, so **different companies get different rule subsets by construction**. Company-only indicators (e.g. a ratio one bank discloses uniquely) use `companies: ["601398"]` and are skipped elsewhere.

**Alt considered**: separate JSON file per company. Rejected — explodes the file count and breaks cross-company comparison; `applies_to` + selector chains in one file is simpler and diff-friendly.

### D3. Pluggable extractors — `llm` or `python:<name>`
Each rule declares `extractor`. `indicators_extractors.py` holds a registry `EXTRACTORS = {"regex_amount": fn, "table_row": fn, ...}` plus a `register(name, fn)` so the user adds extractors without touching the engine.
- `"llm"` → reuse `ai_extract`: feed the section text + a per-section schema requesting `{records: [{indicator, value, period, unit}]}` for all rules mapped to that section. One LLM call per section, not per indicator.
- `"python:<name>"` → dispatch to the named function `(section_text, rule, period) -> {value, unit, note}`. Used for deterministically-located numbers (e.g. a ratio always in a fixed table cell, or a line item extractable by regex). No LLM cost, no hallucination.
- `computed` rules don't use an extractor; their formula is evaluated locally over already-resolved base values (D6).

`extractor: "auto"` (default) lets the engine pick: `computed` → compute; `akshare` → akshare fetch; `report` → `llm` unless a `python:` extractor is named. The user can force `--extractor python` in the script to skip LLM entirely where possible.

**Alt considered**: LLM-only. Rejected — unreliable for arithmetic and wasteful for items a 3-line regex extracts reliably; the user explicitly asked for "python code or llm" per indicator.

### D4. Concrete section mapping is curated, with override chains
The seed rule set maps every bank-specific indicator to its actual annual-report TOC section. Standard structure used as the default selector (banks vary, so overrides are the norm for risk/loan indicators):

| Indicator group | Default section selector | Override example |
|---|---|---|
| 标准报表行项目 (资产总计, 营业收入, 净利润…) | `合并资产负债表` / `合并利润表` / `合并现金流量表` | (akshare preferred) |
| 资本充足率类 | `资本充足率` → fallback `风险管理` | 工行: `三、资本充足率分析` |
| 贷款质量/迁徙率/不良/拨贷比 | `贷款质量` → fallback `信用风险` → `风险管理` | 建行: `五、贷款质量` |
| 净息差/净利差/ROE/ROA/人均 | `主要财务指标` → fallback `管理层讨论与分析` | — |
| 员工人数/学历构成 | `员工情况` | — |
| 前十大股东/股本结构 | `股份变动及股东情况` | — |
| 分红/融资 | `利润分配` → fallback `重要事项` | — |
| 境内/境外区域收入 | `分地区/分行业` → fallback `营业收入构成` | company-only |

The engine resolves via `resolve_selector` (exact → regex) on the parsed outline, walking `selectors[]` until one hits. Misses surface as `missing` (not errors). This table is regenerated into the methodology doc.

### D5. Batch = one fetch, group-by-section, then compute
`extract_indicators(ticker_or_name, year, indicators=None)`:
1. Resolve company + filing PDF (one `report_cache.get_or_fetch`).
2. `applicable_rules(company)` → requested subset (default = all applicable).
3. **akshare group**: one `get_statements` call; pull every requested field.
4. **report group**: sub-partition by resolved section. For each distinct section, fetch text once (cache-backed) and run the rules' extractors — `llm` rules in one batched `ai_extract` call per section, `python:*` rules dispatched individually.
5. **computed group**: after steps 3–4 populate bases, evaluate formulas locally; missing inputs → `unresolved`.
6. Merge into `{indicator: {value, unit, source, source_type, extractor, period, provenance}}` + `missing` + `unresolved`.

**Alt considered**: parallel per-indicator agents. Rejected — they'd re-read cached text and re-call the LLM; grouping by section strictly dominates for latency/tokens and stays deterministic.

### D6. Computed ratios evaluated locally
`computed` rules carry `formula` (e.g. `不良贷款余额 / 贷款和垫款总额 * 100`) and `inputs` (other indicator names). After akshare + report passes fill bases, evaluate with a tiny safe evaluator (operators `+ - * / ()`, numeric literals, indicator-name refs). Non-numeric/missing input → `{value: null, note: "missing input: <name>"}`, listed in `unresolved`. No LLM does arithmetic.

### D7. Cache the extracted indicator bundle on disk
Extend the report-cache stem with `{stem}.indicators.json` (alongside `.pdf`/`.txt`/`.outline.json`) holding the full extracted map for that stock/year, keyed by the **applicable rule set** so a different company's bundle isn't reused. Store `rules_hash` (sha1 of the applied rule subset) in the bundle; mismatch → miss. `extract_indicators` reads on hit — **no re-LLM on repeat**. `clear_cache` already keys on stem, so eviction is free.

### D8. Standalone extraction script `scripts/extract_indicators.py`
CLI entry point so the user can batch-process companies with different rule sets without the MCP server:
```
python scripts/extract_indicators.py <ticker_or_name> --year 2023 \
    [--rules indicator_rules.json] [--extractor auto|llm|python] \
    [--indicators 资本充足率,不良率] [--out-dir ./out] [--format json,csv]
```
- Accepts one ticker/name, or `--from-file companies.txt` for a list.
- `--rules` selects the rule file → "process different company in different process rules" by pointing at a different file per company batch.
- `--extractor` forces a mode (e.g. `python` to run LLM-free where possible).
- Fetches each company's PDF once, applies `applicable_rules`, runs extractors, writes `out/<stock>_<year>.json` + `.csv`.
- Reuses `indicators_client` + `report_cache` + `indicators_extractors` — no logic duplication with the MCP tools.

### D9. Name resolution & error contract (unchanged from prior design)
`resolve_rule(name)`: exact → `aliases` → normalized substring. All helpers go through `@_tool_safe` (errors → `{"error": ...}`, never raise). Return shapes carry `stock_code`, `company_name`, `year`, `pdf_url`, `cached`, and per-value `extractor` + `source_type`.

### D10. Methodology doc generated from the rule set
`docs/indicators-methodology.md` is regenerated from `indicator_rules.json` by `indicators_client.render_methodology()` (or `python indicators_client.py --render-methodology > ...`). Per indicator it lists: `source_type`, the concrete `selectors[]` chain, `extractor`, `applies_to`, `unit`, `note`. Two pinned sections — **"Adding a new rule"** and **"Adding a new extractor"** — document the extension contract for the user.

## Risks / Trade-offs

- **[LLM numeric hallucination on bank tables]** → Prefer `akshare` and `computed` paths; for `report`-path indicators prefer `python:*` extractors where the location is stable, else `llm` with tight per-section schemas + `validate_against_schema` + the one-shot retry in `ai_extract`; surface `extractor` so callers know which values are LLM-derived.
- **[Section selectors go stale as banks restructure their TOC]** → The `selectors[]` chain + fallback + `missing` list make a single stale selector non-fatal; the methodology doc records the curated selectors for manual repair. The user can add a company-specific override without a code change.
- **[Company sub-type mis-classification]** → A wrong sub-type would wrongly include/exclude rules. Mitigation: a curated ticker→sub-type lookup for the ~40 listed banks, name-keyword heuristic fallback, and `list_indicators(company=...)` to preview which rules apply before extraction.
- **[Rule set is large (~200 indicators, company-overriden)]** → Ship a curated seed covering every module/subgroup + all bank-specific indicators named in `indicators.md`, with selector overrides for the major banks. Gaps surface as `missing`, not failures. The script's `--indicators` flag lets the user run a subset while the rule set grows.
- **[Bank-only rules on non-bank tickers]** → `applicable_rules` returns the (small) intersection; non-applicable indicators are excluded, not errored. The README states the seed rule set is banking-focused.
- **[Python extractor bugs / drift]** → Each `python:*` extractor is a pure function with its own unit test against a fixture section text; registered in one place (`indicators_extractors.EXTRACTORS`) so they're discoverable.
- **[Bundle cache staleness after a rule edit]** → D7 stores `rules_hash` in the bundle and treats mismatch as a miss; `--rules` pointing at a different file produces a different hash → automatic bust. `clear_cache(stock_code, year)` is the manual override.

## Migration Plan

Additive only — no existing tool changes contract. Rollout:
1. Land `indicator_rules.json` (seed, with selector overrides for major banks) + `indicators_client.py` (load/resolve/profile/filter/route/compute/render) + `indicators_extractors.py` (registry + 2–3 starter extractors).
2. Wire `list_indicators`, `get_indicator`, `extract_indicators` into `cnreport_tools.py` (`@_tool_safe`) and `server.py` (`@app.tool`).
3. Add `.indicators.json` handling to `report_cache` (write/read/bust-by-rules-hash); extend `list_cache` size accounting.
4. Add `scripts/extract_indicators.py` (CLI) reusing `indicators_client`.
5. Generate `docs/indicators-methodology.md`; add the new "Indicators" layer + script usage to `README.md`.
6. Add offline tests (rule fixture, applicability filter, extractor dispatch, computation, bundle round-trip, script smoke) to `test_cnreport.py`; run `selfcheck`-style smoke against a cached bank PDF without network.

**Rollback**: delete the three `@app.tool` registrations, the script, and the new files; the report cache gains a `.indicators.json` it would ignore. No schema migration, no data loss; `.indicators.json` files are disposable (regenerable).

## Open Questions

- **Seed scope** — curated seed covering every module/subgroup + every bank-specific indicator in `indicators.md`, with selector overrides for the 国有大行 + major 股份制 banks. Rest added by JSON edit. (Default; confirm at apply.)
- **Sub-type taxonomy** — default to {国有大行, 股份制, 城商行, 农商行} for banks. Acceptable, or finer? (Default chosen: 4 buckets.)
- **Doc location** — `docs/indicators-methodology.md` (new `docs/` dir). (Default chosen.)
