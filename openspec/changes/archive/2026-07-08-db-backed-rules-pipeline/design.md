## Context

Indicator rules currently live in a 285 KB JSON file (`indicator_rules.json`, 321 rules) loaded from a hardcoded path in [`indicators_client.py:36`](file:///Users/chengsishi/finddata/cnreport/indicators_client.py) and [`indicators_models.py:26`](file:///Users/chengsishi/finddata/cnreport/indicators_models.py). The project already runs a SQLite database — [`cnreport_database.py`](file:///Users/chengsishi/finddata/cnreport/cnreport_database.py) uses SQLAlchemy 2.x with `sqlite:///daas.db` (default), overridable via `DAAS_DATABASE_URL` from `.env` (loaded by `python-dotenv` in `server.py`). The DB currently holds `report_documents`, `report_sections`, and `es_index_meta`.

Script-rule extraction was removed in a prior change: `indicators_extractors.py` (a `register()`/`get()` extractor registry with `regex_amount`, `percent_value`, `table_row`, `headcount`) was deleted, and `_effective_extractor()` now always returns `"llm"`. The demand asks to (1) move rules into this existing SQLite store, (2) re-introduce script-rule execution from DB-stored rules, and (3) add 5 project-scoped skills that auto-generate LLM rules and script rules from PDFs.

## Goals / Non-Goals

**Goals:**
- Rules persist in `daas.db`; the DB path is env-configurable (reuse `DAAS_DATABASE_URL`, default `sqlite:///daas.db`).
- A one-shot, idempotent migration seeds the DB from `indicator_rules.json`; the JSON becomes a migration seed, not the runtime source of truth.
- The extraction pipeline reads rules from the DB with no change to the rule dict shape it already consumes, so `indicators_client` / `indicators_models` logic is preserved.
- Script rules (`extract_rule` → named extractor) execute through a DB-backed registry, returning the same result shape as LLM extraction.
- 5 generator skills produce validated (pydantic) LLM rules and script rules, persisting to the DB and each skill's `scripts/` dir.

**Non-Goals:**
- A web UI for editing rules (the existing `scripts/rules_dashboard.py` is out of scope).
- Changing the LLM extraction contract (one call per section, `{records:[...]}` schema) — it stays as-is, only its rule source changes.
- Re-implementing the CSV→JSON migration (`scripts/migrate_indicators_csv.py`) to target the DB directly in this change; CSV→JSON continues to feed `indicator_rules.json`, which the new migration then loads into the DB. (Direct CSV→DB is a follow-up.)
- Auto-running the generator skills on a schedule; they are invoked manually via skill-creator.

## Decisions

### D1: Reuse the existing `daas.db` / `DAAS_DATABASE_URL`, not a new rules DB
The project already has a SQLAlchemy engine + session singleton in `cnreport_database.py` (`get_db()`, `check_same_thread=False`). Extending it with two new tables (`llm_rules`, `script_rules`) reuses connection management, env loading, and the test pattern (tests set `DAAS_DATABASE_URL` to a temp file). A separate `rules.db` would double the infra for no benefit.

**Alternatives considered:** a dedicated `rules.db` file — rejected because it splits state, breaks the single-`DAAS_DATABASE_URL` test pattern, and offers no isolation advantage for SQLite.

### D2: Two tables (`llm_rules`, `script_rules`) instead of one typed table
The demand distinguishes LLM rules (`instruction`) from script rules (`extract_rule`) — their core extraction fields differ and do not overlap. Two tables give each a clean, typed column set and a per-type uniqueness constraint on `(indicator, document_type)`. Shared metadata columns (`module`, `applies_to`, `unit`, `period_type`, `value_range`, `source_type`, `source`, `position`, `document_type`) are duplicated across both tables.

**Alternatives considered:** a single `rules` table with a `type` column and nullable `instruction`/`extract_rule` — rejected because it weakens the schema (two mutually-exclusive non-null columns) and loses per-type uniqueness.

### D3: Read API maps DB rows to the existing dict shape (adapter, not a rewrite)
The pipeline reads `r["name"]`, `r["module"]`, `r["applies_to"]`, `r["source"]["selectors"]`, etc. To avoid touching every call site, `load_rules()` returns the same `{"rules": [...]}` dict shape, mapping the DB `indicator` column → the in-memory `name` field and serializing `applies_to`/`source` from JSON columns. The Pydantic registry in `indicators_models` rebuilds from these dicts unchanged. This makes the DB swap transparent to the extraction logic.

**Alternatives considered:** refactor the pipeline to consume ORM objects directly — rejected as a large, risky change unrelated to the demand.

### D4: Migration maps rich fields to the demand's 4 fields, preserving metadata
The demand's LLM-rule fields are `{indicator, instruction, position, document_type}`. The existing rules carry far more (`applies_to`, `module`, `value_range`, etc.). The migration stores the demand's 4 fields **plus** the existing metadata as additional columns, so nothing is lost. Field mapping: `name`→`indicator`; `note`+`aliases`+`source` description→`instruction` (free text); `source.selectors`→`position` (serialized JSON of the selectors chain); `report_type`→`document_type`. All non-script rules (akshare/computed/external included) go into `llm_rules` with `source_type` preserved.

### D5: Script extractor registry re-introduces the deleted `indicators_extractors.py` pattern
A new module (e.g. `script_extractors.py`) restores the `register(name, fn)` / `get(name)` registry with the four original extractors, re-implemented as `(section_text, rule, period) -> {value, unit, note}`. Dispatch resolves a rule to a script rule by looking up `script_rules.extract_rule`; unknown extractors return `{value: null, note: "unknown extractor: ..."}` rather than raising. No arbitrary code execution — only registered callables run.

**Alternatives considered:** store executable Python source in `extract_rule` and `eval` it — rejected on safety grounds (rules are LLM-generated); a constrained registry is safer and auditable.

### D6: Skills live under `.claude/skills/`, each with `SKILL.md` + `scripts/`
`skill-creator` is a built-in Claude Code skill that bootstraps project-scoped skills. Each of the 5 skills gets its own directory with a `SKILL.md` (invocation contract) and a `scripts/<generator>.py` that calls the existing LLM client (`cnreport_tools.call_llm_pydantic`) with a pydantic output model, validates, and persists via the rules-database write API. The `scripts/` dir also holds a serialized copy of the generated artifacts for inspection/VCS.

### D7: In-process read cache with write invalidation
`load_rules()` caches the rule list in-process (matching today's `_RULES_CACHE`). The write API (`upsert_llm_rule` / `upsert_script_rule`) invalidates this cache and the Pydantic registry so the next read reflects the write. Tests that need isolation set `DAAS_DATABASE_URL` to a temp file, as they already do.

## Risks / Trade-offs

- **Migration data fidelity** → The `instruction` and `position` fields are *derived* from richer fields (`note`/`aliases`/`source` vs `source.selectors`). To avoid loss, the full `source`/`note`/`aliases` are preserved in their own columns; `instruction`/`position` are convenience projections. A reconciliation test asserts the post-migration rule set produces the same `applicable_rules` and Pydantic schema as the JSON.
- **`--rules` / `set_registry_path()` break** → Tests and `scripts/extract_indicators*.py` use `--rules` to point at fixture JSON. **Mitigation:** replace with a `seed_rules_from_json(path)` test helper that loads a fixture JSON into a temp DB, so fixtures keep working with a one-line change.
- **Per-call DB reads** → Reading from SQLite on every `load_rules()` call is slower than reading a cached JSON blob. **Mitigation:** in-process cache (D7); SQLite reads of a few hundred rows are sub-millisecond locally.
- **LLM-generated rule quality** → The generator skills' output may be wrong. **Mitigation:** pydantic validation rejects malformed output; the `scripts/` dir copy is reviewable in diff; script `extract_rule` values must match a registered extractor name (unknown → null result, not a crash).
- **Schema duplication across two tables** → Shared metadata columns are duplicated. **Trade-off:** accepted for per-type clarity and uniqueness (D2); a future refactor could extract a shared `rule_metadata` table if it becomes a maintenance burden.

## Migration Plan

1. Add `LlmRule` / `ScriptRule` ORM models to `cnreport_models.py`; ensure `create_all` runs on startup (extend the existing init in `cnreport_database.py`).
2. Add `scripts/migrate_rules_to_db.py` (idempotent JSON→DB seed). Run once against `daas.db`.
3. Add the read API (`load_rules` from DB) and adapter mapping; flip `indicators_client.load_rules()` and `indicators_models._build_registry()` to use it. Keep `indicator_rules.json` as the seed.
4. Add `script_extractors.py` (registry) and wire script-rule dispatch into `_run_extractor` / `get_indicator`.
5. Add the write API (`upsert_llm_rule` / `upsert_script_rule`).
6. Build the 5 skills under `.claude/skills/` via skill-creator, each with its pydantic model + generator script.
7. Update tests: replace `--rules`/`set_registry_path` with `seed_rules_from_json` against a temp `DAAS_DATABASE_URL`.

**Rollback:** revert the code; `daas.db` is unchanged in shape (new tables are additive) and `indicator_rules.json` is untouched, so the pre-change JSON path is restorable by reverting `load_rules()` to read the file.

## Open Questions

- **Skill 5 output format:** Should the "full extraction script" be a runnable `.py` file, or a declarative manifest the existing `extract_indicators` consumes? *Leaning toward a runnable `.py` per document_type, but confirm during implementation.*
- **CSV→DB shortcut:** Should `scripts/migrate_indicators_csv.py` eventually write directly to the DB, skipping the JSON hop? *Deferred to a follow-up change; for now CSV→JSON→DB.*
- **`position` semantics:** Should `position` be the raw `selectors[]` JSON, or a normalized `(section, fallback)` pair? *Leaning toward raw selectors JSON to preserve the company-filter behavior; finalize in implementation.*
