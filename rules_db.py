"""Database-backed rule store for indicator rules.

Replaces the flat ``indicator_rules.json`` read with a SQLite-backed store
(``llm_rules`` + ``script_rules`` tables in the project ``daas.db``). The
extraction pipeline reads rules through :func:`load_rules`, which returns the
same ``{"rules": [...]}`` dict shape it always did — DB ``indicator`` maps to
the in-memory ``name`` field and ``document_type`` to ``report_type`` so the
existing call sites are unchanged.

``indicator_rules.json`` is retained as a migration seed, consumed by
:func:`migrate_from_json` (one-shot) and :func:`seed_rules_from_json` (test
fixture swap, used by ``indicators_client.set_registry_path``).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

import cnreport_database
from cnreport_models import LlmRuleV2, ScriptRule
from rules_models import LlmRuleModel, ScriptRuleModel

logger = logging.getLogger(__name__)

# Allow the rules JSON to be located via env var (useful when fd-cn-report is
# pip-installed and indicator_rules.json isn't sitting next to the module, e.g.
# in a Docker image). Falls back to the module dir for local/source installs.
DEFAULT_RULES_JSON = Path(
    os.environ.get("CNREPORT_RULES_JSON")
    or (Path(__file__).resolve().parent / "indicator_rules.json")
)

# In-process cache of the rule list; cleared by invalidate_rules_cache().
_RULES_CACHE: Optional[dict] = None


# ── session helper ───────────────────────────────────────────────


def _session():
    """A fresh SQLAlchemy session against the current DAAS_DATABASE_URL."""
    return cnreport_database.get_db().get_session()


# ── read API ──────────────────────────────────────────────────────


def _read_rules() -> list[dict]:
    """Read every ``llm_rules_v2`` row as a pipeline rule dict (no caching)."""
    rules: list[dict] = []
    with _session() as session:
        rows = (
            session.query(LlmRuleV2)
            .order_by(LlmRuleV2.taxonomy_code, LlmRuleV2.indicator)
            .all()
        )
        for row in rows:
            rules.append(row.to_rule_dict())
    return rules


def _seed_from_json(rules_path: Path | str, *, clear: bool) -> int:
    """Insert every rule from a JSON file into ``llm_rules_v2`` (no cache touch).

    ``clear`` first deletes all existing ``llm_rules_v2`` rows. Returns the count
    inserted. Used by :func:`load_rules` (auto-seed on empty) and
    :func:`seed_rules_from_json` (fixture swap) — neither of which should
    recurse into :func:`invalidate_rules_cache`.
    """
    raw = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    rules = raw.get("rules", []) if isinstance(raw, dict) else raw
    with _session() as session:
        if clear:
            session.query(LlmRuleV2).delete()
        for rule in rules:
            session.add(LlmRuleV2(**_json_rule_to_llm_columns(rule)))
        session.commit()
    return len(rules)


def load_rules() -> dict:
    """Load and cache the indicator rule set from the ``llm_rules_v2`` table.

    Returns ``{"rules": [...]}`` where each rule dict has the new taxonomy-based
    shape (``name``, ``taxonomy_code``, ``document_type_codes``,
    ``indicator_translations``, ``applies_to``, ...).
    Cached in-process; call :func:`invalidate_rules_cache` after a write.

    If the table is empty and the default seed JSON exists, auto-seeds from it
    once so an un-migrated database still serves the full rule set (mirroring
    the pre-migration behavior where ``indicator_rules.json`` was always
    available).
    """
    global _RULES_CACHE
    if _RULES_CACHE is not None:
        return _RULES_CACHE
    rules = _read_rules()
    if not rules and DEFAULT_RULES_JSON.exists():
        logger.info("llm_rules_v2 empty; auto-seeding from %s", DEFAULT_RULES_JSON)
        _seed_from_json(DEFAULT_RULES_JSON, clear=False)
        rules = _read_rules()
    _RULES_CACHE = {"rules": rules}
    return _RULES_CACHE


def invalidate_rules_cache() -> None:
    """Drop the in-process rule cache and the Pydantic model registry."""
    global _RULES_CACHE
    _RULES_CACHE = None
    try:
        from indicators_models import rebuild_registry as _rebuild
        _rebuild()
    except Exception as e:  # noqa: BLE001 — registry rebuild is best-effort
        logger.debug("model registry rebuild skipped: %s", e)


# ── JSON → row mapping (migration) ────────────────────────────────


def _derive_instruction(rule: dict) -> str:
    """Build the demand's ``instruction`` text from a JSON rule's metadata."""
    parts: list[str] = []
    note = rule.get("note")
    if note:
        parts.append(str(note))
    aliases = rule.get("aliases") or []
    if aliases:
        parts.append("aliases: " + ", ".join(str(a) for a in aliases[:3]))
    src = rule.get("source")
    if isinstance(src, dict) and src:
        parts.append("source: " + json.dumps(src, ensure_ascii=False))
    return " | ".join(parts)


def _derive_position(rule: dict) -> str:
    """Serialize the rule's section position (selectors or source) as JSON."""
    src = rule.get("source")
    if isinstance(src, dict):
        selectors = src.get("selectors")
        if selectors is not None:
            return json.dumps(selectors, ensure_ascii=False)
        return json.dumps(src, ensure_ascii=False)
    return ""


