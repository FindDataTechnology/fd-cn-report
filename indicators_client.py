"""Indicator rules engine for fd-cn-report.

Loads the data-driven rule set (``indicator_rules.json``), profiles a company
to decide which rules apply, and resolves indicator values via three source
strategies — akshare line items, annual-report PDF sections (LLM or pluggable
Python extractors), and locally-computed ratios.

Mirrors the load/resolve pattern of ``cninfo_client`` (data-driven JSON,
no code change to add a rule) and the cache pattern of ``report_cache``.

Public entry points (used by cnreport_tools + the standalone script)::

    load_rules() / resolve_rule(name) / list_rules(module, query, company)
    profile_company(stock_code, name) / applicable_rules(stock_code, name)
    get_indicator(indicator, ticker_or_name, year, period)
    extract_indicators(ticker_or_name, year, indicators, form, extractor_mode)
    render_methodology()            # → markdown string
    rules_hash(rules)               # cache-busting digest

Errors at the public boundary are returned as ``{"error": ...}`` by the
``@_tool_safe`` wrappers in ``cnreport_tools``; this module raises freely.
"""
from __future__ import annotations

import hashlib
import logging
import os
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

_REGISTRY_PATH = Path(__file__).resolve().parent / "indicator_rules.json"
"""Default migration-seed path. Rules are loaded from the rules database
(:mod:`rules_db`); this is kept for the ``--rules`` metadata and as the
seed consumed by ``scripts/migrate_rules_to_db.py``."""


def load_rules() -> dict:
    """Load and cache the indicator rule set from the rules database.

    Returns ``{"rules": [...]}`` where each rule dict is the pipeline's
    existing shape (``name``, ``module``, ``applies_to``, ``source``, ...).
    Delegates to :func:`rules_db.load_rules`, which reads the ``llm_rules``
    table (mapping DB ``indicator``→dict ``name`` and ``document_type``→
    ``report_type``). ``indicator_rules.json`` is a migration seed, not the
    runtime source of truth.
    """
    import rules_db

    return rules_db.load_rules()


def set_registry_path(path) -> None:
    """Swap the active rule set to the rules in ``path`` (a JSON file).

    Seeds the rules database from the file (clearing ``llm_rules`` first) and
    rebuilds the Pydantic model registry. Used by the standalone extraction
    script (``--rules``) and by tests pointing at fixture rule sets. Also
    updates ``_REGISTRY_PATH`` so callers that record the rule source
    (e.g. ``bundle["rule_file"]``) reflect the swap.
    """
    from indicators_models import rebuild_registry as _rebuild_models

    global _REGISTRY_PATH
    _REGISTRY_PATH = Path(path)
    _rebuild_models(path)


def invalidate_rules_cache() -> None:
    """Drop the in-process rule cache and rebuild the Pydantic model registry."""
    import rules_db

    rules_db.invalidate_rules_cache()

# ── bank sub-type lookup ──────────────────────────────────────────
# Curated ticker → sub_type for the listed Chinese banks. Name-keyword
# heuristic is the fallback for tickers not listed here.
_BANK_SUBTYPE_BY_TICKER: dict[str, str] = {
    # 国有大行
    "601398": "国有大行", "601939": "国有大行", "601288": "国有大行",
    "601988": "国有大行", "601328": "国有大行", "601658": "国有大行",
    # 股份制
    "600000": "股份制", "600015": "股份制", "600016": "股份制",
    "600036": "股份制", "601166": "股份制", "601318": "股份制",
    "601818": "股份制", "601998": "股份制", "600999": "股份制",
    "000001": "股份制",
}

_SUBTYPE_BY_NAME_KEYWORD = (
    (("城市", "城商", "银行股份"), "城商行"),
    (("农村", "农商", "农信"), "农商行"),
)


# ── rule loading + name resolution ────────────────────────────────


def _rules() -> list[dict]:
    return load_rules().get("rules", [])


