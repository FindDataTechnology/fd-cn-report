"""Named extractor registry for script-rule extraction.

Re-introduces the ``register(name, fn)`` / ``get(name)`` registry pattern
(the deleted ``indicators_extractors.py``), now resolved from DB-stored
``script_rules.extract_rule``. Each extractor is a pure function::

    (section_text: str, rule: dict, period: str) -> {"value", "unit", "note"}

Built-in extractors: ``regex_amount``, ``percent_value``, ``table_row``,
``headcount``. The registry is constrained (only registered callables run) —
LLM-generated ``extract_rule`` values that do not match a registered name
return ``{value: None}`` rather than executing arbitrary code.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

Extractor = Callable[[str, dict, str], dict[str, Any]]

_REGISTRY: dict[str, Extractor] = {}


def register(name: str, fn: Optional[Extractor] = None):
    """Register an extractor under ``name``.

    Usable both as a direct call (``register("x", fn)``) and as a decorator
    factory (``@register("x")``). Overwrites if already present.
    """
    if fn is not None:
        _REGISTRY[name] = fn
        return fn

    def _decorator(f: Extractor) -> Extractor:
        _REGISTRY[name] = f
        return f

    return _decorator


def get(name: Optional[str]) -> Optional[Extractor]:
    """Return the extractor registered under ``name``, or ``None``."""
    if not name:
        return None
    return _REGISTRY.get(name)


def names() -> list[str]:
    """Return the sorted names of all registered extractors."""
    return sorted(_REGISTRY)


# ── shared regexes ────────────────────────────────────────────────

_NUM_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")
_PCT_RE = re.compile(r"-?\d+(?:\.\d+)?\s*%")
_HEADCOUNT_RE = re.compile(r"(\d[\d,]*)\s*(?:人|名)")

# Accountants write negatives as ``(1,234.56)`` / ``（1,234.56）`` and, in CJK
# PDFs, with a full-width minus ``－1,234.56``. The regexes above only know the
# ASCII hyphen, so those forms used to parse as *positive* amounts. Sign
# normalisation happens once, before tokenising, so every extractor inherits it.

# A dash in sign position only (preceded by non-word text, followed by digits) —
# so year ranges like ``2023—2025`` are left alone.
_SIGN_DASH_RE = re.compile(r"(?<![\d\w.,])[－−‐‑‒–—―](?=\s*\d)")
_PAREN_RE = re.compile(r"[（(]\s*([^()（）\n]{1,40}?)\s*[）)]")
_PAREN_AMOUNT_RE = re.compile(r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+)\s*%?")


def _paren_negative(m: re.Match) -> str:
    """Rewrite a parenthesised amount as a leading-hyphen negative."""
    inner = m.group(1).strip()
    if not _PAREN_AMOUNT_RE.fullmatch(inner):
        return m.group(0)  # not an amount, e.g. （以下简称"公司"）
    if inner.isdigit() and not re.match(r"$|[\s，,、;；。]", m.string[m.end():]):
        return m.group(0)  # a list marker, e.g. （1）营业收入
    return "-" + inner


def _normalize_numbers(text: str) -> str:
    """Normalise accounting sign conventions before the ASCII regexes run.

    Full-width / typographic dashes become ``-`` when they are in sign
    position, and a number wrapped in (full-width) parentheses — the standard
    accounting negative — gains a leading ``-``. Positive values are untouched.
    """
    if not text:
        return text
    return _PAREN_RE.sub(_paren_negative, _SIGN_DASH_RE.sub("-", text))


def _to_float(token: str) -> Optional[float]:
    try:
        return float(token.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _find_numbers(text: str) -> list[str]:
    """All numeric tokens in *text*, after normalising accounting signs."""
    return _NUM_RE.findall(_normalize_numbers(text))


def _find_percent(text: str) -> Optional[re.Match]:
    """First percentage in *text*, after normalising accounting signs."""
    return _PCT_RE.search(_normalize_numbers(text))


def _is_note_ref(token: str) -> bool:
    """Return True if *token* looks like a note reference or year, not a data value."""
    if not token.isdigit():
        return False
    n = int(token)
    return n < 100 or 1000 <= n <= 2099


def _skip_note_refs(tokens: list[str]) -> list[str]:
    """Return *tokens* minus note-ref / year tokens, or empty list if all are refs."""
    return [t for t in tokens if not _is_note_ref(t)]


def _indicator_name(rule: dict) -> str:
    return rule.get("name") or rule.get("indicator") or ""


def _line_matches_name(line: str, name: str) -> bool:
    """Check if *name* matches *line* in either direction.

    Returns True when *name* is a substring of *line* (e.g. "存放中央银行款项"
    in "现金及存放中央银行款项"), OR when the line's leading token (the table
    label) is a substring of *name* (e.g. line "存放中央银行款项" matches
    indicator "现金及存放中央银行款项"). This handles real-world PDF tables
    where the report uses a shorter label than the canonical indicator name.

    Normalizes common character variants (及↔和, 与↔和, etc.) before matching.
    """
    if not name or not line:
        return False
    name_norm = _normalize_text(name)
    line_norm = _normalize_text(line)
    if name_norm in line_norm:
        return True
    # line's leading non-numeric token as the table label
    label = line_norm.strip()
    if not label:
        return False
    m = re.match(r"^([^\d]+?)\s*\d", label)
    if m:
        label = m.group(1).strip()
    if not label or len(label) < 2:
        return False
    return label in name_norm


def _next_data_lines(lines: list[str], start_idx: int, max_lines: int = 5) -> list[str]:
    """Return the next *max_lines* non-empty lines after *start_idx*.

    Used by extractors to look beyond the label line for data values
    (common in PDF tables where label and value are on separate lines).
    """
    result: list[str] = []
    for i in range(start_idx + 1, min(start_idx + 1 + max_lines, len(lines))):
        line = lines[i].strip()
        if not line:
            continue
        result.append(line)
    return result


def _first_valid_number(texts: list[str]) -> Optional[float]:
    """Return the first numeric value from a list of text strings, skipping note refs."""
    for t in texts:
        nums = _find_numbers(t)
        if not nums:
            continue
        candidates = _skip_note_refs(nums)
        if candidates and (val := _to_float(candidates[0])) is not None:
            return val
    return None


# Normalize common character variants between indicator names and report text.
_NORMALIZE_TABLE = str.maketrans({
    "及": "和",
    "與": "和",
    "爲": "为",
    "於": "于",
    "餘": "余",
    "後": "后",
    "前": "前",
    "裏": "里",
    "內": "内",
    "賬": "账",
    "併": "并",
    "減": "减",
    "項": "项",
    "報": "报",
    "稱": "称",
    "審": "审",
    "計": "计",
    "幣": "币",
    "權": "权",
    "準": "准",
    "備": "备",
    "類": "类",
    "險": "险",
    "產": "产",
    "業": "业",
    "務": "务",
    "門": "门",
    "關": "关",
    "係": "系",
    "聯": "联",
    "營": "营",
    "監": "监",
    "總": "总",
    "額": "额",
    "費": "费",
    "價": "价",
    "構": "构",
    "機": "机",
    "級": "级",
    "變": "变",
    "動": "动",
    "導": "导",
    "致": "致",
    "組": "组",
    "織": "织",
    "網": "网",
    "絡": "络",
    "評": "评",
    "貸": "贷",
    "款": "款",
    "結": "结",
})


def _normalize_text(s: str) -> str:
    """Normalize common simplified/traditional and character variants."""
    return s.translate(_NORMALIZE_TABLE)


# ── built-in extractors ───────────────────────────────────────────


@register("regex_amount")
def regex_amount(section_text: str, rule: dict, period: str) -> dict:
    """First numeric amount on or after a line containing the indicator name.

    When the label line has no numbers, looks at the next few lines (common
    in PDF tables where label and value are on separate lines). Skips small
    integers (< 100) that are likely note-reference numbers when larger
    comma-formatted numbers exist on the same line.
    """
    name = _indicator_name(rule)
    name_found = False
    lines = section_text.splitlines()
    for idx, line in enumerate(lines):
        if name and _line_matches_name(line, name):
            name_found = True
            # Try current line first
            nums = _find_numbers(line)
            if nums:
                candidates = _skip_note_refs(nums)
                if candidates and (val := _to_float(candidates[0])) is not None:
                    return {"value": val, "unit": rule.get("unit", ""), "note": "script:regex_amount"}
            # Try next lines (label and value on separate lines)
            val = _first_valid_number(_next_data_lines(lines, idx))
            if val is not None:
                return {"value": val, "unit": rule.get("unit", ""), "note": "script:regex_amount"}
    if not name_found:
        return {"value": None, "unit": rule.get("unit", ""), "note": "script:regex_amount:name_not_found"}
    return {
        "value": None,
        "unit": rule.get("unit", ""),
        "note": "script:regex_amount:not_found",
    }


@register("percent_value")
def percent_value(section_text: str, rule: dict, period: str) -> dict:
    """First percentage on or after a line containing the indicator name."""
    name = _indicator_name(rule)
    name_found = False
    lines = section_text.splitlines()
    for idx, line in enumerate(lines):
        if name and _line_matches_name(line, name):
            name_found = True
            m = _find_percent(line)
            if m:
                val = _to_float(m.group(0).replace("%", "").strip())
                return {"value": val, "unit": "%", "note": "script:percent_value"}
            # Try next lines
            for nl in _next_data_lines(lines, idx):
                m = _find_percent(nl)
                if m:
                    val = _to_float(m.group(0).replace("%", "").strip())
                    return {"value": val, "unit": "%", "note": "script:percent_value"}
    if not name_found:
        return {"value": None, "unit": rule.get("unit", "%"), "note": "script:percent_value:name_not_found"}
    return {"value": None, "unit": rule.get("unit", "%"), "note": "script:percent_value:not_found"}


@register("table_row")
def table_row(section_text: str, rule: dict, period: str) -> dict:
    """First data value on or after a table row whose label matches the indicator.

    Skips small integers (< 100) that are likely note-reference numbers
    so the first actual data column is returned.
    """
    name = _indicator_name(rule)
    if not name:
        return {"value": None, "unit": rule.get("unit", ""), "note": "script:table_row:no_name"}
    lines = section_text.splitlines()
    for idx, line in enumerate(lines):
        if name and _line_matches_name(line, name):
            nums = _find_numbers(line)
            if nums:
                candidates = _skip_note_refs(nums)
                if candidates and (val := _to_float(candidates[0])) is not None:
                    return {"value": val, "unit": rule.get("unit", ""), "note": "script:table_row"}
            # Try next lines
            val = _first_valid_number(_next_data_lines(lines, idx))
            if val is not None:
                return {"value": val, "unit": rule.get("unit", ""), "note": "script:table_row"}
    return {"value": None, "unit": rule.get("unit", ""), "note": "script:table_row:not_found"}


@register("headcount")
def headcount(section_text: str, rule: dict, period: str) -> dict:
    """First ``N 人`` / ``N 名`` headcount in the section."""
    m = _HEADCOUNT_RE.search(section_text)
    if m:
        val = _to_float(m.group(1))
        return {"value": int(val) if val is not None else None, "unit": "人", "note": "script:headcount"}
    return {"value": None, "unit": "人", "note": "script:headcount:not_found"}


@register("dividend_per_share")
def dividend_per_share(section_text: str, rule: dict, period: str) -> dict:
    """Extract 每股分红 / 每股股利 / 每股派息 (dividend per share).

    Looks for lines containing key phrases and extracts the first numeric
    amount found on that line (元/股). Also looks for patterns like
    "每10股派发现金红利X元" and converts to per-share value.
    """
    keywords = ["每股分红", "每股股利", "每股派息", "每股现金股利", "每股现金分红"]
    lines = section_text.splitlines()
    for idx, line in enumerate(lines):
        if any(k in line for k in keywords):
            nums = _find_numbers(line)
            if nums:
                candidates = _skip_note_refs(nums)
                if candidates and (val := _to_float(candidates[0])) is not None:
                    return {"value": val, "unit": "元/股", "note": "script:dividend_per_share"}
            val = _first_valid_number(_next_data_lines(lines, idx))
            if val is not None:
                return {"value": val, "unit": "元/股", "note": "script:dividend_per_share"}
    # "每10股(派发现金股利X元)" → X/10
    per10 = re.findall(r"每10\s*股[^。]*?(\d+\.?\d*)\s*元", section_text)
    if per10:
        return {"value": float(per10[-1]) / 10, "unit": "元/股", "note": "script:dividend_per_share:per10"}
    for kw in keywords:
        idx = section_text.find(kw)
        if idx >= 0:
            context = section_text[idx:idx + 200]
            nums = _find_numbers(context)
            if not nums:
                continue
            candidates = _skip_note_refs(nums)
            if candidates and (val := _to_float(candidates[0])) is not None:
                return {"value": val, "unit": "元/股", "note": "script:dividend_per_share:context"}
    return {"value": None, "unit": "元/股", "note": "script:dividend_per_share:not_found"}