def _document_type_of(rule: dict) -> str:
    rt = rule.get("report_type") or rule.get("document_type") or "年报"
    return str(rt)


def _json_rule_to_llm_columns(rule: dict) -> dict:
    """Map one ``indicator_rules.json`` rule dict to LlmRuleV2 column values."""
    return {
        "indicator": rule.get("name"),
        "taxonomy_code": None,  # Will be set by migration mapping
        "document_type_codes": json.dumps(_document_type_of(rule)),  # Single-element array for old schema
        "indicator_zh": rule.get("name"),  # Default to Chinese
        "indicator_en": None,  # To be filled by translation step
        "indicator_ja": None,
        "indicator_ko": None,
        "applies_to": json.dumps(rule.get("applies_to")) if rule.get("applies_to") else None,
        "source_type": rule.get("source_type"),
        "extractor": rule.get("extractor"),
        "unit": rule.get("unit"),
        "period_type": rule.get("period_type"),
        "value_range": json.dumps(rule.get("value_range")) if rule.get("value_range") else None,
        "source": json.dumps(rule.get("source")) if rule.get("source") else None,
        "aliases": json.dumps(rule.get("aliases") or []),
        "note": rule.get("note"),
        "direction": rule.get("direction"),
        "instruction": _derive_instruction(rule),
        "position": _derive_position(rule),
    }


_LLM_COL_KEYS = set(_json_rule_to_llm_columns({}))


# ── migration (idempotent) ───────────────────────────────────────


def migrate_from_json(
    rules_path: Path | str = DEFAULT_RULES_JSON,
    db_url: Optional[str] = None,
) -> dict:
    """Idempotently seed ``llm_rules_v2`` from a JSON rule file.

    Upserts each rule by ``indicator``. Re-running over an unchanged file
    inserts 0 rows and updates 0 rows (change-detected per column).
    ``script_rules`` is untouched (no script rules exist in the JSON).
    Returns ``{"inserted": n, "updated": n, "unchanged": n, "total": n}``.
    """
    if db_url is not None:
        os.environ["DAAS_DATABASE_URL"] = db_url
        cnreport_database.reset_db()

    raw = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    rules = raw.get("rules", []) if isinstance(raw, dict) else raw

    inserted = updated = unchanged = 0
    with _session() as session:
        for rule in rules:
            cols = _json_rule_to_llm_columns(rule)
            existing = (
                session.query(LlmRuleV2)
                .filter(LlmRuleV2.indicator == cols["indicator"])
                .first()
            )
            if existing is None:
                session.add(LlmRuleV2(**cols))
                inserted += 1
                continue
            changed = False
            for key, val in cols.items():
                if getattr(existing, key) != val:
                    setattr(existing, key, val)
                    changed = True
            if changed:
                updated += 1
            else:
                unchanged += 1
        session.commit()

    invalidate_rules_cache()
    total = inserted + updated + unchanged
    logger.info(
        "rules migration: inserted=%d updated=%d unchanged=%d total=%d",
        inserted, updated, unchanged, total,
    )
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged, "total": total}


def seed_rules_from_json(rules_path: Path | str) -> dict:
    """Replace the ``llm_rules`` table with the contents of a JSON rule file.

    Used by ``indicators_client.set_registry_path`` (the ``--rules`` / test
    fixture swap). Clears ``llm_rules`` then inserts every rule from the file.
    """
    count = _seed_from_json(rules_path, clear=True)
    invalidate_rules_cache()
    return {"seeded": count}


# ── write API (for generator skills) ──────────────────────────────