def rules_hash(rules: Optional[list[dict]] = None) -> str:
    """Stable 16-char sha1 of the rule set + Pydantic model schemas — cache busting."""
    from indicators_models import rules_hash as _model_hash

    rs = rules if rules is not None else _rules()
    h = hashlib.sha1(
        json.dumps(rs, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    h.update(_model_hash().encode())
    return h.hexdigest()[:16]


def _normalize(s: str) -> str:
    """Strip whitespace + common punctuation for tolerant Chinese name matching."""
    return re.sub(r"[\s　·、，,。.：:（）()\-_/]", "", (s or ""))


def resolve_rule(name: str) -> Optional[dict]:
    """Resolve an indicator name to a rule: exact → alias → normalized substring."""
    if not name:
        return None
    rules = _rules()
    for r in rules:
        if r.get("name") == name:
            return r
    for r in rules:
        if name in (r.get("aliases") or []):
            return r
    target = _normalize(name)
    if not target:
        return None
    for r in rules:
        if target == _normalize(r.get("name", "")):
            return r
        for a in r.get("aliases", []):
            if target == _normalize(a):
                return r
    for r in rules:
        if target and target in _normalize(r.get("name", "")):
            return r
        for a in r.get("aliases", []):
            if target and target in _normalize(a):
                return r
    return None


def list_rules(
    module: Optional[str] = None,
    query: Optional[str] = None,
    company: Optional[str] = None,
    taxonomy_code: Optional[str] = None,
) -> dict:
    """Return rules grouped by module or taxonomy, optionally filtered.

    ``module`` filters to one module (legacy); unknown module returns an error dict.
    ``taxonomy_code`` filters to rules with a specific taxonomy_code or its children.
    ``query`` does a normalized substring match over name+aliases.
    ``company`` (ticker or name) filters to ``applicable_rules`` and includes
    the resolved ``{industry, sub_type}`` profile.
    """
    rules = _rules()
    profile = None
    if company is not None:
        profile, rules = _applicable_for(company, rules)

    # Filter by taxonomy_code (new way)
    if taxonomy_code is not None:
        rules = [r for r in rules if r.get("taxonomy_code", "").startswith(taxonomy_code)]
    # Filter by module (legacy way)
    elif module is not None:
        modules = sorted({r.get("module", "") for r in rules})
        if module not in modules:
            return {"error": f"unknown module: {module!r}", "available": modules}
        rules = [r for r in rules if r.get("module") == module]

    if query:
        q = _normalize(query)
        rules = [
            r for r in rules
            if q in _normalize(r.get("name", ""))
            or any(q in _normalize(a) for a in r.get("aliases", []))
        ]

    # Group by taxonomy_code (new way) or module (legacy way)
    if taxonomy_code is not None:
        # Group by taxonomy_code
        groups: dict[str, dict[str, list[dict]]] = {}
        for r in rules:
            tc = r.get("taxonomy_code", "uncategorized")
            groups.setdefault(tc, {}).setdefault("", []).append(_summarize_rule(r))

        result: dict[str, Any] = {
            "groups": [
                {"taxonomy_code": tc, "indicators": items}
                for tc, subs in groups.items()
                for items in subs.values()
            ],
            "count": len(rules),
        }
    else:
        # Group by module then subgroup (legacy way)
        groups = {}
        for r in rules:
            groups.setdefault(r.get("module", ""), {}).setdefault(
                r.get("subgroup", ""), []
            ).append(_summarize_rule(r))

        result = {
            "groups": [
                {"module": m, "subgroups": [{"subgroup": sg, "indicators": items} for sg, items in subs.items()]}
                for m, subs in groups.items()
            ],
            "count": len(rules),
        }

    if profile is not None:
        result["company_profile"] = profile
    return result


def _summarize_rule(r: dict) -> dict:
    return {
        "name": r.get("name"),
        "aliases": r.get("aliases", []),
        "taxonomy_code": r.get("taxonomy_code"),
        "document_type_codes": r.get("document_type_codes", []),
        "module": r.get("module"),  # Legacy field
        "subgroup": r.get("subgroup"),  # Legacy field
        "source_type": r.get("source_type"),
        "extractor": r.get("extractor"),
        "applies_to": r.get("applies_to"),
        "unit": r.get("unit"),
        "period_type": r.get("period_type"),
    }


# ── company profiling + applicability ─────────────────────────────


def profile_company(stock_code: str, name: str = "") -> dict:
    """Classify a company as ``{industry, sub_type}``.

    Banks resolve to one of {国有大行, 股份制, 城商行, 农商行} via a curated
    ticker lookup with a name-keyword heuristic fallback. Non-banks return
    ``{industry: "unknown", sub_type: None}`` (still eligible for ``industry: "*"``
    rules).
    """
    code = (stock_code or "").strip()
    sub = _BANK_SUBTYPE_BY_TICKER.get(code)
    if sub:
        return {"industry": "bank", "sub_type": sub}
    nm = name or ""
    for keywords, st in _SUBTYPE_BY_NAME_KEYWORD:
        if any(k in nm for k in keywords):
            return {"industry": "bank", "sub_type": st}
    # 6-digit code with no match → unknown (could be a non-bank A-share)
    return {"industry": "unknown", "sub_type": None}


def _company_profile_from_lookup(stock_code: str, name: str = "") -> dict:
    return profile_company(stock_code, name)


def applies_to(rule: dict, profile: dict, stock_code: str) -> bool:
    """Evaluate a rule's ``applies_to`` against a company profile + ticker."""
    ap = rule.get("applies_to") or {}
    industry = ap.get("industry", "*")
    if industry not in ("*", profile.get("industry", "unknown")):
        return False
    sub_types = ap.get("sub_types") or ["*"]
    if "*" not in sub_types and profile.get("sub_type") not in sub_types:
        return False
    companies = ap.get("companies") or ["*"]
    if "*" not in companies and stock_code not in companies:
        return False
    exclude = ap.get("exclude_companies") or []
    if stock_code in exclude:
        return False
    return True


def applicable_rules(stock_code: str, name: str = "") -> tuple[dict, list[dict]]:
    """Return ``(profile, [applicable rules])`` for a company."""
    profile = profile_company(stock_code, name)
    rules = _rules()
    return profile, [r for r in rules if applies_to(r, profile, stock_code)]


def _applicable_for(company: str, rules: list[dict]) -> tuple[dict, list[dict]]:
    """Resolve `company` (ticker or name) via cninfo and filter `rules`."""
    import cninfo_client

    row = cninfo_client.lookup_company(company)
    if not row:
        # fall back to treating the input as a raw ticker so profiling still works
        stock = company if (company or "").isdigit() else ""
        profile = profile_company(stock, company)
        return profile, [r for r in rules if applies_to(r, profile, stock)]
    stock = row.get("stock_code", "")
    profile = profile_company(stock, row.get("name", ""))
    return profile, [r for r in rules if applies_to(r, profile, stock)]


# ── source routing primitives ─────────────────────────────────────


def _to_json_val(v: Any) -> Any:
    """Convert Decimal (from Pydantic) to float so the bundle is JSON-safe."""
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    return v


def _value_obj(
    value: Any, *, rule: dict, source: str, extractor: str, period: str,
    provenance: str = "", note: str = "",
) -> dict:
    return {
        "indicator": rule.get("name"),
        "value": _to_json_val(value),
        "unit": rule.get("unit", ""),
        "source_type": rule.get("source_type"),
        "extractor": extractor,
        "source": source,
        "period": period,
        "provenance": provenance,
        "note": note,
    }


def _resolve_via_akshare(company: dict, rule: dict, year: int, period: str) -> dict:
    """Read one field from akshare's structured statements."""
    import financials_client

    src = rule.get("source") or {}
    statement = src.get("statement")
    field = src.get("field")
    if not statement or not field:
        return _value_obj(
            None, rule=rule, source="akshare", extractor="akshare", period=period,
            note="akshare rule missing statement/field",
        )
    try:
        all_stmts = financials_client.get_statements(
            company["stock_code"], period=period, exchange=company.get("exchange", ""),
        )
    except Exception as e:  # noqa: BLE001 — akshare/Sina flakiness must not kill the whole year
        return _value_obj(
            None, rule=rule, source="akshare", extractor="akshare", period=period,
            note=f"akshare unavailable: {type(e).__name__}: {e}",
        )
    stmt = all_stmts.get(statement)
    if not stmt:
        return _value_obj(
            None, rule=rule, source=f"akshare:{statement}", extractor="akshare", period=period,
            note=f"statement not returned: {statement}",
        )
    columns = stmt.get("columns", [])
    data = stmt.get("data", [])
    if field not in columns:
        # try a normalized substring match on column names
        matches = [c for c in columns if _normalize(field) in _normalize(c)]
        if not matches:
            return _value_obj(
                None, rule=rule, source=f"akshare:{statement}", extractor="akshare",
                period=period, note=f"field not in columns: {field!r}; have {columns}",
            )
        field = matches[0]
    idx = columns.index(field)
    # pick the row matching the requested fiscal year. Rows carry their own
    # period-end date (Dec-31 for CN periodic forms; other year-ends for HK
    # companies), so match on the 4-digit year rather than assuming Dec-31.
    target = str(year)
    row = None
    date_col = next((c for c in ("报告日", "报告期", "日期") if c in columns), None)
    if date_col:
        di = columns.index(date_col)
        ystr = str(year)
        for r in data:
            # str() may be "2024-12-31", "2024-12-31 00:00:00", or "20241231";
            # rows are already annual-filtered, so matching the 4-digit year is correct
            # (the old exact `== target` compare fell through to data[0] for datetime
            # strings, leaking the most-recent year's value into every year).
            if str(r[di])[:4] == ystr:
                row = r
                break
    if row is None and data:
        row = data[0]  # fall back to the most recent row
    if row is None:
        return _value_obj(
            None, rule=rule, source=f"akshare:{statement}.{field}", extractor="akshare",
            period=period, note="no rows in statement",
        )
    value = row[idx] if idx < len(row) else None
    return _value_obj(
        value, rule=rule, source=f"akshare:{statement}.{field}", extractor="akshare",
        period=period, provenance=f"akshare row {target}",
    )


def _resolve_section(
    text: str, outline: list[dict], rule: dict, stock_code: str,
    form: str = "",
    page_offsets: Optional[list[int]] = None,
    page_count: int = 0,
):
    """Walk the rule's ``selectors[]`` chain; return ``(section_text, matched)``.

    Company-filtered selectors are tried first; on a miss the next entry is
    tried. Returns ``(None, [tried selectors])`` when nothing hits.
    """
    import cnreport_tools as T

    src = rule.get("source") or {}
    selectors = src.get("selectors") or []
    # Fallback: use subgroup as a single selector when no explicit selectors exist.
    if not selectors and rule.get("subgroup"):
        selectors = [{"section": rule["subgroup"]}]
    import report_section_map as RSM

    tried: list[str] = []
    # order: company-matching selectors first, then the rest, preserving chain order within each
    def _company_matches(sel: dict) -> bool:
        companies = sel.get("company") or []
        return (not companies) or (stock_code in companies)

    ordered = [s for s in selectors if _company_matches(s)] + [
        s for s in selectors if not _company_matches(s)
    ]
    for sel in ordered:
        section = sel.get("section")
        if not section:
            continue
        for candidate in RSM.candidates(form, section):
            tried.append(candidate)
            entry = T.resolve_selector(outline, candidate)
            if entry is None:
                continue
            body = T.extract_section_text(
                text,
                outline,
                entry,
                page_offsets=page_offsets,
                page_count=page_count,
            )
            if body:
                return body, candidate
    # statement-module fallback: try the canonical consolidated statement title
    # (合并资产负债表 / 合并利润表 / 合并现金流量表) via resolve_statement. This
    # honors rules whose selector is a descriptive section label that did not
    # resolve directly, and matches the get_financial_statements strategy.
    stmt_key = _MODULE_TO_STATEMENT.get(rule.get("module", ""))
    if stmt_key is not None:
        entry = T.resolve_statement(outline, stmt_key)
        if entry is not None:
            body = T.extract_section_text(text, outline, entry,
                                          page_offsets=page_offsets,
                                          page_count=page_count)
            if body:
                return body, entry.get("title", stmt_key)
    # body-text fallback: search raw text for each candidate title and slice.
    # Catches sections present in the PDF text but missing from the outline
    # (e.g. 财务报表附注, 员工情况 sub-sections).
    for sel in ordered:
        section = sel.get("section")
        if not section:
            continue
        for candidate in RSM.candidates(form, section):
            tried.append(candidate)
            body = T.extract_statement_text(text, candidate)
            if body:
                return body, f"<body-text: {candidate}>"
            # Also try direct text search for generic section titles
            body = T.extract_section_by_title(text, candidate)
            if body:
                return body, f"<body-text: {candidate}>"
    return None, tried


# rule module → statement key for resolve_statement (the consolidated-first matcher).
_MODULE_TO_STATEMENT: dict[str, str] = {
    "balance_sheet": "balance_sheet",
    "income_statement": "income_statement",
    "cashflow": "cashflow",
}

# CNINFO form name → CSV-style compat key used in a rule's `report_type` field.
# Used by `_form_compatible` to filter rules per periodic form: an annual-only
# rule (report_type "年报") is skipped for 第一季度报告, while a universal rule
# (report_type "年报/半年报/季报") applies to every form.
_FORM_COMPAT_KEY: dict[str, str] = {
    "年度报告": "年报",
    "半年度报告": "半年报",
    "第一季度报告": "季报",
    "第三季度报告": "季报",
    "招股说明书": "招股说明书",
    "港股全球发售": "港股全球发售",
    "港股年度报告": "港股年度报告",
}

# New document_type format patterns (for old document_types array)
_FORM_COMPAT_PATTERNS: dict[str, list[str]] = {
    "年度报告": ["annual-report"],
    "半年度报告": ["interim-report"],
    "第一季度报告": ["quarterly-report"],
    "第三季度报告": ["quarterly-report"],
    "招股说明书": ["prospectus"],
    "港股全球发售": ["hk-prospectus"],
    "港股年度报告": ["hk-annual-report"],
}

# New taxonomy-based document_type_codes mapping
_FORM_COMPAT_TAXONOMY: dict[str, list[str]] = {
    "年度报告": ["cn_annual", "hk_annual", "hk_annual_report"],
    "半年度报告": ["cn_interim", "hk_interim"],
    "第一季度报告": ["cn_quarterly"],
    "第三季度报告": ["cn_quarterly"],
    "招股说明书": ["cn_prospectus", "hk_prospectus"],
    "港股全球发售": ["hk_prospectus"],
    "港股年度报告": ["hk_annual_report", "hk_annual"],
}


def _form_compatible(rule: dict, form: str) -> bool:
    """True if `rule` should be attempted for the given periodic `form`.

    A rule without a `report_type`, `document_type_codes`, or `document_types`
    defaults to broadly applicable (treated as present in every form) — this
    covers hand-authored rules that pre-date the CSV `report_type` column.
    Otherwise the form's compat key must match at least one of the rule's
    document types. Unknown `form` values default to compatible so callers
    passing raw category codes don't accidentally suppress extraction.
    """
    # Check new taxonomy-based document_type_codes first
    doc_type_codes = rule.get("document_type_codes") or []
    if doc_type_codes:
        # Match against taxonomy codes
        taxonomy_codes = _FORM_COMPAT_TAXONOMY.get(form, [])
        if taxonomy_codes:
            # Compatible if any document_type_code matches
            return any(code in doc_type_codes for code in taxonomy_codes)
        # If no mapping for this form, default to compatible
        return True

    # Check old document_types array (backward compatibility)
    doc_types = rule.get("document_types") or []
    if doc_types:
        # Try new pattern format first (e.g., "annual-report")
        patterns = _FORM_COMPAT_PATTERNS.get(form, [])
        if patterns:
            # Compatible if any document_type contains any pattern
            return any(pattern in dt for dt in doc_types for pattern in patterns)

        # Fall back to old key format (e.g., "年报")
        key = _FORM_COMPAT_KEY.get(form)
        if key is None:
            return True
        # Compatible if any document_type contains the key
        return any(key in dt for dt in doc_types)

    # Fall back to old report_type field for backward compatibility
    rt = rule.get("report_type")
    if not rt:
        return True
    key = _FORM_COMPAT_KEY.get(form)
    if key is None:
        return True
    return key in rt


def _build_llm_system_prompt(
    section_title: str, period: str, year: Optional[int], expected_keys: str,
) -> str:
    """Build the LLM system prompt for one section extraction.

    The prompt is parameterized by the requested period (and ``year`` when
    known) and is report-type-agnostic: it does not assume a CN annual report
    and does not hard-code a year, so it applies to prospectus and HK report
    text as well as CN periodic reports.
    """
    period_hint = f" ({year})" if year else ""
    return (
        "You extract structured financial figures from financial-report text. "
        "Return only valid JSON. "
        f"The text is from the section '{section_title}'. "
        f"The text may contain multiple periods of data. Return only the value for "
        f"the requested period{period_hint} as a single number, not a dict. "
        f"Your response MUST be a JSON object with these exact keys: {expected_keys}. "
        "Match indicator names to text lines by financial meaning, not exact wording. "
        "Examples: '母公司股东'->'归属于母公司普通股股东的净利润', "
        "'业务及管理费'->'业务及管理费用', "
        "'发行债务证券所收到的现金'->'发行债券收到的现金', "
        "'投资联营及合营企业所支付的现金'->'取得子公司、合营联营企业及其他营业单位支付的现金净额', "
        "'税前利润'->'利润总额'. "
        "Set to null only if the item genuinely does not exist in the text."
    )


def _llm_extract_section(
    section_text: str, rules: list[dict], period: str, *, max_chars: int | None = None,
    pdf_url: str | None = None, section_key: str | None = None,
    year: Optional[int] = None,
) -> dict[str, dict]:
    """One Pydantic-typed LLM call per module over a section's rules.

    Groups ``rules`` by ``module`` (balance_sheet, income_statement, cashflow,
    report_section), makes one ``call_llm_pydantic`` per module using the
    corresponding Pydantic model from ``indicators_models``, and returns
    ``{indicator_name: {value, unit, note}}``.

    On any failure (no API key, parse error) returns one entry per rule with
    ``value=None`` and a note.  Caching delegates to :mod:`llm_section_cache`
    using the Pydantic model's rules hash as the version key.
    """
    import cnreport_tools as T
    import llm_section_cache as LSC
    from indicators_models import model_to_json_schema, model_for_subgroup

    if max_chars is None:
        max_chars = int(os.environ.get("LLM_MAX_CHARS", "24000"))

    cfg = T.llm_config()
    if not cfg["api_key"]:
        return {
            r["name"]: {"value": None, "unit": r.get("unit", ""), "note": "LLM_API_KEY not configured"}
            for r in rules
        }

    # Group by (module, subgroup) — each group gets a focused Pydantic model
    # with fewer fields, reducing LLM hallucination.
    by_group: dict[tuple[str, str], list[dict]] = {}
    for r in rules:
        mod = r.get("module", "")
        sub = r.get("subgroup") or mod
        by_group.setdefault((mod, sub), []).append(r)

    _log = logging.getLogger(__name__)
    all_results: dict[str, dict] = {}

    for (module, subgroup), group_rules in by_group.items():
        wanted_names = [r["name"] for r in group_rules]
        model_cls = model_for_subgroup(module, subgroup, group_rules)
        model_rh = rules_hash(group_rules)
        # Build the LLM user prompt
        snippet = section_text[:max_chars]
        section_title = section_key or module
        schema = model_to_json_schema(model_cls)
        field_descriptions = []
        for nm in wanted_names:
            field_info = schema["schema"]["properties"].get(nm, {})
            desc = field_info.get("description", nm)
            field_descriptions.append(f"  - {nm}: {desc}")

        expected_keys = json.dumps(wanted_names, ensure_ascii=False)
        system = _build_llm_system_prompt(section_title, period, year, expected_keys)
        user = (
            f"Financial section: {section_title}\n\n"
            f"Period: {period}\n\n"
            f"Relevant text:\n{snippet}\n\n"
            f"Extract values for these indicators:\n" + "\n".join(field_descriptions) + "\n\n"
            f"Return a JSON object with keys: {expected_keys}. "
            "Each value must be a single number or null."
        )

        # Cache lookup (when caller supplied pdf_url + section_key)
        _cached_raw = None
        if pdf_url and section_key:
            try:
                _cached_raw = LSC.get(pdf_url, section_key, period, model_rh)
            except Exception as e:
                _log.debug("section cache read error: %s", e)

        if _cached_raw is not None:
            cached_names = {LSC._normalize_name(r.get("indicator", "")) for r in _cached_raw}
            wanted_norm = {LSC._normalize_name(n) for n in wanted_names}
            missing_norm = wanted_norm - cached_names
            if not missing_norm:
                # Full hit
                for rec in _cached_raw:
                    nm = rec.get("indicator", "")
                    if LSC._normalize_name(nm) in wanted_norm:
                        all_results[nm] = {
                            "value": rec.get("value"),
                            "unit": rec.get("unit") or "",
                            "note": "llm-section-cache",
                        }
                for r in group_rules:
                    if r["name"] not in all_results:
                        all_results[r["name"]] = {"value": None, "unit": r.get("unit", ""), "note": "llm-section-cache: not returned"}
                continue

        # Call the LLM with the focused subgroup schema
        try:
            instance = T.call_llm_pydantic(system, user, model_cls)
        except RuntimeError as e:
            for r in group_rules:
                all_results[r["name"]] = {
                    "value": None, "unit": r.get("unit", ""),
                    "note": f"llm error: {e}",
                }
            continue

        raw = instance.model_dump()
        if pdf_url and section_key:
            try:
                records = [{"indicator": k, "value": v} for k, v in raw.items()]
                LSC.put(pdf_url, section_key, period, model_rh, records)
            except Exception as e:
                _log.debug("section cache write error: %s", e)

        for r in group_rules:
            all_results[r["name"]] = {
                "value": _to_json_val(raw.get(r["name"])),
                "unit": r.get("unit", ""),
                "note": "llm",
            }

    return all_results


def _run_extractor(
    section_text: str, rule: dict, period: str, extractor_mode: str = "auto",
    llm_cache: Optional[dict] = None,
    *,
    pdf_url: str | None = None,
    section_key: str | None = None,
    year: Optional[int] = None,
) -> dict:
    """Dispatch one report rule, honoring ``extractor_mode``.

    Script rules (a ``script_rules`` row matching the indicator +
    ``document_type``) are dispatched first via the named-extractor registry in
    :mod:`script_extractors` — they are deterministic, so they run in any mode
    (including ``python``) and never need an LLM call or API key.

    Remaining rules go through the LLM extractor. ``llm_cache`` (when provided)
    carries the batched LLM result for this section so a single indicator lookup
    reuses the per-section call instead of re-querying. When ``pdf_url`` +
    ``section_key`` are provided, the persistent section cache
    (``llm_section_cache``) is consulted first; a miss falls through to
    ``_llm_extract_section`` and the result is written back to the cache.
    """
    # script-rule dispatch (deterministic; runs in any mode, no LLM)
    script_result = _try_script_extractor(section_text, rule, period)
    if script_result is not None:
        return script_result

    if extractor_mode == "python":
        return {"value": None, "unit": rule.get("unit", ""),
                "note": "skipped: llm extractor in python mode"}

    if llm_cache is not None and rule["name"] in llm_cache:
        return llm_cache[rule["name"]]
    result = _llm_extract_section(
        section_text, [rule], period,
        pdf_url=pdf_url, section_key=section_key, year=year,
    )
    return result.get(rule["name"], {"value": None, "unit": rule.get("unit", ""), "note": "llm: empty"})


def _try_script_extractor(
    section_text: str, rule: dict, period: str,
) -> Optional[dict]:
    """Run a matching script rule's named extractor, or return ``None``.

    Looks up a ``script_rules`` row by the rule's indicator (``name``) and
    ``document_type`` (``report_type``). If one exists, dispatches to the
    registered extractor named by ``extract_rule``. Unknown extractors and
    extractor errors return ``{value: None}`` rather than raising. Returns
    ``None`` when no script rule exists (so the caller falls through to the
    LLM path).
    """
    import script_extractors
    import rules_db

    name = rule.get("name") or rule.get("indicator")
    if not name:
        return None
    doc_type = rule.get("report_type") or rule.get("document_type")
    srule = rules_db.get_script_rule(name, doc_type)
    if srule is None:
        return None
    extract_rule = srule.get("extract_rule")
    fn = script_extractors.get(extract_rule)
    if fn is None:
        return {
            "value": None, "unit": rule.get("unit", ""),
            "note": f"unknown extractor: {extract_rule}",
            "extractor": f"script:{extract_rule}",
        }
    try:
        res = fn(section_text, srule, period)
    except Exception as e:  # noqa: BLE001 — extractor must not abort extraction
        return {
            "value": None, "unit": rule.get("unit", ""),
            "note": f"script:{extract_rule} error: {e}",
            "extractor": f"script:{extract_rule}",
        }
    res.setdefault("unit", rule.get("unit", ""))
    res.setdefault("note", f"script:{extract_rule}")
    res["extractor"] = f"script:{extract_rule}"
    return res


def _resolve_via_report(
    text: str, outline: list[dict], rule: dict, stock_code: str,
    year: int, period: str, form: str, extractor_mode: str, pdf_url: str,
    llm_cache: Optional[dict] = None,
    page_offsets: Optional[list[int]] = None,
    page_count: int = 0,
) -> dict:
    section_text, matched = _resolve_section(
        text,
        outline,
        rule,
        stock_code,
        form=form,
        page_offsets=page_offsets,
        page_count=page_count,
    )
    if section_text is None:
        return _value_obj(
            None, rule=rule, source=f"report:{matched}", extractor=rule.get("extractor", "llm"),
            period=period, provenance=pdf_url,
            note=f"section not found; tried {matched}",
        )
    res = _run_extractor(
        section_text, rule, period, extractor_mode, llm_cache=llm_cache,
        pdf_url=pdf_url, section_key=matched, year=year,
    )
    return _value_obj(
        res.get("value"), rule=rule, source=f"report:{matched}",
        extractor=res.get("extractor")
        or (res.get("note", "").startswith("llm") and "llm")
        or (rule.get("extractor") or "llm"),
        period=period, provenance=pdf_url, note=res.get("note", ""),
    )


# ── safe formula evaluator ────────────────────────────────────────

_TOK_RE = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([+\-*/()])|([^+\-*/()\s]+))")


def _eval_formula(formula: str, base_values: dict[str, Any]) -> tuple[Any, Optional[str]]:
    """Evaluate ``formula`` with ``+ - * / ()``, numeric literals, and indicator-name refs.

    Returns ``(value, None)`` on success or ``(None, "missing input: <name>")``.
    Uses Python's ``ast`` for safe parsing — no eval/exec.
    """
    import ast

    # token names referenced in the formula resolve to base_values
    def _resolve_tok(name: str) -> Any:
        if name in base_values:
            return base_values[name]
        return None

    # Replace each indicator name (Chinese token) with a placeholder var,
    # then build an ast and walk it.
    tokens: list[str] = []
    pos = 0
    while pos < len(formula):
        m = _TOK_RE.match(formula, pos)
        if not m:
            pos += 1
            continue
        pos = m.end()
        num, op, name = m.groups()
        if num is not None:
            tokens.append(num)
        elif op is not None:
            tokens.append(op)
        elif name is not None:
            tokens.append(name)
    # Now parse tokens into an expression string with names quoted as vars.
    # Build a name→symbol map to substitute, then use ast.
    expr_parts: list[str] = []
    name_map: dict[str, str] = {}
    for t in tokens:
        if t in ("+", "-", "*", "/", "(", ")"):
            expr_parts.append(t)
        elif re.fullmatch(r"\d+(?:\.\d+)?", t):
            expr_parts.append(t)
        else:
            sym = name_map.get(t)
            if sym is None:
                sym = f"__v{len(name_map)}"
                name_map[t] = sym
            expr_parts.append(sym)
    expr = " ".join(expr_parts)
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None, "formula syntax error"

    env: dict[str, float] = {}
    for original, sym in name_map.items():
        raw = _resolve_tok(original)
        if raw is None or raw == "":
            return None, f"missing input: {original}"
        try:
            env[sym] = float(str(raw).replace(",", ""))
        except (TypeError, ValueError):
            return None, f"non-numeric input: {original}={raw!r}"

    def _ev(n: ast.AST) -> float:
        if isinstance(n, ast.Expression):
            return _ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name):
            return env[n.id]
        if isinstance(n, ast.BinOp):
            a, b = _ev(n.left), _ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if isinstance(n.op, ast.Div):
                return a / b if b != 0 else None
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -_ev(n.operand)
        raise ValueError("unsupported operation in formula")

    try:
        result = _ev(node)
    except ZeroDivisionError:
        return None, "division by zero"
    except Exception as e:
        return None, f"formula error: {e}"
    return result, None


