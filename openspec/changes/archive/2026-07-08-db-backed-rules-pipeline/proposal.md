## Why

Indicator rules today live in a 285 KB hand-edited JSON file (`indicator_rules.json`) loaded from a hardcoded path ([`indicators_client.py:36`](file:///Users/chengsishi/finddata/cnreport/indicators_client.py), [`indicators_models.py:26`](file:///Users/chengsishi/finddata/cnreport/indicators_models.py)). Script-rule extraction was removed entirely (`indicators_extractors.py` deleted; `_effective_extractor()` now always returns `"llm"`), so every report indicator goes through the LLM even when a deterministic script would do. There is also no way to generate rules from a document — every rule is hand-authored. This change persists rules in the project's existing SQLite store (`daas.db`, env-configurable), re-introduces DB-backed script-rule extraction, and adds 5 project-scoped skills that auto-generate LLM rules and script rules from PDFs.

## What Changes

- **Persist indicator rules in SQLite.** Add `llm_rules` and `script_rules` tables to the existing `daas.db` (SQLAlchemy, via `DAAS_DATABASE_URL`, default `sqlite:///daas.db`). LLM rules carry `{indicator, instruction, position, document_type}`; script rules carry `{indicator, extract_rule, position, document_type}`, plus the shared metadata the pipeline already needs (`module`, `applies_to`, `unit`, `period_type`, `value_range`).
- **Migrate `indicator_rules.json` → DB.** A one-shot migration script seeds the `llm_rules` table from the 321 existing rules (mapping `name`→`indicator`, `note`/`aliases`/`source`→`instruction`, `source.selectors`→`position`, `report_type`→`document_type`). The JSON is retained as a migration seed only — it is no longer the runtime source of truth. **BREAKING** for any caller that reads `indicator_rules.json` directly or uses the `--rules` / `set_registry_path()` override.
- **Rules loaded from DB at runtime.** `indicators_client.load_rules()` and `indicators_models._build_registry()` read from the rules database instead of the JSON file; the Pydantic model registry is rebuilt from DB rows. `set_registry_path()` is replaced by a DB-backed registry refresh.
- **Script-rule extraction engine.** Re-introduce a named-extractor registry (the deleted `indicators_extractors.py` pattern) whose extractors are resolved from DB `script_rules.extract_rule`. `extract_indicators()` dispatches script rules through this registry alongside the existing `llm` / `computed` / `akshare` paths, returning the same result bundle shape.
- **5 project-scoped generator skills** (under `.claude/skills/`), each a Python script using pydantic for structured output, persisting to the rules database and the skill's own `scripts/` directory:
  1. `fd-cnreport-llm-rules-creator` — generate LLM rules from a section / piece of a document.
  2. `fd-cnreport-pdf-llm-rules-creator` — split a whole PDF by outline into chapters, generate LLM rules per chapter.
  3. `fd-cnreport-pdf-scripts-creator` — read a single rule/document's rules from DB, generate script rules.
  4. `fd-cnreport-pdf-scripts-by-type-creator` — read all rules for a `document_type` from DB, generate script rules per target indicator.
  5. `fd-cnreport-pdf-full-scripts-creator` — generate a full end-to-end extraction script per `document_type`.

## Capabilities

### New Capabilities
- `rules-database`: SQLite-backed store for LLM rules and script rules — env-configurable path (extends the existing `DAAS_DATABASE_URL` / default `daas.db`), one-shot migration from `indicator_rules.json`, and the read/write API used by the extraction pipeline and the generator skills.
- `script-indicator-extract`: Execution of script rules — dispatch rules whose `extractor` resolves to a named script via a DB-backed extractor registry, returning the same result shape as LLM extraction.
- `rules-generator-skills`: 5 project-scoped skills that generate LLM rules and script rules from documents/PDFs, validate output with pydantic, and persist results to the rules database and each skill's `scripts/` directory.

### Modified Capabilities
- `indicator-rules`: Rules are loaded from the rules database at runtime instead of `indicator_rules.json`; the JSON file becomes a migration seed. Rule structure and applicability logic are otherwise unchanged.
- `indicator-catalog`: `list_indicators` reads rules from the rules database instead of loading `indicator_rules.json` at tool-call time.
- `indicator-lookup`: `get_indicator` dispatches script-rule extractors (sourced from DB) in addition to `llm` / `computed` / `akshare`.

## Impact

- **New code**: a rules-database module (tables + CRUD), a migration script (`scripts/migrate_rules_to_db.py`), a script-extractor registry module, and 5 skill directories under `.claude/skills/` (each with `SKILL.md` + a pydantic-validated Python generator script in its `scripts/` dir).
- **Existing code**: `indicators_client.py` (load_rules, registry-path handling, extractor dispatch), `indicators_models.py` (registry built from DB rows), `cnreport_database.py` / `cnreport_models.py` (new tables), and `cnreport_tools.py` (if rule-loading helpers relocate).
- **Dependencies**: no new runtime deps — SQLAlchemy, pydantic, and python-dotenv are already declared. Skills reuse the existing LLM client (`cnreport_tools.call_llm_pydantic`).
- **Env**: reuses `DAAS_DATABASE_URL` (default `sqlite:///daas.db`); no new env vars required.
- **Tests**: existing tests that point `DAAS_DATABASE_URL` at a temp SQLite file keep working; the JSON-path override (`--rules` / `set_registry_path()`) is replaced by DB seeding in fixtures.