def _rule_dict_to_llm_columns(rule: dict) -> dict:
    """Map a skill-produced rule dict (demand's field names) to LlmRuleV2 columns."""
    instruction = rule.get("instruction") or _derive_instruction(rule)
    position = rule.get("position") or _derive_position(rule)
    # Handle both old (single document_type) and new (document_type_codes array) formats
    doc_type_codes = rule.get("document_type_codes") or []
    if not doc_type_codes:
        doc_types = rule.get("document_types") or []
        if doc_types:
            # Convert old document_types to new document_type_codes
            doc_type_codes = doc_types  # They might already be in the new format
        else:
            doc_type = rule.get("document_type") or rule.get("report_type") or "年报"
            doc_type_codes = [doc_type]
    # Handle indicator translations
    indicator_translations = rule.get("indicator_translations") or {}
    indicator_name = rule.get("indicator") or rule.get("name")
    return {
        "indicator": indicator_name,
        "taxonomy_code": rule.get("taxonomy_code"),
        "document_type_codes": json.dumps(doc_type_codes),
        "indicator_zh": indicator_translations.get("zh") or indicator_name,
        "indicator_en": indicator_translations.get("en"),
        "indicator_ja": indicator_translations.get("ja"),
        "indicator_ko": indicator_translations.get("ko"),
        "source_type": rule.get("source_type"),
        "extractor": rule.get("extractor"),
        "applies_to": json.dumps(rule.get("applies_to")) if rule.get("applies_to") else None,
        "unit": rule.get("unit"),
        "period_type": rule.get("period_type"),
        "value_range": json.dumps(rule.get("value_range")) if rule.get("value_range") else None,
        "source": json.dumps(rule.get("source")) if rule.get("source") else None,
        "aliases": json.dumps(rule.get("aliases") or []),
        "note": rule.get("note"),
        "direction": rule.get("direction"),
        "instruction": instruction,
        "position": position,
    }


def _rule_dict_to_script_columns(rule: dict) -> dict:
    return {
        "indicator": rule.get("indicator") or rule.get("name"),
        "document_type": rule.get("document_type") or rule.get("report_type") or "年报",
        "extract_rule": rule.get("extract_rule"),
        "position": rule.get("position") or "",
        "module": rule.get("module"),
        "subgroup": rule.get("subgroup"),
        "source_type": rule.get("source_type"),
        "applies_to": rule.get("applies_to"),
        "unit": rule.get("unit"),
        "period_type": rule.get("period_type"),
        "source": rule.get("source"),
        "aliases": rule.get("aliases") or [],
        "note": rule.get("note"),
    }


def upsert_llm_rule(rule: dict) -> dict:
    """Insert-or-update an LLM rule by ``indicator``.

    Validates against :class:`rules_models.LlmRuleModel` first. Invalid input
    raises and writes nothing. Invalidates the read cache.
    """
    validated = LlmRuleModel.model_validate(rule)
    payload = validated.model_dump(exclude_none=False)
    cols = _rule_dict_to_llm_columns(payload)
    # Minimal enforcement for industry-scoped document_type_codes:
    # require an explicit non-empty instruction so the LLM has actionable guidance.
    doc_type_codes = json.loads(cols.get("document_type_codes") or "[]")
    instruction = str(cols.get("instruction") or "").strip()
    if any(code.startswith("cn/") for code in doc_type_codes) and not instruction:
        raise ValueError("LLM rule instruction must be non-empty for industry-scoped document_type_code (cn/...)")
    with _session() as session:
        # Find existing rule by indicator (since we deduplicated, one row per indicator)
        row = (
            session.query(LlmRuleV2)
            .filter(LlmRuleV2.indicator == cols["indicator"])
            .first()
        )
        if row is None:
            row = LlmRuleV2(**cols)
            session.add(row)
        else:
            # Merge document_type_codes arrays
            existing_codes = set(json.loads(row.document_type_codes or "[]"))
            new_codes = set(doc_type_codes)
            merged_codes = sorted(existing_codes | new_codes)
            cols["document_type_codes"] = json.dumps(merged_codes)
            for key, val in cols.items():
                setattr(row, key, val)
        session.commit()
        session.refresh(row)
        result = row.to_rule_dict()
    invalidate_rules_cache()
    return result