def _resolve_via_computed(rule: dict, base_values: dict[str, Any], period: str) -> dict:
    src = rule.get("source") or {}
    formula = src.get("formula", "")
    value, err = _eval_formula(formula, base_values)
    return _value_obj(
        value, rule=rule, source=f"computed:{formula}", extractor="computed",
        period=period, note=err or "",
    )


# ── context + single-indicator resolution ─────────────────────────


class _Ctx:
    """Carries everything a resolution pass needs to avoid re-fetching."""

    def __init__(
        self, company, filing, text, outline, year, period, form, extractor_mode,
        page_offsets: Optional[list[int]] = None,
    ):
        self.company = company
        self.filing = filing
        self.text = text
        self.outline = outline
        self.year = year
        self.period = period
        self.form = form
        self.extractor_mode = extractor_mode
        self.page_offsets = page_offsets or []
        self._section_cache: dict[str, str] = {}  # section title → body text

    @property
    def pdf_url(self) -> str:
        return (self.filing or {}).get("pdf_url", "")

    @property
    def stock_code(self) -> str:
        return (self.company or {}).get("stock_code", "")


def _resolve_rule_value(rule: dict, ctx: _Ctx, depth: int = 0) -> dict:
    """Resolve one rule (any source_type) within a context. Recurses for computed inputs."""
    if depth > 6:
        return _value_obj(None, rule=rule, source="depth", extractor="auto",
                          period=ctx.period, note="recursion depth exceeded")
    st = rule.get("source_type")
    if st == "akshare":
        return _resolve_via_akshare(ctx.company, rule, ctx.year, ctx.period)
    if st == "report":
        return _resolve_via_report(
            ctx.text, ctx.outline, rule, ctx.stock_code, ctx.year, ctx.period,
            ctx.form, ctx.extractor_mode, ctx.pdf_url,
            page_offsets=ctx.page_offsets or None,
            page_count=len(ctx.page_offsets) - 1 if len(ctx.page_offsets) > 1 else 0,
        )
    if st == "computed":
        src = rule.get("source") or {}
        inputs = src.get("inputs") or []
        bases: dict[str, Any] = {}
        for inp in inputs:
            irule = resolve_rule(inp)
            if irule is None:
                bases[inp] = None
                continue
            ires = _resolve_rule_value(irule, ctx, depth + 1)
            bases[inp] = ires.get("value")
        return _resolve_via_computed(rule, bases, ctx.period)
    if st == "external":
        # realtime / market-data indicator — not present in the report PDF
        return _value_obj(
            None, rule=rule, source="external", extractor="",
            period=ctx.period, note="external source — not extractable from report",
        )
    return _value_obj(None, rule=rule, source="unknown", extractor="auto",
                      period=ctx.period, note=f"unknown source_type: {st}")


