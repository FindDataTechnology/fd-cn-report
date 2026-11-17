## Context

The current extraction pipeline uses 6 extractor types across 321 rules. The dominant path (`python:table_row`, 186 rules) applies fragile regex patterns to raw section text — it cannot reliably distinguish row labels from values in Chinese financial table text. The LLM path (62 rules) sends freeform JSON prompts with `response_format: json_object` but no schema — the LLM may omit fields, return wrong types, or hallucinate values silently. Both paths produce loosely-typed `{value, note}` dicts, requiring callers to handle None checks and parse errors.

The report structure is known: balance sheet, income statement, and cash flow each have a fixed set of ~40 line items. MD&A and risk sections have semi-structured tables. This makes the problem tractable with per-section Pydantic models.

## Goals / Non-Goals

**Goals:**
- Replace all `python:table_row`, `python:percent_value`, `python:headcount` extractors with LLM extraction validated by Pydantic schemas.
- Define Pydantic models per report section (balance_sheet, income_statement, cashflow, report_section) that list exactly which indicators to extract.
- Rewrite `call_llm_json` → `call_llm_pydantic` using OpenAI's structured output (`json_schema` in `response_format`), validated by Pydantic at runtime.
- Provide a high-level `extract_to_dataframe(ticker, years)` that auto-downloads reports, resolves sections, runs parallel LLM extraction, and returns a pandas DataFrame.
- Maintain backward compatibility for akshare and computed rules (unchanged code path).
- Design rule administration so adding/removing an indicator is a one-line Pydantic model change.

**Non-Goals:**
- Real-time market data extraction (akshare/external rules stay unchanged).
- Web dashboard rewrite (existing dashboard continues to work with the new DataFrame output).
- Multi-language support (Chinese-only reports).
- Generic PDF table parsing (only section-within-report extraction).

## Decisions

### D1: Pydantic model per section module (not per indicator)

Each section module (balance_sheet, income_statement, cashflow, report_section) gets one Pydantic model listing all supported indicators as `Optional[Decimal]` or `Optional[str]` fields. A `BaseExtractionResult` base model provides metadata (`section`, `page`, `source`).

**Rationale** over per-indicator models: A single model per section means one LLM call extracts all indicators in that section at once, matching the current grouping strategy. Per-indicator models would require N calls. The field set is stable (balance sheet has ~40 line items — adding one means adding a field).

```python
class BalanceSheetResult(BaseExtractionResult):
    资产总计: Optional[Decimal] = None
    负债合计: Optional[Decimal] = None
    发放贷款和垫款: Optional[Decimal] = None
    吸收存款: Optional[Decimal] = None
    客户存款: Optional[Decimal] = None
    存放中央银行款项: Optional[Decimal] = None
    # ... all balance sheet indicators
```

**Alternative considered:** JSON Schema generated from `indicator_rules.json` per section. Rejected — loses type safety, IDE autocomplete, and refactoring support.

### D2: LLM structured output via OpenAI `json_schema` response format

Replace `response_format: {"type": "json_object"}` with `response_format: {"type": "json_schema", "json_schema": {"name": "...", "schema": pydantic_model_to_json_schema(...)}}`. The LLM is constrained to produce valid JSON matching the schema. The response is then parsed through the Pydantic model.

**Rationale:** The `json_object` format guarantees JSON but not structure — the LLM can invent fields, skip required ones, or nest incorrectly. `json_schema` enforces the exact field set at the API level, making Pydantic validation a safety net rather than the primary guard.

**API support:** The 火山引擎 DeepSeek API (OpenAI-compatible) supports `response_format.json_schema` (confirmed via test). Fallback: if the provider doesn't support `json_schema`, fall back to `json_object` + Pydantic manual parse with retry on failure.

### D3: `json_schema` field name = indicator rule name, case- and punctuation-tolerant

The generated JSON Schema uses camelCase field names like `totalAssets`, `totalLiabilities`. On the LLM side, DeepSeek responds in these names. The Pydantic model uses `Field(alias=...)` to map to/from the original Chinese indicator names.

```python
发放贷款和垫支: Optional[Decimal] = Field(None, alias="loanAndAdvances")
```

**Rationale:** LLMs handle ASCII field names much more reliably than multi-byte Chinese keys in JSON Schema constraints (some providers mangle Unicode in schema definitions).