def upsert_script_rule(rule: dict) -> dict:
    """Insert-or-update a script rule by ``(indicator, document_type)``.

    Validates against :class:`rules_models.ScriptRuleModel` first.
    """
    validated = ScriptRuleModel.model_validate(rule)
    payload = validated.model_dump(exclude_none=False)
    cols = _rule_dict_to_script_columns(payload)
    with _session() as session:
        row = (
            session.query(ScriptRule)
            .filter(
                ScriptRule.indicator == cols["indicator"],
                ScriptRule.document_type == cols["document_type"],
            )
            .first()
        )
        if row is None:
            row = ScriptRule(**cols)
            session.add(row)
        else:
            for key, val in cols.items():
                setattr(row, key, val)
        session.commit()
        session.refresh(row)
        result = row.to_rule_dict()
    invalidate_rules_cache()
    return result


# ── script-rule lookup (extraction dispatch) ──────────────────────


def get_script_rule(indicator: str, document_type: Optional[str] = None) -> Optional[dict]:
    """Return the script rule for ``indicator`` (+ ``document_type``), or None.

    If ``document_type`` is None, returns the first script rule matching the
    indicator (any document_type). Used by the extraction dispatch to decide
    whether a rule should run via the script registry instead of the LLM.
    """
    with _session() as session:
        q = session.query(ScriptRule).filter(ScriptRule.indicator == indicator)
        if document_type:
            q = q.filter(ScriptRule.document_type == document_type)
        row = q.first()
        return row.to_rule_dict() if row else None


# ── skill scripts-dir persistence ─────────────────────────────────


def save_to_skill_scripts_dir(skill_name: str, payload: Any) -> Path:
    """Write a serialized artifact to a skill's ``scripts/`` directory.

    ``payload`` is JSON-serialized unless it is already a ``str``. Creates the
    directory if needed. Returns the written path.
    """
    skill_dir = (
        Path(__file__).resolve().parent / ".claude" / "skills" / skill_name / "scripts"
    )
    skill_dir.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(
        payload, ensure_ascii=False, indent=2
    )
    out_path = skill_dir / f"{skill_name}.json"
    out_path.write_text(text, encoding="utf-8")
    return out_path


# ── taxonomy browsing and querying ────────────────────────────────


def list_report_taxonomy(parent_code: Optional[str] = None) -> list[dict]:
    """List all report taxonomy entries, optionally filtered by parent.

    Returns list of taxonomy entries with multi-language labels.
    """
    from cnreport_models import ReportTaxonomy

    with _session() as session:
        q = session.query(ReportTaxonomy)
        if parent_code is not None:
            q = q.filter(ReportTaxonomy.parent_code == parent_code)
        q = q.order_by(ReportTaxonomy.sort_order, ReportTaxonomy.code)
        return [row.to_dict() for row in q.all()]


def get_report_taxonomy(code: str) -> Optional[dict]:
    """Get a single report taxonomy entry by code.

    Returns the taxonomy entry with multi-language labels, or None if not found.
    """
    from cnreport_models import ReportTaxonomy

    with _session() as session:
        row = session.query(ReportTaxonomy).filter(ReportTaxonomy.code == code).first()
        return row.to_dict() if row else None


def get_report_taxonomy_children(code: str) -> list[dict]:
    """Get all children of a report taxonomy node.

    Returns list of child taxonomy entries.
    """
    return list_report_taxonomy(parent_code=code)


def list_document_taxonomy(
    parent_code: Optional[str] = None,
    country: Optional[str] = None,
) -> list[dict]:
    """List all document taxonomy entries, optionally filtered.

    Returns list of document taxonomy entries with multi-language labels.
    """
    from cnreport_models import DocumentTaxonomy

    with _session() as session:
        q = session.query(DocumentTaxonomy)
        if parent_code is not None:
            q = q.filter(DocumentTaxonomy.parent_code == parent_code)
        if country is not None:
            q = q.filter(DocumentTaxonomy.country == country)
        q = q.order_by(DocumentTaxonomy.sort_order, DocumentTaxonomy.code)
        return [row.to_dict() for row in q.all()]


def get_document_taxonomy(code: str) -> Optional[dict]:
    """Get a single document taxonomy entry by code.

    Returns the document taxonomy entry with multi-language labels, or None if not found.
    """
    from cnreport_models import DocumentTaxonomy

    with _session() as session:
        row = session.query(DocumentTaxonomy).filter(DocumentTaxonomy.code == code).first()
        return row.to_dict() if row else None


def get_document_taxonomy_children(code: str) -> list[dict]:
    """Get all children of a document taxonomy node.

    Returns list of child document taxonomy entries.
    """
    return list_document_taxonomy(parent_code=code)