def _build_ctx(
    ticker_or_name: str, year: int, form: str, period: str, extractor_mode: str,
    *, fetch_pdf: bool = True,
) -> tuple[Optional[_Ctx], Optional[dict]]:
    """Resolve company + filing + (optionally) cached PDF text → a `_Ctx`.

    Returns ``(ctx, None)`` on success or ``(None, error_dict)`` on failure.
    """
    import cninfo_client
    import report_cache
    import cnreport_tools as T

    company = cninfo_client.lookup_company(ticker_or_name)
    if not company:
        return None, {"error": f"no company matched: {ticker_or_name!r}"}
    filings = cninfo_client.query_announcements(
        company["stock_code"], company["org_id"], form=form, year=year, limit=5,
    )
    if not filings:
        return None, {
            "error": f"no filing found for {company['stock_code']} form={form!r} year={year}"
        }
    # Prefer the A-share filing over H-share / overseas variants and skip summaries.
    # H股公告 / 海外公告 titles contain "H股" or "海外" — skip them when
    # a plain A-share filing exists. Also skip "摘要" (summary) filings.
    top = filings[0]
    for f in filings:
        title = (f.get("title") or "").lower()
        if "h股" not in title and "海外" not in title and "摘要" not in title:
            top = f
            break
    text = outline = page_offsets = None
    if fetch_pdf:
        text, cache_info = report_cache.get_or_fetch(
            top["pdf_url"],
            stock_code=company["stock_code"], year=year, form=form,
            announcement_id=top.get("announcement_id") or "",
        )
        # prefer enriched outline (pymupdf + regex + statement titles) when available
        enriched = cache_info.get("enriched_outline")
        if enriched:
            outline = enriched
        else:
            # try building enriched outline from cached PDF
            try:
                cache_dir = report_cache.cache_dir()
                pdf_path = cache_dir / f"{cache_info.get('stem', '')}.pdf"
                pdf_data = pdf_path.read_bytes() if pdf_path.exists() else None
                enriched, page_off, _ = T.build_enriched_outline(text, pdf_data=pdf_data)
                if enriched:
                    outline = enriched
                    if page_off:
                        page_offsets = page_off
            except Exception:
                pass
        if outline is None:
            outline = T.parse_outline(text)
        page_offsets = cache_info.get("page_offsets", [])
    ctx = _Ctx(company, top, text, outline, year, period, form, extractor_mode,
               page_offsets=page_offsets)
    return ctx, None


