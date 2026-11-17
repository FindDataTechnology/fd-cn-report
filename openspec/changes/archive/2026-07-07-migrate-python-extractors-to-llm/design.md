## Context

The indicator rules engine has 289 `report`-type rules. 62 use `extractor: "llm"` and work correctly. 227 use `python:table_row`, `python:percent_value`, or `python:headcount` — these have a 22% hit rate and the hits are unreliable (wrong values, same total for all sub-categories).

The LLM batch path already exists: `extract_indicators` groups report rules by resolved section, then calls `_llm_extract_section` once per section×module. The Pydantic models in `indicators_models.py` are dynamically built from `indicator_rules.json` and already include all 289 report indicators as fields. Migrating the 227 python rules to `extractor: "llm"` means they automatically join the existing batch LLM calls — no new extraction code needed.

The real work is: (1) flip the `extractor` field in JSON, (2) fix broken section selectors so the LLM receives the right text, (3) remove the dead Python extractor code.

## Goals / Non-Goals

**Goals:**
- All 289 report-type indicators extracted via LLM with correct section text
- Section selectors for 资产负债表/利润表/现金流量表 resolve to the actual consolidated statement, not the MD&A analysis
- Dead `indicators_extractors.py` module removed
- Batch extraction path simplified (no python/llm split per section)

**Non-Goals:**
- Changing the LLM prompt or Pydantic model structure (already works for 62 rules)
- Changing the section cache (`llm_section_cache`) — same cache key strategy
- Optimizing LLM cost (that's a follow-up; this change focuses on correctness)
- Fixing the `report_section_map.json` for every possible company — only ICBC/Moutai sections are covered

## Decisions

### D1: Flip `extractor` in JSON, not in code
**Decision**: Change `extractor` from `python:*` to `"llm"` directly in `indicator_rules.json` for all 227 rules. Do NOT add a runtime mapping layer.
**Rationale**: The JSON is the single source of truth. A code-level remapping would hide the intent and complicate the rule file. A direct JSON edit is auditable and idempotent.
**Alternative considered**: Add a `_EXTRACTOR_OVERRIDE` map in code — rejected because it creates two sources of truth.

### D2: Fix three-statement selectors via `report_section_map.json`, not per-rule
**Decision**: Add `合并资产负债表`/`合并及公司资产负债表` as aliases for `资产负债表` in the section map, and make `_resolve_section` try statement-table aliases before the MD&A substring match.
**Rationale**: The root cause is that `resolve_selector("资产负债表")` matches `"7.2.2 资产负债表项目分析"` via substring before reaching the statement-fallback path. Adding aliases to the section map makes the correct candidates tried first.
**Alternative considered**: Change `_MODULE_TO_STATEMENT` fallback to run before the selector chain — rejected because it would break company-specific selectors that intentionally target the MD&A.

### D3: Remove `indicators_extractors.py` entirely
**Decision**: Delete the file and remove the `import indicators_extractors` + `python:` dispatch branch from `_run_extractor`.
**Rationale**: After migration, no rule uses `python:*`. Keeping the dead code adds maintenance burden and confuses readers.
**Alternative considered**: Keep the file as a "future extension point" — rejected because the registry pattern can always be re-added when needed.

### D4: Simplify `_extract_one_section` — no more python/llm split
**Decision**: Remove the `python_rules` branch from `_extract_one_section`. All report rules in a section go through `_llm_extract_section`.
**Rationale**: With no python extractors, the split is dead code. Removing it simplifies the batch path to: resolve section → one LLM call per module → map results.

### D5: Pass `form` to `_resolve_section` in the batch path
**Decision**: The batch extraction path in `extract_indicators` currently calls `_resolve_section` without `form`. Add `form=ctx.form` so section-map alias expansion is form-aware.
**Rationale**: Without `form`, the section map can't distinguish annual vs quarterly aliases.

## Risks / Trade-offs

- [LLM cost increases] → ~15-20 calls per report instead of ~10. Mitigated by `llm_section_cache` (repeat runs are free) and the fact that the 50 python "hits" were mostly wrong anyway.
- [LLM_API_KEY required for all report extraction] → Previously `extractor_mode="python"` could run without an API key. After migration, `python` mode becomes a no-op for report rules (all go to `unresolved`). This is acceptable — the python extractors never worked reliably.
- [Large Pydantic models] → The `balance_sheet` model will have ~80+ fields. Some LLM providers have token limits on structured output schemas. Mitigated by the existing `max_chars` truncation and the fact that the 62-rule model already works.
- [Section resolution still imperfect] → Some sections (`客户情况`, `供应商情况`) may not exist in certain reports. The LLM will return `null` for those, which is the correct behavior (the indicator isn't in the report).