### D4: `indicator_rules.json` drops `extractor` for report-type rules

After migrating, all report-type rules use `llm` extraction. The `extractor` field becomes redundant and is removed. The section module (`balance_sheet`, `income_statement`, etc.) determines which Pydantic model to use.

**Migration:** A script reads the old rules JSON, drops `extractor` field from report-type rules, and writes the simplified version. The `python:table_row`, `python:percent_value`, `python:headcount` extractors are deleted from `indicators_extractors.py`.

```json
{
  "rules": [
    {
      "name": "发放贷款和垫款",
      "module": "balance_sheet",
      "applies_to": { "industry": ["bank"] },
      "source_type": "report",
      "selectors": [{"section": "合并资产负债表"}, {"section": "资产负债表", "fallback": true}]
    }
  ]
}
```

### D5: `extract_to_dataframe` as the new top-level entry point

```python
def extract_to_dataframe(
    tickers: str | list[str],
    years: int | list[int],
    rules: Optional[list[str]] = None,
    concurrency: int = 4,
) -> pd.DataFrame:
```

Downloads reports in parallel (one per ticker-year), resolves sections with enriched outline, dispatches Pydantic-typed LLM extraction across sections concurrently, and flattens results into a DataFrame with columns:
`ticker | year | indicator | value | unit | source_section | period`.

**Rationale:** Users want to query "give me 不良贷款余额 for all these banks in 2023-2025". The current dict-of-dicts output requires manual flattening. A DataFrame is the natural interchange format for analysis.

### D6: Rule administration via `extract_rules list/add/rm/edit` CLI

A new `extract_rules` CLI command (installed via `pyproject.toml` `[project.scripts]`) wraps rule CRUD:
- `extract_rules list [--module balance_sheet]` — list rules
- `extract_rules add <name> --module balance_sheet --selectors "..."` — add rule
- `extract_rules rm <name>` — remove rule
- `extract_rules edit <name> --field value` — modify rule
- `extract_rules json-schema --module balance_sheet` — preview the Pydantic → JSON Schema

### D7: Parallel section extraction with per-section lock

Current code already groups rules by section and makes one LLM call per section. The new design keeps this structure: each Pydantic model maps to one section, one LLM call extracts all fields in that model. Sections are independent (balance sheet, income statement, cash flow, report_section sub-sections) and can run in parallel.

A per-section result cache (SQLite-backed, keyed by `ticker-year-section-rules_hash`) prevents re-extracting the same section across runs.

## Risks / Trade-offs

- **LLM cost increase**: Single LLM call per section replaces cheap regex extractors. Mitigation: each call extracts ~40 indicators in one shot (cost per indicator is lower than per-indicator LLM calls). For DeepSeek-Flash, estimated ~$0.03/call × ~6 sections = ~$0.18/report.
- **LLM hallucination on balance sheet values**: A Pydantic-validated `Decimal` won't catch a wrong number. Mitigation: cross-validate against akshare when available (reports map to known statement items); add `min`, `max` per field via Pydantic `Field(ge=0, le=1e15)` to reject absurd values.
- **Latency**: One LLM call per section per ticker-year. For 10 banks × 3 years × 6 sections = 180 calls. Mitigation: concurrent dispatch with configurable `concurrency` cap; LLM response time ~3-8s per call.
- **JSON Schema support gap**: Some OpenAI-compatible providers reject `json_schema` response format. Fallback: detect at startup and fall back to `json_object` + Pydantic parse with retry (max 2 retries on parse failure).
- **Model update coupling**: Adding an indicator field to a Pydantic model requires re-extracting all cached sections. Mitigation: cache key includes a model version hash; bumping the model version busts the cache.

## Open Questions

- Which Pydantic model field naming convention for the LLM JSON Schema keys? Preferred: camelCase ASCII (e.g., `totalAssets`). Needs testing against 火山引擎 DeepSeek-Flash to confirm no Unicode mangling.
- Should non-section report modules (financial_ratio) also get a Pydantic model, or stay computed? Decision: they become computed — they're already formula-based and don't need LLM.
- What's the rollback plan if the LLM extraction quality is measurably worse than current regex approach? Maintain a branch/release tag of the old code; run A/B comparison on the same 10-bank-3-year corpus.