# ── public entry points ───────────────────────────────────────────


def get_indicator(
    indicator: str, ticker_or_name: str, year: int, period: str = "annual",
) -> dict:
    """Resolve a single named indicator for a company + period."""
    rule = resolve_rule(indicator)
    if rule is None:
        return {"error": f"unknown indicator: {indicator!r}",
                "available": [r["name"] for r in _rules()][:30]}

    ctx, err = _build_ctx(ticker_or_name, year, "年度报告", period, "auto", fetch_pdf=False)
    if err:
        return err
    # applicability check
    profile, applicable = applicable_rules(ctx.stock_code, ctx.company.get("name", ""))
    if not any(r["name"] == rule["name"] for r in applicable):
        return {"error": "indicator not applicable to this company",
                "indicator": indicator, "company": ctx.stock_code}

    # only fetch the PDF when the rule actually needs it (report or computed-with-report-inputs)
    needs_pdf = rule["source_type"] in ("report",) or (
        rule["source_type"] == "computed"
        and _computed_needs_pdf(rule)
    )
    if needs_pdf:
        ctx2, err = _build_ctx(ticker_or_name, year, ctx.form, period, "auto", fetch_pdf=True)
        if err:
            return err
        ctx = ctx2
    res = _resolve_rule_value(rule, ctx)
    return {
        "stock_code": ctx.stock_code,
        "company_name": ctx.company.get("name", ""),
        "year": year,
        "indicator": rule["name"],
        **res,
    }


def _computed_needs_pdf(rule: dict, depth: int = 0) -> bool:
    """True if a computed rule (transitively) depends on a report-source input."""
    if depth > 6:
        return False
    for inp in (rule.get("source") or {}).get("inputs", []):
        irule = resolve_rule(inp)
        if irule is None:
            continue
        if irule["source_type"] == "report":
            return True
        if irule["source_type"] == "computed" and _computed_needs_pdf(irule, depth + 1):
            return True
    return False


# ── concurrency ───────────────────────────────────────────────────


def _resolve_concurrency(concurrency: Optional[int]) -> int:
    """Resolve the in-call worker cap for a concurrent extraction pass.

    A positive ``concurrency`` wins; otherwise the ``EXTRACT_CONCURRENCY`` env
    var is read (default ``4``). The result is clamped to ``>= 1`` — ``1`` means
    sequential, and callers short-circuit the pool entirely at that value so
    behavior and call order are identical to a plain loop (the deterministic,
    reproducible path used by tests and rate-fragile providers).
    """
    if concurrency is not None and concurrency > 0:
        return concurrency
    try:
        env = int(os.environ.get("EXTRACT_CONCURRENCY", "4"))
    except (TypeError, ValueError):
        env = 4
    return max(1, env)


def _resolve_batch_concurrency(concurrency: Optional[int]) -> int:
    """Resolve the cross-target worker cap for ``extract_indicators_batch``.

    Independent from the in-call cap (``_resolve_concurrency``); default ``2``
    via ``EXTRACT_BATCH_CONCURRENCY`` so the product
    ``batch_concurrency × extract_concurrency`` stays modest (default ``2 × 4 = 8``
    peak in-flight LLM calls) against provider rate limits.
    """
    if concurrency is not None and concurrency > 0:
        return concurrency
    try:
        env = int(os.environ.get("EXTRACT_BATCH_CONCURRENCY", "2"))
    except (TypeError, ValueError):
        env = 2
    return max(1, env)


def _map_merge(items, fn, concurrency: int, *, label: str = "") -> list:
    """Map ``fn`` over ``items`` concurrently up to ``concurrency`` workers.

    Returns the list of ``fn(item)`` results in **input order**. When
    ``concurrency <= 1`` or there is at most one item, runs inline (no thread
    pool) so behavior and call order are identical to ``[fn(i) for i in items]``
    — the deterministic path used by tests and for reproducibility.

    Workers never mutate shared state: each returns a plain value and the caller
    merges results. This is safe because the I/O-bound call sites are already
    concurrency-safe at this boundary: ``cnreport_tools.call_llm_json`` issues a
    fresh ``httpx.post`` per call (no shared client); ``report_cache`` and
    ``llm_section_cache`` write atomically (``tmp`` + ``os.replace``) to
    *distinct* keys; ``_RULES_CACHE`` is read-only after first load; and
    ``financials_client.get_statements`` holds no module-level mutable state.

    ``label`` is a debug-only tag surfaced in log messages to identify which
    pass (``section`` / ``akshare`` / ``batch``) is running.
    """
    if concurrency <= 1 or len(items) <= 1:
        return [fn(it) for it in items]
    _log = logging.getLogger(__name__)
    _log.debug("concurrent %s pass: %d items, %d workers", label or "map", len(items), concurrency)
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        return list(ex.map(fn, items))


