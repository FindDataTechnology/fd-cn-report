## 1. Rules database — schema & setup

- [x] 1.1 Add `LlmRule` ORM model to `cnreport_models.py` with columns: `id`, `indicator`, `instruction`, `position`, `document_type`, `module`, `subgroup`, `applies_to` (JSON), `unit`, `period_type`, `value_range` (JSON), `source_type`, `source` (JSON), `aliases` (JSON); unique constraint on `(indicator, document_type)`.
- [x] 1.2 Add `ScriptRule` ORM model to `cnreport_models.py` with columns: `id`, `indicator`, `extract_rule`, `position`, `document_type`, plus the shared metadata columns from 1.1; unique constraint on `(indicator, document_type)`.
- [x] 1.3 Ensure `create_all` runs on startup in `cnreport_database.py` so the new tables are created alongside the existing ones (confirm against the existing `DAAS_DATABASE_URL` / default `sqlite:///daas.db`).
- [x] 1.4 Add a pydantic `LlmRuleModel` / `ScriptRuleModel` in a new `rules_models.py` (or `indicators_models.py`) validating the demand's required fields (`indicator`, `instruction`/`extract_rule`, `position`, `document_type`).

## 2. Migration: `indicator_rules.json` → DB

- [x] 2.1 Create `scripts/migrate_rules_to_db.py` with a `migrate(rules_path=indicator_rules.json, db_url=None)` function mapping `name`→`indicator`, `note`+`aliases`+`source`→`instruction`, `source.selectors`→`position` (JSON), `report_type`→`document_type`, carrying through `module`/`applies_to`/`unit`/`period_type`/`value_range`/`source_type`/`source`.
- [x] 2.2 Make the migration idempotent: re-running over an unchanged JSON inserts 0 rows and updates 0 rows (upsert by `(indicator, document_type)`).
- [x] 2.3 Add a `__main__` CLI (`python -m scripts.migrate_rules_to_db` or `python scripts/migrate_rules_to_db.py`) honoring `DAAS_DATABASE_URL`.
- [x] 2.4 Run the migration against `daas.db` and assert 321 rows land in `llm_rules`, 0 in `script_rules`.

## 3. Read API & wire the pipeline to the DB

- [x] 3.1 Add a `rules_db.py` module exposing `load_rules() -> {"rules": [...]}` that reads `llm_rules` and maps each row to the existing in-memory dict shape (DB `indicator` → dict `name`; deserialize `applies_to`/`source`/`value_range` JSON).
- [x] 3.2 Add an in-process cache for `load_rules()` with an `invalidate_rules_cache()` helper, mirroring today's `_RULES_CACHE`.
- [x] 3.3 Flip `indicators_client.load_rules()` (and `_RULES_CACHE`) to delegate to `rules_db.load_rules()`; remove the hardcoded `indicator_rules.json` read.
- [x] 3.4 Update `indicators_models._build_registry()` / `rebuild_registry()` to build the Pydantic model registry from DB-sourced dicts (verify the model schema is unchanged).
- [x] 3.5 Replace `set_registry_path(path)` with `seed_rules_from_json(path)` (a test helper that loads a fixture JSON into a temp `DAAS_DATABASE_URL` DB) and update call sites in `indicators_client.py`.
- [x] 3.6 Confirm `applicable_rules(company)` and `rules_hash()` behave identically post-migration.

## 4. Script-rule extraction engine

- [x] 4.1 Create `script_extractors.py` restoring the `register(name, fn)` / `get(name)` registry, with built-in extractors `regex_amount`, `percent_value`, `table_row`, `headcount` as `(section_text, rule, period) -> {value, unit, note}`.
- [x] 4.2 Add `get_script_rule(indicator, document_type)` to `rules_db.py` reading the `script_rules` table.
- [x] 4.3 Wire script-rule dispatch into `indicators_client._run_extractor()` and the `get_indicator` path: if a `script_rules` row exists for the indicator+document_type, call `get(extract_rule)`; unknown extractors return `{value: null, note: "unknown extractor: ..."}`.
- [x] 4.4 Ensure script-rule results carry `extractor: "script:<name>"` and merge into the bundle with the same shape as LLM results.

## 5. Write API (for generator skills)

- [x] 5.1 Add `upsert_llm_rule(rule_dict)` and `upsert_script_rule(rule_dict)` to `rules_db.py` — insert-or-update by `(indicator, document_type)`, validate against the pydantic model, and invalidate the read cache.
- [x] 5.2 Add `save_to_skill_scripts_dir(skill_name, payload)` helper writing a serialized artifact to `.claude/skills/<skill>/scripts/`.

## 6. Generator skills (under `.claude/skills/`)

- [x] 6.1 Use `skill-creator` to scaffold `fd-cnreport-llm-rules-creator` (`SKILL.md` + `scripts/generate_llm_rules.py`): accept a document section excerpt, call `call_llm_pydantic` with an `LlmRuleModel` output schema, upsert to `llm_rules`, save to the skill's `scripts/` dir.
- [x] 6.2 Use `skill-creator` to scaffold `fd-cnreport-pdf-llm-rules-creator` (`SKILL.md` + `scripts/generate_pdf_llm_rules.py`): split a whole PDF by outline into chapters (reuse the existing outline parser), generate LLM rules per chapter, validate, persist.
- [x] 6.3 Use `skill-creator` to scaffold `fd-cnreport-pdf-scripts-creator` (`SKILL.md` + `scripts/generate_scripts.py`): read a single rule/document's rules from the DB, generate `script_rules` via LLM, validate, persist.
- [x] 6.4 Use `skill-creator` to scaffold `fd-cnreport-pdf-scripts-by-type-creator` (`SKILL.md` + `scripts/generate_scripts_by_type.py`): read all rules for a `document_type` from the DB, generate script rules per target indicator, validate, persist.
- [x] 6.5 Use `skill-creator` to scaffold `fd-cnreport-pdf-full-scripts-creator` (`SKILL.md` + `scripts/generate_full_scripts.py`): generate a full end-to-end extraction script per `document_type` from the DB rules, save to the DB and the skill's `scripts/` dir.

## 7. Tests & validation

- [x] 7.1 Add a migration test asserting 321 rules land in `llm_rules`, 0 in `script_rules`, and re-running is a no-op.
- [x] 7.2 Add a read-API test asserting `load_rules()` from a temp DB matches the pre-change JSON-derived rule set for `applicable_rules` and the Pydantic schema hash.
- [x] 7.3 Add a script-extractor test: a `script_rules` row with `extract_rule: "regex_amount"` dispatches to the registry and returns `{value, unit}` without an LLM call; an unknown extractor returns `{value: null}`.
- [x] 7.4 Add a write-API test: `upsert_llm_rule` inserts then updates by `(indicator, document_type)`; invalid input raises and writes nothing.
- [x] 7.5 Update existing tests that use `--rules` / `set_registry_path()` to use `seed_rules_from_json` against a temp `DAAS_DATABASE_URL`.
- [x] 7.6 Run `openspec validate db-backed-rules-pipeline` and the existing pytest suite (`.venv/bin/python -m pytest`) green.