def extract_indicators(
    ticker_or_name: str,
    year: int,
    indicators: Optional[list[str]] = None,
    form: str = "年度报告",
    extractor_mode: str = "auto",
    concurrency: Optional[int] = None,
) -> dict:
    """Extract many indicators for one company/year in one pass.

    Fetches the PDF once, groups report-rules by section (one LLM call per
    section), runs Python extractors individually, and computes derived ratios
    locally. Caches the resulting bundle to disk keyed by the applicable rule set.
    """
    import report_cache
    import cnreport_tools as T

    ctx, err = _build_ctx(ticker_or_name, year, form, "annual", extractor_mode, fetch_pdf=True)
    if err:
        return err
    profile, applicable = applicable_rules(ctx.stock_code, ctx.company.get("name", ""))

    # Form-compat filter: rules whose report_type doesn't include this form's
    # compat key are skipped (source_type "form_filter"), not extracted. This
    # mirrors extract_indicators_by_position so prospectus/HK rules don't run
    # for periodic forms and vice versa. External (realtime/market) rules are
    # form-agnostic and bypass this filter so they still reach the external
    # group below (-> unresolved), not the form_filter skip.
    def _form_ok(r: dict) -> bool:
        return r.get("source_type") == "external" or _form_compatible(r, form)

    skipped: list[dict] = []

    # select the requested subset (after applicability + form-compat)
    if indicators is None:
        for r in applicable:
            if not _form_ok(r):
                skipped.append({"indicator": r["name"], "source_type": "form_filter", "note": f"not in {form}"})
        target_rules = [r for r in applicable if _form_ok(r)]
    else:
        applicable_names = {r["name"] for r in applicable}
        target_rules = []
        unknown: list[str] = []
        not_applicable: list[str] = []
        for nm in indicators:
            r = resolve_rule(nm)
            if r is None:
                unknown.append(nm)
            elif not _form_ok(r):
                skipped.append({"indicator": nm, "source_type": "form_filter", "note": f"not in {form}"})
            elif r["name"] not in applicable_names:
                not_applicable.append(nm)
            else:
                target_rules.append(r)

    rh = rules_hash(target_rules)
    stem = report_cache.cache_key(
        ctx.pdf_url, stock_code=ctx.stock_code, year=year, form=form,
        announcement_id=ctx.filing.get("announcement_id") or "",
    )
    if stem is not None:
        cached = report_cache.get_cached_indicators(stem, rh)
        if cached is not None:
            cached["cached"] = True
            return cached

    cap = _resolve_concurrency(concurrency)
    results: dict[str, dict] = {}
    missing: list[dict] = []
    unresolved: list[dict] = []
    section_cache_reuse = 0  # incremented in the LLM per-section loop below

    if indicators is not None:
        for nm in unknown:
            missing.append({"indicator": nm, "reason": "unknown"})
        for nm in not_applicable:
            missing.append({"indicator": nm, "reason": "not applicable"})

    # --- akshare group: one network fetch per rule, run concurrently up to `cap` ---
    akshare_rules = [r for r in target_rules if r["source_type"] == "akshare"]

    def _resolve_one_akshare(r: dict) -> tuple[str, dict]:
        return r["name"], _resolve_via_akshare(ctx.company, r, year, "annual")

    for name, val in _map_merge(akshare_rules, _resolve_one_akshare, cap, label="akshare"):
        results[name] = val

    # --- external group: realtime/market indicators not in the report PDF → unresolved ---
    external_rules = [r for r in target_rules if r["source_type"] == "external"]
    for r in external_rules:
        unresolved.append({
            "indicator": r["name"],
            "note": "external source — not extractable from report",
        })

    # --- report group: group by resolved section, batch LLM per section ---
    report_rules = [r for r in target_rules if r["source_type"] == "report"]
    # resolve each rule's section first
    section_of: dict[str, str] = {}
    section_text_cache: dict[str, str] = {}
    for r in report_rules:
        body, matched = _resolve_section(
            ctx.text, ctx.outline, r, ctx.stock_code,
            form=ctx.form,
            page_offsets=ctx.page_offsets or None,
            page_count=len(ctx.page_offsets) - 1 if ctx.page_offsets and len(ctx.page_offsets) > 1 else 0,
        )
        if body is None:
            results[r["name"]] = _value_obj(
                None, rule=r, source=f"report:{matched}", extractor=r.get("extractor", "llm"),
                period="annual", provenance=ctx.pdf_url, note=f"section not found; tried {matched}",
            )
            missing.append({"indicator": r["name"], "reason": "section not found",
                            "tried": matched})
            continue
        section_of[r["name"]] = matched
        section_text_cache[matched] = body

    # group report rules by section + by extractor mode
    if extractor_mode == "python":
        # only python extractors run; llm rules → unresolved
        for r in report_rules:
            if r["name"] not in section_of:
                continue  # already added to missing
            sec = section_of[r["name"]]
            res = _run_extractor(section_text_cache[sec], r, "annual", "python", year=year)
            results[r["name"]] = _value_obj(
                res.get("value"), rule=r, source=f"report:{sec}",
                extractor=(r.get("extractor", "").startswith("python:") and r["extractor"] or "llm"),
                period="annual", provenance=ctx.pdf_url, note=res.get("note", ""),
            )
            if res.get("value") is None and "skipped" in (res.get("note") or ""):
                unresolved.append({"indicator": r["name"], "note": res["note"]})
    else:
        sections = sorted(set(section_of.values()))

        def _extract_one_section(sec: str) -> tuple[dict[str, dict], int]:
            """Resolve all rules in one section: script rules first, then one LLM call per module for the rest.

            Returns ``(sub_results, reuse_delta)`` so the main thread can merge
            into ``results`` without any shared-dict mutation across workers.
            Disjoint sections own disjoint indicator names and distinct
            section-cache keys, so this is safe to run concurrently.
            """
            all_rules_in_sec = [r for r in report_rules if section_of.get(r["name"]) == sec]
            if extractor_mode == "python":
                return {
                    r["name"]: _value_obj(
                        None, rule=r, source=f"report:{sec}", extractor="llm",
                        period="annual", provenance=ctx.pdf_url,
                        note="skipped: llm extractor in python mode",
                    )
                    for r in all_rules_in_sec
                }, 0
            sub: dict[str, dict] = {}
            llm_rules: list[dict] = []
            for r in all_rules_in_sec:
                script_res = _try_script_extractor(section_text_cache[sec], r, "annual")
                if script_res is not None:
                    val = script_res.get("value")
                    note = script_res.get("note", "")
                    if val is not None:
                        sub[r["name"]] = _value_obj(
                            val, rule=r, source=f"report:{sec}",
                            extractor=script_res.get("extractor", f"script:{note}"),
                            period="annual", provenance=ctx.pdf_url, note=note,
                        )
                    else:
                        llm_rules.append(r)
                else:
                    llm_rules.append(r)
            llm_cache: dict[str, dict] = {}
            reuse = 0
            if llm_rules:
                llm_cache = _llm_extract_section(
                    section_text_cache[sec], llm_rules, "annual",
                    pdf_url=ctx.pdf_url, section_key=sec, year=year,
                )
                for r in llm_rules:
                    rec = llm_cache.get(r["name"], {})
                    if (rec.get("note") or "").startswith("llm-section-cache"):
                        reuse += 1
            for r in llm_rules:
                rec = llm_cache.get(r["name"], {"value": None, "note": "llm: empty"})
                sub[r["name"]] = _value_obj(
                    rec.get("value"), rule=r, source=f"report:{sec}", extractor="llm",
                    period="annual", provenance=ctx.pdf_url, note=rec.get("note", ""),
                )
            return sub, reuse

        # Sections are independent → safe to run concurrently. _map_merge returns
        # outcomes in input (sorted-section) order, so the merged `results` dict
        # matches the prior sequential layout; concurrency<=1 runs inline.
        for sub, reuse in _map_merge(sections, _extract_one_section, cap, label="section"):
            results.update(sub)
            section_cache_reuse += reuse

    # --- computed group: evaluate from bases already in `results` ---
    computed_rules = [r for r in target_rules if r["source_type"] == "computed"]
    # multi-pass so computed rules can depend on other computed rules
    pending = list(computed_rules)
    for _ in range(len(pending) + 1):
        if not pending:
            break
        still: list[dict] = []
        for r in pending:
            src = r.get("source") or {}
            inputs = src.get("inputs") or []
            bases = {inp: (results.get(inp, {}) or {}).get("value") for inp in inputs}
            if any(bases[i] is None for i in inputs):
                # try next pass; inputs might come from another pending computed rule
                still.append(r)
                continue
            results[r["name"]] = _resolve_via_computed(r, bases, "annual")
        if len(still) == len(pending):
            # no progress → unresolved
            for r in still:
                src = r.get("source") or {}
                inputs = src.get("inputs") or []
                missing_inputs = [i for i in inputs if (results.get(i, {}) or {}).get("value") is None]
                results[r["name"]] = _value_obj(
                    None, rule=r, source=f"computed:{src.get('formula','')}", extractor="computed",
                    period="annual", note=f"missing input: {','.join(missing_inputs)}",
                )
                unresolved.append({"indicator": r["name"], "note": f"missing input: {','.join(missing_inputs)}"})
            break
        pending = still

    bundle = {
        "stock_code": ctx.stock_code,
        "company_name": ctx.company.get("name", ""),
        "industry": profile.get("industry"),
        "sub_type": profile.get("sub_type"),
        "year": year,
        "form": form,
        "pdf_url": ctx.pdf_url,
        "cached": False,
        "rules_hash": rh,
        "extractor_mode": extractor_mode,
        "indicators": results,
        "missing": missing,
        "unresolved": unresolved,
        "skipped": skipped,
        "section_cache_reuse": section_cache_reuse,
        "concurrency": cap,
        "dataframe": _build_dataframe(results, ctx.stock_code, ctx.company.get("name", ""), year),
    }
    if stem is not None:
        report_cache.write_cached_indicators(stem, bundle)
    return bundle


# ── position-CSV-driven extraction ────────────────────────────────


def _resolve_csv_path(csv_path: str) -> Path:
    """Resolve a (possibly relative) CSV path against the repo root."""
    p = Path(csv_path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    return p


def load_position_csv(csv_path: str = "docs/indicators_position.csv") -> list[str]:
    """Read the ``indicator`` column of a position CSV → ordered, de-duplicated name list."""
    import csv as _csv

    p = _resolve_csv_path(csv_path)
    rows = list(_csv.DictReader(p.open(encoding="utf-8", newline="")))
    seen: set[str] = set()
    names: list[str] = []
    for r in rows:
        n = (r.get("indicator") or "").strip()
        if n and n not in seen:
            seen.add(n)
            names.append(n)
    return names


def extract_indicators_by_position(
    ticker_or_name: str,
    year: int,
    csv_path: str = "docs/indicators_position.csv",
    extractor: str = "auto",
    indicators: Optional[list[str]] = None,
    form: str = "年度报告",
    concurrency: Optional[int] = None,
) -> dict:
    """Extract the indicators named in a position CSV for one company/year/form.

    Reads the CSV's ``indicator`` column (intersected with ``indicators`` if
    given), resolves each name to a rule, partitions by ``source_type`` and
    form-applicability (``external`` → ``skipped``; form-incompatible →
    ``skipped``; everything else → delegated to ``extract_indicators`` with the
    requested ``form``), and returns the standard bundle plus a ``skipped``
    list and the ``csv_path`` used.

    ``form`` selects the periodic report (年度报告 / 半年度报告 / 第一季度报告 /
    第三季度报告). Each rule's ``report_type`` is consulted via
    ``_form_compatible`` so annual-only indicators (e.g. 分红金额) are skipped
    for quarterly forms instead of being attempted and failing.
    """
    csv_names = load_position_csv(csv_path)
    if indicators:
        wanted = set(indicators)
        csv_names = [n for n in csv_names if n in wanted]

    skipped: list[dict] = []
    missing_unknown: list[dict] = []
    delegate_names: list[str] = []
    for nm in csv_names:
        rule = resolve_rule(nm)
        if rule is None:
            missing_unknown.append({"indicator": nm, "reason": "unknown"})
        elif rule.get("source_type") == "external":
            skipped.append({
                "indicator": nm,
                "source_type": "external",
                "note": "realtime/external — not in report PDF",
            })
        elif not _form_compatible(rule, form):
            # rule's report_type doesn't include this form (e.g. 分红金额 for Q1)
            skipped.append({
                "indicator": nm,
                "source_type": "form_filter",
                "note": f"not in {form}",
            })
        else:
            delegate_names.append(rule["name"])

    if delegate_names:
        bundle = extract_indicators(
            ticker_or_name, year, indicators=delegate_names,
            form=form, extractor_mode=extractor, concurrency=concurrency,
        )
    else:
        # nothing to extract from the report — build a header without fetching the PDF
        ctx, err = _build_ctx(
            ticker_or_name, year, form, "annual", extractor, fetch_pdf=False,
        )
        if err:
            bundle = err
        else:
            profile = profile_company(ctx.stock_code, ctx.company.get("name", ""))
            bundle = {
                "stock_code": ctx.stock_code,
                "company_name": ctx.company.get("name", ""),
                "industry": profile.get("industry"),
                "sub_type": profile.get("sub_type"),
                "year": year,
                "form": form,
                "pdf_url": ctx.pdf_url,
                "cached": False,
                "rules_hash": rules_hash([]),
                "extractor_mode": extractor,
                "indicators": {},
                "missing": [],
                "unresolved": [],
                "section_cache_reuse": 0,
                "concurrency": 0,
            }

    bundle["csv_path"] = str(_resolve_csv_path(csv_path))
    bundle["skipped"] = skipped
    if missing_unknown:
        bundle.setdefault("missing", []).extend(missing_unknown)
    return bundle


# ── cross-target batch extraction ──────────────────────────────────


def extract_indicators_batch(
    targets: list,
    *,
    concurrency: Optional[int] = None,
    extract_concurrency: Optional[int] = None,
    csv_path: Optional[str] = "docs/indicators_position.csv",
    indicators: Optional[list[str]] = None,
    form: str = "年度报告",
    extractor_mode: str = "auto",
) -> dict:
    """Run many ``(ticker, year[, form])`` extractions concurrently.

    Each ``target`` is a ``(ticker, year)`` or ``(ticker, year, form)`` tuple,
    or a dict ``{"ticker", "year", "form"?}``. Extractions run concurrently up to
    a worker cap (``concurrency``, default ``EXTRACT_BATCH_CONCURRENCY`` or ``2``).
    A target that raises, or returns a bundle containing an ``error`` key, is
    recorded in ``failures`` and never aborts the batch.

    ``extract_concurrency`` is forwarded to each inner ``extract_indicators``
    call as the in-call cap (default ``EXTRACT_CONCURRENCY``/``4``). Because the
    batch pool and the in-call pool are independent, peak in-flight LLM calls is
    bounded by ``batch_concurrency × extract_concurrency`` — tune both against
    provider rate limits.

    When ``csv_path`` is given (default), each target is extracted via
    ``extract_indicators_by_position`` (CSV-driven); when ``csv_path is None``,
    via ``extract_indicators`` directly (e.g. multiyear python-only runs).

    Returns ``{"results": {target_key: bundle}, "failures": [...], "concurrency": <batch_cap>}``.
    ``target_key`` is ``"<ticker>_<year>"`` for the annual form, else
    ``"<ticker>_<year>_<form>"``. The result map is order-independent.
    """
    norm: list[tuple[str, int, str]] = []
    for t in targets:
        if isinstance(t, dict):
            ticker, year, f = t["ticker"], t["year"], t.get("form", form)
        elif isinstance(t, (list, tuple)):
            ticker, year = t[0], t[1]
            f = t[2] if len(t) > 2 else form
        else:
            raise TypeError(f"target must be tuple/dict, got {type(t).__name__}")
        norm.append((ticker, year, f))

    def _extract_one(target: tuple[str, int, str]):
        ticker, year, f = target
        key = f"{ticker}_{year}_{f}" if f != "年度报告" else f"{ticker}_{year}"
        try:
            if csv_path:
                bundle = extract_indicators_by_position(
                    ticker, year, csv_path=csv_path, extractor=extractor_mode,
                    indicators=indicators, form=f, concurrency=extract_concurrency,
                )
            else:
                bundle = extract_indicators(
                    ticker, year, indicators=indicators, form=f,
                    extractor_mode=extractor_mode, concurrency=extract_concurrency,
                )
        except Exception as e:  # noqa: BLE001 — batch isolation: never abort the batch
            return ("fail", key, f"{type(e).__name__}: {e}")
        if isinstance(bundle, dict) and "error" in bundle:
            return ("fail", key, str(bundle["error"]))
        return ("ok", key, bundle)

    batch_cap = _resolve_batch_concurrency(concurrency)
    outcomes = _map_merge(norm, _extract_one, batch_cap, label="batch")
    results_map: dict = {}
    failures: list = []
    for status, key, payload in outcomes:
        if status == "ok":
            results_map[key] = payload
        else:
            failures.append({"target": key, "error": payload})
    return {"results": results_map, "failures": failures, "concurrency": batch_cap}


def _effective_extractor(rule: dict, extractor_mode: str) -> str:
    """Return the effective extractor for a report rule.

    With python extractors removed, all report rules use "llm".
    In ``python`` mode, returns "llm" (which the caller treats as skipped).
    """
    return "llm"


def _build_dataframe(
    results: dict[str, dict], stock_code: str, company_name: str, year: int,
) -> list[dict]:
    """Convert ``{name: {value, unit, ...}}`` → flat list of dicts (pandas-friendly)."""
    rows: list[dict] = []
    for name, rec in results.items():
        rows.append({
            "stock_code": stock_code,
            "company_name": company_name,
            "year": year,
            "indicator": name,
            "value": rec.get("value"),
            "unit": rec.get("unit", ""),
            "note": rec.get("note", ""),
        })
    return rows


# ── methodology renderer ──────────────────────────────────────────


def render_methodology() -> str:
    """Render the rule set as a markdown methodology document."""
    rules = _rules()
    lines: list[str] = []
    lines.append("# Indicators — source & process methodology")
    lines.append("")
    lines.append(
        "Generated from `indicator_rules.json`. Each indicator lists its source type, "
        "the concrete annual-report section selector chain (or akshare field / formula), "
        "the extractor, applicability, and a process note. `indicators.md` remains the "
        "human-authored catalog; this document is the machine-kept companion."
    )
    lines.append("")
    lines.append(f"_Total rules: {len(rules)} · rules_hash: {rules_hash(rules)}_")
    lines.append("")

    # group by module then subgroup
    by_module: dict[str, dict[str, list[dict]]] = {}
    for r in rules:
        by_module.setdefault(r.get("module", ""), {}).setdefault(
            r.get("subgroup", ""), []
        ).append(r)

    for module, subs in by_module.items():
        lines.append(f"## {module}")
        lines.append("")
        for sg, items in subs.items():
            lines.append(f"### {sg}")
            lines.append("")
            lines.append("| Indicator | source_type | source | extractor | applies_to | unit | note |")
            lines.append("|---|---|---|---|---|---|---|")
            for r in items:
                src = r.get("source") or {}
                if r["source_type"] == "akshare":
                    src_str = f"akshare `{src.get('statement')}.{src.get('field')}`"
                elif r["source_type"] == "report":
                    chain = " → ".join(
                        (s.get("section", "") + ("*" if s.get("company") else ""))
                        for s in src.get("selectors", [])
                    )
                    src_str = f"report: {chain}"
                elif r["source_type"] == "external":
                    src_str = "external (realtime/market — not in report PDF)"
                else:
                    src_str = f"computed: `{src.get('formula')}`"
                ap = r.get("applies_to") or {}
                ap_str = []
                if ap.get("industry") and ap["industry"] != "*":
                    ap_str.append(ap["industry"])
                if ap.get("sub_types") and ap["sub_types"] != ["*"]:
                    ap_str.append("/".join(ap["sub_types"]))
                if ap.get("companies") and ap["companies"] != ["*"]:
                    ap_str.append("companies:" + ",".join(ap["companies"]))
                if ap.get("exclude_companies"):
                    ap_str.append("exclude:" + ",".join(ap["exclude_companies"]))
                ap_text = " ".join(ap_str) or "*"
                note = (r.get("note") or "").replace("|", "/").replace("\n", " ")
                lines.append(
                    f"| {r['name']} | {r['source_type']} | {src_str} | "
                    f"{r.get('extractor','')} | {ap_text} | {r.get('unit','')} | {note} |"
                )
            lines.append("")

    lines.append("## Adding a new rule")
    lines.append("")
    lines.append(
        "Append an entry to `indicator_rules.json`. Required fields: `name`, `module`, "
        "`subgroup`, `applies_to`, `source_type`, and the matching `source` spec "
        "(`{statement, field}` for akshare, `{selectors:[...], extractor}` for report, "
        "`{formula, inputs}` for computed). Optional: `aliases`, `unit`, `period_type`, "
        "`direction`, `note`. No Python change is needed — `list_indicators`, "
        "`get_indicator`, `extract_indicators`, and the script all read the JSON at call "
        "time. Then re-run `python indicators_client.py --render-methodology > "
        "docs/indicators-methodology.md` to refresh this document."
    )
    lines.append("")
    lines.append("## Adding a new extractor")
    lines.append("")
    lines.append(
        "1. Write a function `(section_text, rule, period) -> {value, unit, note}` in "
        "`indicators_extractors.py`.\n"
        "2. Call `register('your_name', your_fn)` at import time.\n"
        "3. Set `\"extractor\": \"python:your_name\"` on the rule(s) that should use it.\n"
        "\n"
        "The engine dispatches by name; no engine change is required. Python extractors "
        "receive the already-sliced, cache-backed section text and never touch the PDF "
        "themselves. Use `--extractor python` on the script to run LLM-free where possible."
    )
    lines.append("")
    lines.append("## LLM section cache")
    lines.append("")
    lines.append(
        "The LLM extractor persists the raw `{records:[...]}` response to "
        "`<CNREPORT_CACHE_DIR>/llm_sections/<key>.json`, keyed by "
        "`(pdf_url, section_key, period, rules_hash)`. After a section has been "
        "extracted once, subsequent runs — including single-indicator lookups via "
        "`get_indicator` and re-runs with different indicator subsets — reuse the "
        "cached records and only re-query the LLM for indicators not yet cached.\n"
        "\n"
        "The bundle exposes a `section_cache_reuse: <int>` field that counts records "
        "served from the section cache in that run (distinct from `cached: true`, "
        "which indicates a full bundle hit). The cache is on by default; set "
        "`LLM_SECTION_CACHE=off` to disable it at runtime. CNINFO reports are "
        "immutable, so the cache is safe to leave on indefinitely."
    )
    lines.append("")
    lines.append("## Concurrency")
    lines.append("")
    lines.append(
        "`extract_indicators` runs its per-section LLM calls and `akshare` calls "
        "concurrently up to a worker cap (sections are independent: disjoint "
        "indicator names, distinct section-cache keys), so a cold first pass takes "
        "`~1 × LLM_latency` instead of `N_sections × latency`. The cap is set by "
        "the `concurrency` parameter, falling back to the `EXTRACT_CONCURRENCY` "
        "env var (default `4`); `concurrency=1` runs inline with no thread pool and "
        "reproduces the prior sequential behavior and call order exactly. The "
        "bundle reports the cap used via a `concurrency: <int>` field.\n"
        "\n"
        "`extract_indicators_batch(targets, ...)` runs many `(ticker, year[, form])` "
        "extractions concurrently (powering `scripts/extract_indicators_by_position.py "
        "--from-file` and `scripts/extract_indicators_multiyear.py`). Its batch cap "
        "(`concurrency`, default `EXTRACT_BATCH_CONCURRENCY`/`2`) is independent of "
        "the in-call cap (`extract_concurrency`, default `EXTRACT_CONCURRENCY`/`4`), "
        "so peak in-flight LLM calls is bounded by their product (`2 × 4 = 8` by "
        "default). Lower either if the provider rate-limits; set either to `1` for "
        "strictly sequential runs. The thread pool relies on the existing concurrency "
        "boundaries — `call_llm_json` issues a fresh `httpx.post` per call, "
        "`report_cache`/`llm_section_cache` write atomically to distinct keys, and "
        "`_RULES_CACHE` is read-only after first load — so no new locking is needed."
    )
    lines.append("")
    return "\n".join(lines)


def render_coverage() -> str:
    """Render a coverage summary of the rule set as markdown.

    Companion to ``render_methodology``: a concise summary (counts by module and
    source_type, fetchable vs external) rather than a per-rule table. The full
    per-rule source/process detail lives in ``docs/indicators-methodology.md``.
    """
    rules = _rules()
    total = len(rules)
    by_module: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for r in rules:
        by_module[r.get("module", "")] = by_module.get(r.get("module", ""), 0) + 1
        st = r.get("source_type", "")
        by_source[st] = by_source.get(st, 0) + 1
    fetchable = sum(v for k, v in by_source.items() if k in ("akshare", "report", "computed"))
    external = by_source.get("external", 0)

    lines: list[str] = []
    lines.append("# Indicators coverage — implemented rule set")
    lines.append("")
    lines.append(
        "Summary of `indicator_rules.json` (the implemented rule set). Banking rules are "
        "hand-authored; the broader set is migrated from `docs/indicators_position.csv` "
        "by `scripts/migrate_indicators_csv.py`. Per-rule source/process detail lives in "
        "`docs/indicators-methodology.md`."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total rules: **{total}**")
    lines.append(f"- **Fetchable** (report / akshare / computed): **{fetchable}**")
    lines.append(f"- **External** (realtime/market — not in report PDF, listed in `skipped`): **{external}**")
    lines.append(f"- rules_hash: `{rules_hash(rules)}`")
    lines.append("")
    lines.append("## By source_type")
    lines.append("")
    lines.append("| source_type | count | meaning |")
    lines.append("|---|---|---|")
    meaning = {
        "akshare": "read from akshare structured statements",
        "report": "extracted from the annual-report PDF section",
        "computed": "derived locally from base values via a formula",
        "external": "realtime/market data — not in the report PDF",
    }
    for st in ("akshare", "report", "computed", "external"):
        lines.append(f"| {st} | {by_source.get(st, 0)} | {meaning.get(st, '')} |")
    lines.append("")
    lines.append("## By module")
    lines.append("")
    lines.append("| module | rules |")
    lines.append("|---|---|")
    for m in sorted(by_module):
        lines.append(f"| {m} | {by_module[m]} |")
    lines.append("")
    lines.append("## Refresh")
    lines.append("")
    lines.append(
        "Regenerate after editing the CSV / rules:\n\n"
        "```\n"
        "python scripts/migrate_indicators_csv.py          # sync CSV → indicator_rules.json\n"
        "python indicators_client.py --render-methodology > docs/indicators-methodology.md\n"
        "python indicators_client.py --render-coverage > docs/indicators-coverage.md\n"
        "```"
    )
    lines.append("")
    return "\n".join(lines)


def write_coverage_csv(path) -> None:
    """Write the flat coverage CSV (one row per rule) to ``path``."""
    import csv as _csv

    rules = _rules()
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["module", "subgroup", "indicator", "fetchable", "source_type", "extractor", "method"])
        for r in rules:
            st = r.get("source_type", "")
            src = r.get("source") or {}
            if st == "akshare":
                method = f"akshare ({src.get('statement')}.{src.get('field')})"
                fetchable = "yes"
            elif st == "report":
                chain = " → ".join(s.get("section", "") for s in src.get("selectors", []))
                method = f"report PDF ({r.get('extractor', 'llm')}): {chain}"
                fetchable = "yes"
            elif st == "computed":
                method = f"computed ({src.get('formula', '')})"
                fetchable = "yes"
            elif st == "external":
                method = ""
                fetchable = "no"
            else:
                method = ""
                fetchable = "no"
            w.writerow([r.get("module", ""), r.get("subgroup", ""), r.get("name", ""),
                        fetchable, st, r.get("extractor", ""), method])


def _main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Indicator rules engine CLI")
    p.add_argument("--render-methodology", action="store_true",
                   help="Print the methodology markdown to stdout")
    p.add_argument("--render-coverage", action="store_true",
                   help="Print the coverage summary markdown to stdout")
    p.add_argument("--write-coverage-csv", metavar="PATH",
                   help="Write the flat coverage CSV (one row per rule) to PATH")
    args = p.parse_args()
    if args.render_methodology:
        print(render_methodology())
    if args.render_coverage:
        print(render_coverage())
    if args.write_coverage_csv:
        write_coverage_csv(args.write_coverage_csv)


if __name__ == "__main__":
    _main()
