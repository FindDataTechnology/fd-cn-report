"""Pure helpers for fd-cn-report: fetch, outline parse, section select,
LLM extraction, Elasticsearch store/search. No FastMCP here — server.py
registers the @app.tool wrappers that call these.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Optional

# ponytail: fetch via httpx + pypdf directly; scrapling delegation deferred
# for JS/anti-bot pages (rare for static cninfo/sse annual-report downloads).

# ── outline parsing ──────────────────────────────────────────────

# Common Chinese annual-report heading patterns: 第三节, 第三章, 一、, （一）, 1.
_HEADING_RE = re.compile(
    r"^\s*("
    r"第[一二三四五六七八九十百零〇\d]+[章节部分编篇]"
    r"|[\(（][一二三四五六七八九十百\d]+[\)）]"
    r"|[一二三四五六七八九十百]+、"
    r"|\d+[\.、]"
    r"|(?:Part|Section|Chapter|CHAPTER|SECTION|PART)\s+[IVXLCDMivxlcdm\d+]"
    r")\s*(.+?)\s*\.{3,}?\s*\d*\s*$"  # optional dot-leader + page no
)
# looser fallback: heading token alone on a line
_HEADING_LOOSE_RE = re.compile(
    r"^\s*(第[一二三四五六七八九十百零〇\d]+[章节部分编篇]|[一二三四五六七八九十百]+、|\d+[\.、]|(?:Part|Section|Chapter)\s+[IVXLCDMivxlcdm\d]+)\s*(\S.*?)\s*$"
)


def strip_html(html: str) -> str:
    """Crude HTML → text: drop tags/scripts, collapse whitespace."""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
    html = re.sub(r"(?s)<[^>]+>", "", html)
    # entities ponytail: handle the few that matter
    html = html.replace("&nbsp;", " ").replace("&amp;", "&")
    html = html.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"[ \t]+", " ", html).strip()


def extract_pdf_text(data: bytes) -> str:
    """Extract text from a text-layer PDF.

    Tries pymupdf first (better CJK font handling), falls back to pypdf.
    """
    import io

    try:
        import fitz
        doc = fitz.Document(stream=data, filetype="pdf")
        parts = []
        for i in range(len(doc)):
            try:
                parts.append(doc[i].get_text() or "")
            except Exception:
                continue
        return "\n".join(parts)
    except ImportError:
        pass

    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def get_pypdf_page_offsets(data: bytes) -> list[int]:
    """Return character offsets ``[0, p1_end, p2_end, ..., total]`` for each page
    in the full text produced by ``extract_pdf_text``. The Nth entry is the
    ``(N-1)``th page's start offset (0-based); the last entry is ``len(text)``.
    1-based page N maps to slice ``offsets[N-1 : N+1]``.
    """
    import io

    try:
        import fitz
        doc = fitz.Document(stream=data, filetype="pdf")
        offsets = [0]
        for i in range(len(doc)):
            try:
                text = doc[i].get_text() or ""
            except Exception:
                text = ""
            offsets.append(offsets[-1] + len(text) + 1)
        total = offsets[-1] - 1 if offsets[-1] > 0 else 0
        offsets[-1] = total
        return offsets
    except ImportError:
        pass

    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    offsets = [0]
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        offsets.append(offsets[-1] + len(text) + 1)  # +1 for the \n separator
    # last entry = len(text) stripping the trailing \n we won't have
    total = offsets[-1] - 1 if offsets[-1] > 0 else 0
    offsets[-1] = total
    return offsets


def fetch_source(source: str, fetcher: str = "uv") -> str:
    """Fetch a report as text. URL via httpx (html/pdf), local path read directly.

    fetcher is accepted for forward-compat; v1 ignores it (httpx/pypdf only).
    """
    return fetch_source_with_bytes(source, fetcher)[0]


def fetch_source_with_bytes(source: str, fetcher: str = "uv") -> tuple[str, Optional[bytes]]:
    """Fetch a report as ``(text, raw_bytes)``.

    For URL sources, ``raw_bytes`` is the downloaded response body so callers
    (the report cache) can persist the original PDF. For local-path sources,
    ``raw_bytes`` is ``None`` — the file is already on disk and need not be
    re-cached.
    """
    if _looks_like_url(source):
        import httpx

        resp = httpx.get(source, follow_redirects=True, timeout=60.0)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").lower()
        if "pdf" in ctype or source.lower().endswith(".pdf"):
            return extract_pdf_text(resp.content), resp.content
        if "html" in ctype:
            return strip_html(resp.text), resp.content
        return resp.text, resp.content
    # local path
    path = os.path.abspath(source)
    if not os.path.exists(path):
        raise FileNotFoundError(f"source not found and not a URL: {source}")
    if path.lower().endswith(".pdf"):
        with open(path, "rb") as fh:
            return extract_pdf_text(fh.read()), None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read(), None


def _looks_like_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def parse_outline(text: str) -> list[dict]:
    """Parse 目录/bookmarks into a flat list of {level, title, ordinal}.

    level: 1 for 第X章/节, 2 for 一、, 3 for （一）/1.
    """
    entries: list[dict] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _HEADING_RE.match(line) or _HEADING_LOOSE_RE.match(line)
        if not m:
            continue
        token, title = m.group(1), m.group(2)
        title = title.strip().strip(".").strip()
        if not title or len(title) > 80:
            continue
        level = _heading_level(token)
        key = f"{token}{title}"
        if key in seen:
            continue
        seen.add(key)
        entries.append({"level": level, "title": f"{token} {title}".strip(), "ordinal": len(entries) + 1})
    return entries


def _heading_level(token: str) -> int:
    if re.match(r"第[一二三四五六七八九十百零〇\d]+[章节部分编篇]", token):
        return 1
    if re.match(r"[一二三四五六七八九十百]+、", token):
        return 2
    return 3  # （一）/1.


def parse_pymupdf_outline(data: bytes) -> list[dict]:
    """Parse PDF bookmarks via pymupdf ``get_toc()``.

    Returns a list of ``{level, title, page, source: "pymupdf"}`` entries
    where ``page`` is the 1-based page number. Returns empty list when
    pymupdf is unavailable or the PDF has no bookmarks.
    """
    try:
        import fitz
    except ImportError:
        return []
    try:
        doc = fitz.Document(stream=data, filetype="pdf")
        toc = doc.get_toc()
        doc.close()
    except Exception:
        return []
    entries = []
    seen: set[str] = set()
    for level, title, page in toc:
        title = title.strip()
        if not title or title in seen:
            continue
        seen.add(title)
        entries.append({"level": level, "title": title, "page": page, "source": "pymupdf"})
    return entries


def merge_outlines(pymupdf_entries: list[dict], regex_entries: list[dict]) -> list[dict]:
    """Merge pymupdf bookmarks with heading-regex outline entries.

    Deduplicates by normalized title (pymupdf entries win priority).
    Regex-only entries (no page number) are appended after the merged set,
    preserving their ordinal sequence.
    """
    from_normalized = {}
    for e in regex_entries:
        key = _normalize_section_title(e["title"])
        from_normalized[key] = e
    merged: list[dict] = []
    seen_keys: set[str] = set()
    ordinal = 0
    for e in pymupdf_entries:
        key = _normalize_section_title(e["title"])
        seen_keys.add(key)
        ordinal += 1
        merged.append({**e, "ordinal": ordinal})
    for e in regex_entries:
        key = _normalize_section_title(e["title"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        ordinal += 1
        merged.append({**e, "ordinal": ordinal})
    return merged


def page_to_char_offset(page: int, offsets: list[int]) -> int:
    """Convert a 1-based page number to a character offset in the full text.

    Returns the start offset of the page when ``page`` is within range,
    or ``0`` when not (safe fallback).
    """
    if page < 1 or page >= len(offsets):
        return 0
    return offsets[page - 1]


def resolve_selector(outline: list[dict], selector: str) -> Optional[dict]:
    """Resolve a selector (ordinal int | exact title | regex | normalized substring) to an outline entry.

    Matching passes, in order: ordinal (1-based), exact title, normalized
    leading-keyword substring, regex. The normalized substring pass lets
    descriptive selectors like ``"资产负债表 — 一、资产"`` or
    ``"管理层讨论与分析 — 财务概要"`` (sourced from indicators_position.csv)
    match real TOC titles like ``"合并资产负债表"`` / ``"管理层讨论与分析"``:
    the leading keyword (text before the first em-dash) is matched as a
    substring against the normalized outline title.
    """
    # ordinal (1-based)
    if isinstance(selector, int) or (isinstance(selector, str) and selector.isdigit()):
        idx = int(selector)
        for e in outline:
            if e["ordinal"] == idx:
                return e
        return None
    # exact title
    for e in outline:
        if e["title"] == selector:
            return e
    # normalized leading-keyword: exact-ish match after stripping ordinals/dashes.
    # Always falls back to substring match so "资产负债表" matches "合并资产负债表"
    # and "讨论与分析" matches "管理层讨论与分析".
    sel_key = _normalize_section_title(_leading_keyword(selector))
    if sel_key and len(sel_key) >= 2:
        for e in outline:
            norm_title = _normalize_section_title(e["title"])
            if sel_key == norm_title:
                return e
        # substring match as fallback (tolerant for CSV selectors)
        for e in outline:
            norm_title = _normalize_section_title(e["title"])
            if sel_key in norm_title:
                return e
    # Also try the tail keyword (after em-dash) when leading keyword fails.
    # E.g. "人力资源管理 — 员工情况" → tail "员工情况" matches "5. 14 员工情况".
    tail = _leading_keyword_tail(selector)
    if tail and tail != sel_key and len(tail) >= 2:
        for e in outline:
            norm_title = _normalize_section_title(e["title"])
            if tail == norm_title:
                return e
        for e in outline:
            norm_title = _normalize_section_title(e["title"])
            if tail in norm_title:
                return e
    # regex (only when the selector is an actual regex pattern, not plain text)
    if re.search(r"[.+*?^$()\[\]{}|\\]", selector):
        try:
            pat = re.compile(selector)
        except re.error:
            return None
        for e in outline:
            if pat.search(e["title"]):
                return e
    return None


# ordinals a section title may carry: "一、", "（一）", "1、", "第一章", "第二节" etc.
_SECTION_ORDINAL_RE = re.compile(
    r"[一二三四五六七八九十百]+、|（[一二三四五六七八九十百]+）|\d+、"
    r"|第[一二三四五六七八九十百]+[章节部分]"
)
# em-dashes / hyphens used as section delimiters in the CSV (e.g. "资产负债表 — 一、资产").
_SECTION_DASH_RE = re.compile(r"[—–\-]")


def _leading_keyword(selector: str) -> str:
    """Return the text before the first em-dash/hyphen (the section keyword)."""
    s = selector or ""
    for sep in ("—", "–", "-"):
        if sep in s:
            return s.split(sep, 1)[0].strip()
    return s.strip()


def _leading_keyword_tail(selector: str) -> str:
    """Return the text after the last em-dash/hyphen, or empty string."""
    s = selector or ""
    for sep in ("—", "–", "-"):
        if sep in s:
            return s.rsplit(sep, 1)[-1].strip()
    return ""


def _normalize_section_title(s: str) -> str:
    """Strip ordinals, em-dashes, slashes, and whitespace for tolerant matching."""
    s = _SECTION_ORDINAL_RE.sub("", s or "")
    s = _SECTION_DASH_RE.sub("", s)
    return re.sub(r"[\s／/、，,。.：:（）()]+", "", s)


# ── three major financial statements (三大报表) ─────────────────────
# Each statement tried consolidated-first, then un-prefixed. Matched via
# resolve_selector (regex search), so token-prefixed TOC titles like
# "1、 合并资产负债表" resolve correctly. Parent-only titles (母公司…)
# never contain the consolidated substring, so they're skipped on the first
# pass and only matched as a last-resort fallback on the un-prefixed pass.
STATEMENT_MATCHERS: dict[str, list[str]] = {
    "income_statement": ["合并及公司利润表", "合并利润表", "利润表", "合并及公司利润表–按中国会计准则编制", "綜合收益表", "Statement of Profit or Loss"],
    "balance_sheet": ["合并及公司资产负债表", "合并资产负债表", "资产负债表", "合并及公司资产负债表–按中国会计准则编制", "財務狀況表", "綜合財務狀況表", "Statement of Financial Position"],
    "cashflow": ["合并及公司现金流量表", "合并现金流量表", "现金流量表", "合并及公司现金流量表–按中国会计准则编制", "綜合現金流量表", "Consolidated Statement of Cash Flows"],
}

# Financial statement table titles that may be absent from both PDF bookmarks
# and the heading-regex outline. The system scans for these in the body text
# and injects them as virtual outline entries with page-level positions.
# Bank-specific variants (银行资产负债表 etc.) are checked first.
STATEMENT_TITLES: dict[str, list[str]] = {
    "balance_sheet": [
        "合并及公司资产负债表",
        "银行资产负债表",
        "银行资产负债表（未经审计）",
        "合并资产负债表",
        "资产负债表",
        "財務狀況表",
        "綜合財務狀況表",
        "Statement of Financial Position",
    ],
    "income_statement": [
        "合并及公司利润表",
        "银行利润表",
        "银行利润表（未经审计）",
        "合并利润表",
        "利润表",
        "綜合收益表",
        "Statement of Profit or Loss",
    ],
    "cashflow": [
        "合并及公司现金流量表",
        "银行现金流量表",
        "银行现金流量表（未经审计）",
        "合并现金流量表",
        "现金流量表",
        "綜合現金流量表",
        "Consolidated Statement of Cash Flows",
    ],
    "equity": [
        "合并及公司股东权益变动表",
        "合并股东权益变动表",
        "股东权益变动表",
    ],
}


def detect_statement_titles(text: str, page_offsets: list[int], page_count: int) -> list[dict]:
    """Scan body text for financial statement table titles not in the outline.

    Returns a list of ``{level: 2, title, page, source: "statement_detection",
    module: <key>}`` entries, one per detected title.
    """
    detected: list[dict] = []
    seen_titles: set[str] = set()
    _TOC_LINE_RE = re.compile(r"^\s*(?:\.{2,}(?:\s*\d+)?|\d+(?:\s*[-–]\s*\d+)*)\s*$")
    for module, titles in STATEMENT_TITLES.items():
        for title in titles:
            if title in seen_titles:
                continue
            # find first body occurrence (skip TOC lines, skips references inside text)
            idx = 0
            found_pos = -1
            while True:
                pos = text.find(title, idx)
                if pos == -1:
                    break
                line_end = text.find("\n", pos)
                if line_end == -1:
                    line_end = len(text)
                after = text[pos + len(title):line_end].strip()
                if _TOC_LINE_RE.match(after):
                    idx = pos + 1
                    continue
                # also skip if the line looks like a TOC entry (digits + optional page range)
                if re.match(r'^\d+(?:\s*[-–]\s*\d+)*\s*$', after):
                    idx = pos + 1
                    continue
                # title must be at the start of the line (only whitespace before)
                line_start = text.rfind("\n", 0, pos)
                if line_start == -1:
                    line_start = 0
                before_on_line = text[line_start:pos]
                if before_on_line.strip():
                    idx = pos + 1
                    continue
                # also skip if this is before the main report body (table of contents section)
                line = text[line_start:line_end]
                if "目" in line or "录" in line or "TOC" in line.upper():
                    idx = pos + 1
                    continue
                found_pos = pos
                break
            if found_pos == -1:
                continue
            seen_titles.add(title)
            # resolve position to page number
            page = pos_to_page(found_pos + 1, page_offsets, page_count)  # +1 because find gives 0-based
            detected.append({
                "level": 2,
                "title": title,
                "page": page,
                "source": "statement_detection",
                "module": module,
            })
    return detected


def pos_to_page(char_pos: int, offsets: list[int], page_count: int) -> int:
    """Convert a 1-based character position to a 1-based page number."""
    for p in range(1, page_count + 1):
        start = offsets[p - 1] if p - 1 < len(offsets) else 0
        end = offsets[p] if p < len(offsets) else offsets[-1]
        if start <= char_pos <= end:
            return p
    return 1


def build_enriched_outline(
    text: str,
    pdf_data: Optional[bytes] = None,
    page_offsets: Optional[list[int]] = None,
    page_count: int = 0,
) -> tuple[list[dict], list[int], int]:
    """Build the enriched outline by merging PDF bookmarks + regex outline + statement titles.

    Returns ``(merged_entries, page_offsets, page_count)``.
    When ``pdf_data`` is provided and pymupdf is available, also computes
    ``page_offsets`` from it.
    """
    regex_entries = parse_outline(text)
    pymupdf_entries = parse_pymupdf_outline(pdf_data) if pdf_data else []
    merged = merge_outlines(pymupdf_entries, regex_entries)
    if pdf_data and page_offsets is None:
        page_offsets = get_pypdf_page_offsets(pdf_data)
    if not page_count and page_offsets:
        page_count = len(page_offsets) - 1
    if page_offsets and page_count:
        stmt_entries = detect_statement_titles(text, page_offsets, page_count)
        # Remove generic un-prefixed titles when the specific version exists
        # for the same module (e.g., keep 合并资产负债表, drop 资产负债表).
        has_specific: set[str] = set()
        for e in stmt_entries:
            title = e["title"]
            if title.startswith(("合并", "银行", "公司")):
                has_specific.add(e.get("module", ""))
        stmt_entries = [
            e for e in stmt_entries
            if e["title"].startswith(("合并", "银行", "公司"))
            or e.get("module", "") not in has_specific
        ]
        # inject at the start of the outline so they take priority in substring matching
        ordinal = 0
        for e in stmt_entries:
            ordinal += 1
            e["ordinal"] = ordinal
        for e in merged:
            ordinal += 1
            e["ordinal"] = ordinal
        merged = stmt_entries + merged
    return merged, page_offsets or [], page_count


def resolve_statement(outline: list[dict], key: str) -> Optional[dict]:
    """Return the first outline entry matching a statement key, or None.

    Tries each target title in order (consolidated before un-prefixed) via
    ``resolve_selector`` (exact, then regex substring).
    """
    for target in STATEMENT_MATCHERS.get(key, []):
        entry = resolve_selector(outline, target)
        if entry is not None:
            return entry
    return None


# Bank quarterly reports use "合并及公司资产负债表–按中国会计准则编制" etc.
# These are matched by the un-prefixed title as a substring.
# The boundary regex finds the NEXT statement title (excluding continuation
# pages marked 续) or a 第X节 chapter heading. Statement rows like "一、营业
# 收入" are intentionally NOT matched — they are content, not boundaries.
_STATEMENT_NEXT_BOUNDARY_RE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零〇\d]+[章节部分编篇]"
    r"|\s*合并.*(?:资产负债表|利润表|现金流量表)(?!.*续)"
    r"|\s*合并及公司.*(?:资产负债表|利润表|现金流量表)(?!.*续)"
    r")",
    re.MULTILINE,
)


def find_statement_in_text(text: str, module: str) -> Optional[tuple[int, int, str]]:
    """Locate a financial statement in raw report text by its canonical title.

    Used as the body-text fallback when the outline lacks statement titles
    (the quarterly-report case). Tries each canonical title for ``module``
    (consolidated → un-prefixed) via ``_find_section_start`` (skips TOC rows).
    Returns ``(start, end, matched_title)`` where ``start``/``end`` are char
    offsets slicing the statement body, or ``None`` when no title is found.

    The end boundary is the next statement title or the next top-level
    numbered heading (``第X节`` / ``一、``) appearing after the title line.
    """
    targets = STATEMENT_MATCHERS.get(module, [])
    for title in targets:
        pos = _find_section_start(text, title)
        if pos == -1:
            continue
        # start of the line containing the title
        line_start = text.rfind("\n", 0, pos) + 1
        # end = next boundary (statement title or top-level heading) after this line
        body_start = text.find("\n", pos)
        if body_start == -1:
            body_start = len(text)
        end = len(text)
        for m in _STATEMENT_NEXT_BOUNDARY_RE.finditer(text, body_start):
            # skip the title we're currently slicing (boundary must be after the title line)
            if m.start() > body_start:
                end = m.start()
                break
        return line_start, end, title
    return None


def extract_statement_text(text: str, module: str) -> Optional[str]:
    """Return the sliced body text for a statement module, or ``None``.

    Thin wrapper around ``find_statement_in_text`` returning the string slice.
    """
    found = find_statement_in_text(text, module)
    if found is None:
        return None
    start, end, _title = found
    return text[start:end]


def extract_section_by_title(text: str, title: str) -> Optional[str]:
    """Slice body text from *title* to the next top-level heading.

    Searches the raw text for *title* (skipping TOC rows), then slices to
    the next numbered heading (``第X节`` / ``一、`` / ``X.``) or end of text.
    Skips page-header boundaries (same heading repeating within ~2000 chars).
    Used as fallback when the outline lacks the section entry.
    """
    pos = _find_section_start(text, title)
    if pos == -1:
        return None
    line_start = text.rfind("\n", 0, pos) + 1
    body_start = text.find("\n", pos)
    if body_start == -1:
        body_start = len(text)
    end = len(text)
    # Find the first boundary that is NOT a page header.
    # Page headers have a page number line before them within the last 3 lines.
    for m in _STATEMENT_NEXT_BOUNDARY_RE.finditer(text, body_start):
        if m.start() <= body_start:
            continue
        # Check if this is a page header: look back for a standalone page number
        pre = text[max(0, m.start() - 80):m.start()]
        pre_lines = [l.strip() for l in pre.splitlines() if l.strip()]
        is_page_header = False
        for pl in pre_lines[-3:]:
            if pl.isdigit() and len(pl) <= 4:
                is_page_header = True
                break
        if is_page_header:
            continue
        end = m.start()
        break
    return text[line_start:end]


def _find_section_start(text: str, title: str, start_pos: int = 0) -> int:
    """Find the body occurrence of `title` at or after ``start_pos``, skipping
    目录 (TOC) rows and inline references.

    The match must be at an effective line boundary (start of string, preceded
    by ``\\n``, or preceded only by whitespace on the same line) so that titles
    like ``"资产负债表"`` don't match inside longer titles like ``"银行资产负债表"``
    but do match lines with leading whitespace (common in PDF text extraction).
    Additionally the title must be followed by whitespace / line-end / punctuation
    (not a Chinese character) to avoid matching inline references like
    ``"合并资产负债表中投资标准银行的年末余额"``.
    """
    _TOC_SKIP_RE = re.compile(r"^\s*(?:\.{2,}(?:\s*\d+)?|\d+(?:\s*[-–]\s*\d+)*)\s*$")
    idx = start_pos
    while True:
        pos = text.find(title, idx)
        if pos == -1:
            return -1
        # must be at effective line boundary: either start of string,
        # preceded by \n, or preceded only by whitespace on the same line
        line_start = text.rfind("\n", 0, pos) + 1  # 0 if no \n found
        before_on_line = text[line_start:pos]
        if before_on_line.strip():
            # non-whitespace text before the title on the same line → false positive
            idx = pos + 1
            continue
        # title must be followed by whitespace, punctuation, or end-of-line
        # (not a Chinese character — avoids matching "合并资产负债表中...")
        next_ch = text[pos + len(title):pos + len(title) + 1] if pos + len(title) < len(text) else "\n"
        if next_ch and ord(next_ch) > 0x2E80 and ord(next_ch) < 0x9FFF:
            # next char is a CJK ideograph → this is an inline reference, not a heading
            idx = pos + 1
            continue
        # peek at the rest of the line after the title
        line_end = text.find("\n", pos)
        if line_end == -1:
            line_end = len(text)
        after = text[pos + len(title):line_end].strip()
        # TOC rows: "title ......... 12" or "title 7-8" (page refs)
        if _TOC_SKIP_RE.match(after):
            idx = pos + 1
            continue
        # Also skip if the next line is just a page number (page on its own line,
        # e.g. "第三章 管理层讨论与分析\n19" — common in CJK PDF TOCs).
        next_line_start = line_end + 1
        if next_line_start < len(text):
            next_line_end = text.find("\n", next_line_start)
            if next_line_end == -1:
                next_line_end = len(text)
            next_line = text[next_line_start:next_line_end].strip()
            if next_line.isdigit() or re.match(r"^\d+\s*[-–]\s*\d+$", next_line):
                idx = pos + 1
                continue
        return pos


def extract_section_text(
    text: str,
    outline: list[dict],
    entry: dict,
    page_offsets: Optional[list[int]] = None,
    page_count: int = 0,
) -> str:
    """Slice body text from entry's title to the next outline entry's title.

    When ``entry`` has a ``page`` and ``page_offsets`` is provided, restricts
    the title search to the entry's page area.  This avoids false matches
    against the table-of-contents or earlier cross-references.
    """
    # Start: restrict search to entry's page area when available
    if entry.get("page") and page_offsets:
        page_start = page_to_char_offset(entry["page"], page_offsets)
        start = _find_section_start(text, entry["title"], start_pos=page_start)
        if start == -1:
            start = _find_section_start(text, entry["title"])
        if start == -1:
            token = entry["title"].split()[0] if entry["title"] else entry["title"]
            start = _find_section_start(text, token)
        if start == -1:
            return ""
    else:
        start = _find_section_start(text, entry["title"])
        if start == -1:
            token = entry["title"].split()[0] if entry["title"] else entry["title"]
            start = _find_section_start(text, token)
        if start == -1:
            return ""

    start = text.find("\n", start)
    if start == -1:
        start = len(text)

    # End: next sibling outline entry's position
    # Skip entries whose title is a substring of the current entry (e.g., "资产负债表"
    # is a substring of "合并资产负债表") to avoid premature truncation on the same page.
    cur_title = entry["title"]
    end = len(text)
    for e in outline:
        if e["ordinal"] <= entry["ordinal"]:
            continue
        if e.get("source") == entry.get("source") and e["title"] in cur_title:
            continue
        nsearch_start = start
        if e.get("page") and page_offsets:
            e_page = page_to_char_offset(e["page"], page_offsets)
            if e_page > start:
                nsearch_start = e_page
        pos = _find_section_start(text, e["title"], start_pos=nsearch_start)
        if pos != -1:
            end = min(end, pos)
            break
    return text[start:end].strip()


# ── LLM extraction ───────────────────────────────────────────────


def llm_config() -> dict:
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "").rstrip("/"),
        "api_key": os.environ.get("LLM_API_KEY", "") or os.environ.get("OPENAI_API_KEY", ""),
        "model": os.environ.get("LLM_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o")),
    }


def call_llm_json(system: str, user: str, max_retries: int = 3) -> str:
    """Call the OpenAI-compatible chat/completions endpoint, return raw content.

    Retries on transient connection errors (OpenRouter free tier and other
    shared upstreams often drop the connection mid-stream).
    """
    import httpx
    import time

    cfg = llm_config()
    if not cfg["api_key"]:
        raise RuntimeError("LLM_API_KEY is not configured")
    url = cfg["base_url"] + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 32000,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=300.0)
            if resp.status_code == 429 and attempt < max_retries - 1:
                retry_after = float(resp.headers.get("Retry-After", "5"))
                time.sleep(min(retry_after, 30.0))
                last_err = RuntimeError(f"429 rate-limited (retry-after={retry_after:.0f}s)")
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (httpx.RemoteProtocolError, httpx.ReadTimeout,
                httpx.ConnectError, httpx.ReadError) as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2.0 * (attempt + 1))
    raise last_err  # type: ignore[misc]


def call_llm_pydantic(
    system: str,
    user: str,
    model_class: type,
    max_retries: int = 2,
) -> Any:
    """Call the LLM with ``response_format.json_schema``, return a validated
    Pydantic model instance.

    ``model_class`` must be a subclass of ``BaseExtractionResult`` (or any
    Pydantic`` BaseModel`` with ``model_validate``).

    **Fallback chain:**
    1. ``json_schema`` (OpenAI structured output)
    2. ``json_object`` (provider doesn't support ``json_schema``) — retry once
    3. No ``response_format`` (provider supports neither) — retry once
    """
    from indicators_models import model_to_json_schema

    import httpx
    import time

    cfg = llm_config()
    if not cfg["api_key"]:
        raise RuntimeError("LLM_API_KEY is not configured")
    url = cfg["base_url"] + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}

    schema_payload = model_to_json_schema(model_class)

    strategies: list[dict | None] = [
        {"type": "json_schema", "json_schema": schema_payload},
        {"type": "json_object"},
        None,
    ]

    last_err: Exception | None = None
    for strat in strategies:
        for attempt in range(max_retries):
            payload: dict = {
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
            }
            if strat is not None:
                payload["response_format"] = strat
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=300.0)
                if resp.status_code == 400 and strat is not None and strat.get("type") == "json_schema":
                    # provider rejected json_schema → try next strategy
                    last_err = RuntimeError(f"json_schema rejected: {resp.text[:200]}")
                    break
                if resp.status_code == 429 and attempt < max_retries - 1:
                    retry_after = float(resp.headers.get("Retry-After", "5"))
                    time.sleep(min(retry_after, 30.0))
                    last_err = RuntimeError(f"429 rate-limited (retry-after={retry_after:.0f}s)")
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                # Handle single-field models: LLM may return bare value instead of {"field": value}
                if not isinstance(parsed, dict):
                    fields = list(model_class.model_fields.keys())
                    if len(fields) == 1:
                        parsed = {fields[0]: parsed}
                return model_class.model_validate(parsed)
            except (httpx.RemoteProtocolError, httpx.ReadTimeout,
                    httpx.ConnectError, httpx.ReadError) as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(2.0 * (attempt + 1))
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                last_err = e
                if attempt < max_retries - 1:
                    continue
                break  # no point retrying with the same strategy for parse errors
        else:
            continue  # inner loop finished without break → strat worked
        continue  # inner break → try next strategy

    raise RuntimeError(f"LLM extraction failed after all strategies: {last_err}") from last_err


def validate_against_schema(data, schema: dict) -> Optional[str]:
    """Return None if valid, else a short error string."""
    try:
        import jsonschema

        jsonschema.validate(instance=data, schema=schema)
        return None
    except ImportError:
        return None  # ponytail: no jsonschema installed → skip validation
    except Exception as e:
        return str(e)


# ── Elasticsearch ────────────────────────────────────────────────

CNREPORT_MAPPING = {
    "properties": {
        "report_id": {"type": "keyword"},
        "company": {"type": "keyword"},
        "stock_code": {"type": "keyword"},
        "year": {"type": "integer"},
        "section": {"type": "keyword"},
        "section_id": {"type": "keyword"},
        "text": {"type": "text", "analyzer": "ik_smart"},
        "fields": {"type": "object", "dynamic": True},
        "indexed_at": {"type": "date"},
    }
}
CNREPORT_MAPPING_FALLBACK = {
    # ponytail: standard analyzer when ik plugin is absent
    "properties": {
        **CNREPORT_MAPPING["properties"],
        "text": {"type": "text", "analyzer": "standard"},
    }
}


def es_client():
    """Build an Elasticsearch client from env. Raises if ES_URL unset."""
    from elasticsearch import Elasticsearch

    url = os.environ.get("ES_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("ES_URL is not configured")
    api_key = os.environ.get("ES_API_KEY")
    if api_key:
        return Elasticsearch(url, api_key=api_key)
    user = os.environ.get("ES_USERNAME")
    pwd = os.environ.get("ES_PASSWORD")
    if user:
        return Elasticsearch(url, basic_auth=(user, pwd or ""))
    return Elasticsearch(url)


def index_name_for(year: int) -> str:
    return f"cnreport-{year}"


def mapping_hash(mapping: dict) -> str:
    return hashlib.sha1(json.dumps(mapping, sort_keys=True).encode()).hexdigest()[:16]


def ensure_index(es, year: int) -> tuple[str, dict]:
    """Create cnreport-{year} if missing. Tries ik_smart, falls back to standard.

    Returns (index_name, mapping_used).
    """
    name = index_name_for(year)
    if es.indices.exists(index=name):
        return name, CNREPORT_MAPPING  # assume ik; hash still recorded
    try:
        es.indices.create(index=name, mappings=CNREPORT_MAPPING)
        return name, CNREPORT_MAPPING
    except Exception:
        # ik analyzer not installed → retry with standard
        es.indices.create(index=name, mappings=CNREPORT_MAPPING_FALLBACK)
        return name, CNREPORT_MAPPING_FALLBACK


def records_to_docs(records: list[dict], report_id: str, section_id: str) -> list[dict]:
    """Map extracted records to ES docs. Each record carries its own fields."""
    docs = []
    for i, rec in enumerate(records):
        docs.append(
            {
                "_id": f"{report_id}:{section_id}:{i}",
                "report_id": report_id,
                "section_id": section_id,
                "section": section_id,
                "fields": rec,
                "text": json.dumps(rec, ensure_ascii=False),
            }
        )
    return docs


# ── company API (edgartools-style) ───────────────────────────────
# Thin wrappers over cninfo_client + financials_client. All errors return
# {"error": ...} instead of raising, matching the edgartools-mcp pattern.


def _tool_safe(fn):
    """Decorator: convert any exception to {'error': '<type>: <msg>'}."""
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — tool boundary
            return {"error": f"{type(e).__name__}: {e}"}
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


@_tool_safe
def get_company(ticker_or_name: str) -> dict:
    """Resolve a CN-A-share company by 6-digit ticker or name fragment."""
    import cninfo_client  # late import keeps server.py boot light

    row = cninfo_client.lookup_company(ticker_or_name)
    if not row:
        return {"error": f"no company matched: {ticker_or_name!r}"}
    return row


@_tool_safe
def list_filings(
    ticker_or_name: str,
    form: Optional[str] = None,
    category: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 20,
) -> list[dict] | dict:
    """List a company's disclosures, filtered by form or category and year.

    `form` and `category` are mutually exclusive. `form` accepts the four
    periodic report names or a free-text title substring. `category` accepts
    any CNINFO category code or Chinese name from the catalog (e.g. 招股说明书);
    an unknown category returns an error without a network call.
    """
    import cninfo_client

    if form and category:
        return {"error": "specify either form or category, not both"}
    if category is not None and not cninfo_client.resolve_category(category):
        return {"error": f"unknown CNINFO category: {category!r}"}

    company = cninfo_client.lookup_company(ticker_or_name)
    if not company:
        return {"error": f"no company matched: {ticker_or_name!r}"}
    rows = cninfo_client.query_announcements(
        company["stock_code"],
        company["org_id"],
        form=form,
        category=category,
        year=year,
        limit=limit,
    )
    return rows


@_tool_safe
def get_filing(announcement_id: str, ticker_or_name: Optional[str] = None) -> dict:
    """Fetch one announcement's metadata + PDF URL by id."""
    import cninfo_client

    stock_code = org_id = None
    if ticker_or_name:
        company = cninfo_client.lookup_company(ticker_or_name)
        if company:
            stock_code = company["stock_code"]
            org_id = company["org_id"]
    row = cninfo_client.get_announcement(
        announcement_id, stock_code=stock_code, org_id=org_id,
    )
    if not row:
        return {"error": f"no announcement found: {announcement_id!r}"}
    return row


@_tool_safe
def get_financials(
    ticker_or_name: str,
    statement: Optional[str] = None,
    period: str = "annual",
) -> dict:
    """Return structured income/balance/cashflow statements via akshare."""
    import cninfo_client
    import financials_client

    company = cninfo_client.lookup_company(ticker_or_name)
    if not company:
        return {"error": f"no company matched: {ticker_or_name!r}"}
    try:
        all_stmts = financials_client.get_statements(
            company["stock_code"],
            period=period,
            exchange=company["exchange"],
        )
    except financials_client.MissingDependencyError as e:
        return {"error": str(e)}

    if statement:
        if statement not in all_stmts:
            return {
                "error": (
                    f"unknown statement: {statement!r}; "
                    f"choose from {sorted(all_stmts)}"
                )
            }
        return {
            "stock_code": company["stock_code"],
            "company_name": company["name"],
            "period": period,
            "statement": statement,
            **{statement: all_stmts[statement]},
        }
    return {
        "stock_code": company["stock_code"],
        "company_name": company["name"],
        "period": period,
        **all_stmts,
    }


@_tool_safe
def get_section(
    ticker_or_name: str,
    year: int,
    section: str,
    form: str = "年度报告",
) -> dict:
    """Convenience: resolve filing PDF for (ticker, year, form) then extract a section.

    Reuses the cache-aware fetch path (report_cache.get_or_fetch) →
    parse_outline → resolve_selector → extract_section_text so no PDF is
    re-downloaded or re-parsed when the same report has been fetched before.
    """
    import cninfo_client
    import report_cache

    company = cninfo_client.lookup_company(ticker_or_name)
    if not company:
        return {"error": f"no company matched: {ticker_or_name!r}"}
    filings = cninfo_client.query_announcements(
        company["stock_code"],
        company["org_id"],
        form=form,
        year=year,
        limit=5,
    )
    if not filings:
        return {
            "error": (
                f"no filing found for {company['stock_code']} "
                f"form={form!r} year={year}"
            )
        }
    top = filings[0]
    pdf = top["pdf_url"]
    text, cache_info = report_cache.get_or_fetch(
        pdf,
        stock_code=company["stock_code"],
        year=year,
        form=form,
        announcement_id=top.get("announcement_id") or "",
    )
    enriched = cache_info.get("enriched_outline")
    outline = enriched or parse_outline(text)
    page_offsets = cache_info.get("page_offsets") or []
    entry = resolve_selector(outline, section)
    if entry is None:
        return {
            "error": "no section matched selector",
            "available": [e["title"] for e in outline],
            "pdf_url": pdf,
        }
    body = extract_section_text(text, outline, entry,
                                page_offsets=page_offsets or None,
                                page_count=len(page_offsets) - 1 if len(page_offsets) > 1 else 0)
    return {
        "stock_code": company["stock_code"],
        "company_name": company["name"],
        "year": year,
        "form": form,
        "section": section,
        "pdf_url": pdf,
        "outline_entry": entry,
        "char_count": len(body),
        "text": body,
    }


@_tool_safe
def list_report_types(group: Optional[str] = None) -> dict:
    """Return the CNINFO disclosure category catalog.

    With no `group`, returns every group with its categories. With `group`,
    returns only that group's categories. Each category carries `name`, `code`,
    and `description`. The response includes a `count` of categories returned.
    """
    import cninfo_client

    catalog = cninfo_client.load_categories()
    groups = catalog.get("groups", [])
    if group is not None:
        matched = [g for g in groups if g.get("name") == group]
        if not matched:
            return {
                "error": f"unknown group: {group!r}",
                "available": [g.get("name") for g in groups],
            }
        cats = matched[0].get("categories", [])
        return {"group": group, "categories": cats, "count": len(cats)}
    all_cats: list[dict] = []
    for g in groups:
        all_cats.extend(g.get("categories", []))
    return {"groups": groups, "count": len(all_cats)}


@_tool_safe
def get_special_report(
    ticker_or_name: str,
    category: str,
    year: Optional[int] = None,
    section: Optional[str] = None,
    limit: int = 5,
) -> dict:
    """Retrieve a special-type report for a company by CNINFO category.

    Resolves the company, lists filings of the given `category` (any catalog
    name like 招股说明书 / 增发 / 业绩预告, or a raw `category_*` code), and returns
    the top filing's metadata + pdf_url. When `section` is given, fetches the
    PDF (via the report cache) and extracts that section's body through the
    outline pipeline (parse_outline → resolve_selector → extract_section_text)
    — no PDF logic duplicated. When `section` is omitted, the PDF is NOT downloaded.
    """
    import cninfo_client
    import report_cache

    company = cninfo_client.lookup_company(ticker_or_name)
    if not company:
        return {"error": f"no company matched: {ticker_or_name!r}"}
    if not cninfo_client.resolve_category(category):
        return {"error": f"unknown CNINFO category: {category!r}"}

    filings = cninfo_client.query_announcements(
        company["stock_code"],
        company["org_id"],
        category=category,
        year=year,
        limit=limit,
    )
    if not filings:
        return {
            "error": (
                f"no filing found for {company['stock_code']} "
                f"category={category!r} year={year}"
            )
        }
    top = filings[0]
    if section is None:
        return {
            "stock_code": company["stock_code"],
            "company_name": company["name"],
            "category": category,
            "year": year,
            "filings": filings,
            "pdf_url": top["pdf_url"],
        }
    # Section extraction — via the cache-aware fetch path (no duplication).
    pdf = top["pdf_url"]
    text, _ = report_cache.get_or_fetch(
        pdf,
        stock_code=company["stock_code"],
        year=year,
        form=category,
        announcement_id=top.get("announcement_id") or "",
    )
    outline = parse_outline(text)
    entry = resolve_selector(outline, section)
    if entry is None:
        return {
            "error": "no section matched selector",
            "available": [e["title"] for e in outline],
            "pdf_url": pdf,
        }
    body = extract_section_text(text, outline, entry)
    return {
        "stock_code": company["stock_code"],
        "company_name": company["name"],
        "category": category,
        "year": year,
        "section": section,
        "pdf_url": pdf,
        "outline_entry": entry,
        "char_count": len(body),
        "text": body,
    }


@_tool_safe
def get_financial_statements(
    ticker_or_name: str,
    year: int,
    form: str = "年度报告",
) -> dict:
    """Extract the three major financial statements (三大报表) as text.

    Resolves the company's filing PDF for ``(ticker, year, form)`` (via the
    report cache — no re-download on repeat), parses the table of contents,
    and returns the body text of each statement section:

      - income_statement (利润表)         — prefers 合并利润表
      - balance_sheet (资产负债表)         — prefers 合并资产负债表
      - cashflow (现金流量表)              — prefers 合并现金流量表

    Falls back to the un-prefixed title when no consolidated version is found.
    Returns section **text only** — never PDF bytes. Statements not located in
    the TOC are listed in ``missing`` (with the full ``available`` title list
    so the caller can fall back to ``get_section`` with a custom selector).
    """
    import cninfo_client
    import report_cache

    company = cninfo_client.lookup_company(ticker_or_name)
    if not company:
        return {"error": f"no company matched: {ticker_or_name!r}"}
    filings = cninfo_client.query_announcements(
        company["stock_code"],
        company["org_id"],
        form=form,
        year=year,
        limit=5,
    )
    if not filings:
        return {
            "error": (
                f"no filing found for {company['stock_code']} "
                f"form={form!r} year={year}"
            )
        }
    top = filings[0]
    pdf = top["pdf_url"]
    text, cache_info = report_cache.get_or_fetch(
        pdf,
        stock_code=company["stock_code"],
        year=year,
        form=form,
        announcement_id=top.get("announcement_id") or "",
    )
    enriched = cache_info.get("enriched_outline")
    outline = enriched or parse_outline(text)
    page_offsets = cache_info.get("page_offsets") or []
    statements: dict = {}
    missing: list[str] = []
    for key in ("income_statement", "balance_sheet", "cashflow"):
        entry = resolve_statement(outline, key)
        if entry is None:
            missing.append(key)
            continue
        body = extract_section_text(text, outline, entry,
                                    page_offsets=page_offsets or None,
                                    page_count=len(page_offsets) - 1 if len(page_offsets) > 1 else 0)
        statements[key] = {
            "title": entry["title"],
            "outline_entry": entry,
            "char_count": len(body),
            "text": body,
        }
    result: dict = {
        "stock_code": company["stock_code"],
        "company_name": company["name"],
        "year": year,
        "form": form,
        "pdf_url": pdf,
        "cached": cache_info["cached"],
        "statements": statements,
        "missing": missing,
    }
    if missing:
        result["available"] = [e["title"] for e in outline]
    return result


# ── indicator rules engine (data-driven) ──────────────────────────
# Thin wrappers over indicators_client. Adding an indicator = editing
# indicator_rules.json (no code change), mirroring the cninfo_categories
# convention. Errors return {"error": ...}, never raise.


@_tool_safe
def list_indicators(
    module: Optional[str] = None,
    query: Optional[str] = None,
    company: Optional[str] = None,
) -> dict:
    """Browse the indicator rule set, optionally filtered.

    With no args returns every rule grouped by module/subgroup. `module`
    filters to one module; `query` does a normalized substring match over
    name+aliases; `company` (ticker or name) filters to the rules applicable
    to that company and includes the resolved `{industry, sub_type}` profile.
    """
    import indicators_client

    return indicators_client.list_rules(module=module, query=query, company=company)


@_tool_safe
def get_indicator(
    indicator: str,
    ticker_or_name: str,
    year: int,
    period: str = "annual",
) -> dict:
    """Resolve one named indicator to a value for a company + period.

    Routes per the rule's source_type: akshare line items, annual-report PDF
    section (LLM or registered Python extractor), or locally-computed ratio.
    Returns `{value, unit, source_type, extractor, source, period, provenance}`
    or `{error}`. Indicators whose rule does not apply to the company return an
    error without fetching the PDF.
    """
    import indicators_client

    return indicators_client.get_indicator(indicator, ticker_or_name, year, period=period)


@_tool_safe
def extract_indicators(
    ticker_or_name: str,
    year: int,
    indicators: Optional[list] = None,
    form: str = "年度报告",
    extractor_mode: str = "auto",
) -> dict:
    """Extract many indicators for one company/year in a single pass.

    Fetches the annual-report PDF once, groups report-rules by section (one LLM
    call per section), dispatches Python extractors individually, and computes
    derived ratios locally. Caches the resulting bundle to disk keyed by the
    applicable rule set. `extractor_mode` is `auto` (default), `llm` (force LLM
    for report rules), or `python` (skip report rules whose extractor is LLM).
    """
    import indicators_client

    return indicators_client.extract_indicators(
        ticker_or_name, year, indicators=indicators, form=form, extractor_mode=extractor_mode,
    )


@_tool_safe
def extract_indicators_by_position(
    ticker_or_name: str,
    year: int,
    csv_path: str = "docs/indicators_position.csv",
    extractor: str = "auto",
    indicators: Optional[list] = None,
) -> dict:
    """Extract the indicators named in a position CSV for one company/year.

    Reads the CSV's ``indicator`` column (default ``docs/indicators_position.csv``),
    intersects it with ``indicators`` if given, resolves each name to a rule, and
    routes ``report`` / ``akshare`` / ``computed`` rules through the batch engine.
    ``external`` (realtime / market-data) indicators are listed in ``skipped`` —
    they are not present in the report PDF and are never fetched or sent to the LLM.

    Returns: ``{stock_code, company_name, year, form, pdf_url, cached, indicators,
              missing, unresolved, skipped, csv_path}`` or ``{error}``.
    """
    import indicators_client

    return indicators_client.extract_indicators_by_position(
        ticker_or_name, year, csv_path=csv_path, extractor=extractor, indicators=indicators,
    )


# ── HK stock tools ───────────────────────────────────────────────


@_tool_safe
def get_hk_company(ticker_or_name: str) -> dict:
    """Resolve a HK stock company by 5-digit ticker or name fragment.

    Args:
        ticker_or_name: ticker ("00700") or name fragment ("腾讯").

    Returns: {stock_code, name, name_en, industry, employees, description, website}
             or {error}.
    """
    import hk_stock_client

    row = hk_stock_client.lookup_hk_company(ticker_or_name)
    if not row:
        return {"error": f"no HK company matched: {ticker_or_name!r}"}
    return row


@_tool_safe
def list_hk_filings(
    ticker_or_name: str,
    form: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 20,
) -> list[dict] | dict:
    """List a HK stock company's filings/announcements.

    Args:
        ticker_or_name: HK stock ticker or name.
        form: optional form type filter (e.g. "年报", "年报/中期报告").
        year: optional year filter.
        limit: max results (default 20).

    Returns: list of filing entries or {error}.
    """
    import hk_stock_client

    company = hk_stock_client.lookup_hk_company(ticker_or_name)
    if not company:
        return {"error": f"no HK company matched: {ticker_or_name!r}"}
    rows = hk_stock_client.list_hk_filings(
        company["stock_code"], form=form, year=year, limit=limit,
    )
    return rows


@_tool_safe
def get_hk_financials(ticker_or_name: str) -> dict:
    """Return structured financial statements for a HK stock company.

    Args:
        ticker_or_name: HK stock ticker or name.

    Returns: {stock_code, company_name, income_statement, balance_sheet, cashflow}
             or {error}.
    """
    import hk_stock_client

    company = hk_stock_client.lookup_hk_company(ticker_or_name)
    if not company:
        return {"error": f"no HK company matched: {ticker_or_name!r}"}
    stmts = hk_stock_client.get_hk_financials(company["stock_code"])
    return {
        "stock_code": company["stock_code"],
        "company_name": company["name"],
        **stmts,
    }


@_tool_safe
def get_hk_section(
    ticker_or_name: str,
    year: int,
    section: str,
) -> dict:
    """Extract a named section from a HK stock annual report PDF.

    Convenience wrapper: (ticker, year, section) → HK filing lookup
    → PDF URL → existing text-extraction pipeline.

    Args:
        ticker_or_name: HK stock ticker or name.
        year: fiscal year.
        section: section title or selector.

    Returns: {stock_code, company_name, year, section, pdf_url, text, char_count}
             or {error}.
    """
    import hk_stock_client
    import cnreport_tools as T

    company = hk_stock_client.lookup_hk_company(ticker_or_name)
    if not company:
        return {"error": f"no HK company matched: {ticker_or_name!r}"}
    filing = hk_stock_client.get_hk_annual_report_filing(company["stock_code"], year)
    if not filing or not filing.get("pdf_url"):
        return {
            "error": f"no annual report filing found for {company['stock_code']} year={year}",
            "company_name": company["name"],
        }
    pdf = filing["pdf_url"]
    text, _ = report_cache.get_or_fetch(
        pdf,
        stock_code=company["stock_code"],
        year=year,
        form="hkex-annual",
        announcement_id=filing.get("announcement_id") or "",
    )
    outline = T.parse_outline(text)
    entry = T.resolve_selector(outline, section)
    if entry is None:
        return {
            "error": "no section matched selector",
            "available": [e["title"] for e in outline],
            "pdf_url": pdf,
        }
    body = T.extract_section_text(text, outline, entry)
    return {
        "stock_code": company["stock_code"],
        "company_name": company["name"],
        "year": year,
        "section": section,
        "pdf_url": pdf,
        "outline_entry": entry,
        "char_count": len(body),
        "text": body,
    }


@_tool_safe
def audit_rule_gaps(
    out_dir: str = "out",
    output_path: str = "docs/rule_gap_audit.json",
    max_files: int = 0,
) -> dict:
    import time
    from pathlib import Path

    import report_section_map as RSM

    repo_root = Path(__file__).resolve().parent
    rules_path = repo_root / "indicator_rules.json"
    out_root = (repo_root / out_dir).resolve() if not Path(out_dir).is_absolute() else Path(out_dir).resolve()
    output_file = (repo_root / output_path).resolve() if not Path(output_path).is_absolute() else Path(output_path).resolve()

    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    rules_array = rules.get("rules") or []
    rules_hash = hashlib.sha1(
        json.dumps(rules_array, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]

    files = sorted(out_root.glob("*.json"))
    if max_files and max_files > 0:
        files = files[:max_files]

    def _classify_bundle(bundle: dict, path: str) -> list[dict]:
        items: list[dict] = []
        stock_code = bundle.get("stock_code", "")
        form = bundle.get("form", "")
        year = bundle.get("year", "")

        for m in bundle.get("missing") or []:
            if isinstance(m, str):
                ind = m
                reason = "missing"
                tried = []
            else:
                ind = m.get("indicator") or m.get("name") or ""
                reason = m.get("reason") or ""
                tried = m.get("tried") or []

            categories: list[str] = []
            if "not applicable" in reason:
                categories.append("inapplicable_rule")
            elif "unknown" in reason or "no rule" in reason:
                categories.append("missing_rule")
            elif "section not found" in reason:
                categories.append("missing_section")
            else:
                categories.append("missing_rule")

            suggested: list[str] = []
            if "missing_section" in categories:
                seen: set[str] = set()
                for t in tried if isinstance(tried, list) else []:
                    for c in RSM.candidates(form, str(t)):
                        if c not in seen:
                            seen.add(c)
                            suggested.append(c)
                if not suggested:
                    for key in RSM.canonical_keys(form):
                        for c in RSM.candidates(form, key):
                            if c not in seen:
                                seen.add(c)
                                suggested.append(c)

            items.append(
                {
                    "indicator": ind,
                    "categories": categories,
                    "evidence": {
                        "bundle": path,
                        "stock_code": stock_code,
                        "year": year,
                        "form": form,
                        "reason": reason,
                        "tried": tried,
                    },
                    "suggested_sections": suggested,
                }
            )

        for u in bundle.get("unresolved") or []:
            if isinstance(u, str):
                ind = u
                note = ""
            else:
                ind = u.get("indicator") or u.get("name") or ""
                note = u.get("note") or ""
            items.append(
                {
                    "indicator": ind,
                    "categories": ["unresolved_extractor"],
                    "evidence": {
                        "bundle": path,
                        "stock_code": stock_code,
                        "year": year,
                        "form": form,
                        "note": note,
                    },
                    "suggested_sections": [],
                }
            )

        indicators = bundle.get("indicators") or {}
        for ind, entry in indicators.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("source_type") != "report":
                continue
            if entry.get("value") is not None:
                continue
            note = entry.get("note") or ""
            if isinstance(note, str) and note.startswith("llm"):
                items.append(
                    {
                        "indicator": ind,
                        "categories": ["llm_null_value"],
                        "evidence": {
                            "bundle": path,
                            "stock_code": stock_code,
                            "year": year,
                            "form": form,
                            "note": note,
                            "source": entry.get("source") or "",
                        },
                        "suggested_sections": [],
                    }
                )
        return items

    all_items: list[dict] = []
    for p in files:
        try:
            bundle = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        all_items.extend(_classify_bundle(bundle, str(p)))

    def _stable_key(it: dict) -> tuple:
        ev = it.get("evidence") or {}
        return (
            it.get("indicator") or "",
            ",".join(it.get("categories") or []),
            ev.get("stock_code") or "",
            str(ev.get("year") or ""),
            ev.get("form") or "",
            ev.get("bundle") or "",
        )

    all_items.sort(key=_stable_key)
    summary: dict[str, int] = {}
    for it in all_items:
        for c in it.get("categories") or []:
            summary[c] = summary.get(c, 0) + 1

    report = {
        "generated_at": int(time.time()),
        "rules_hash": rules_hash,
        "inputs": {
            "rules_path": str(rules_path),
            "out_dir": str(out_root),
            "files_scanned": [str(p) for p in files],
        },
        "summary": summary,
        "items": all_items,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return {"output_path": str(output_file), "report": report}


# ── SSE (上海证券交易所) official-website tools ───────────────────
# Direct primary-source path complementing CNINFO. See sse_client for the
# undocumented query.sse.com.cn / sns.sseinfo.com endpoints.


@_tool_safe
def get_sse_company(ticker_or_name: str) -> dict:
    """Resolve an SSE-listed company by 6-digit ticker.

    Name fragments are not supported by the SSE client (no reliable search
    endpoint) - resolve the name via ``get_company`` (CNINFO) first.

    Returns: {stock_code, exchange, source, name} or {error}.
    """
    import sse_client

    row = sse_client.lookup_sse_company(ticker_or_name)
    if not row:
        return {"error": f"no SSE company matched: {ticker_or_name!r} (use a 6-digit SSE code)"}
    return row


@_tool_safe
def list_sse_filings(
    ticker_or_name: str,
    title: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 20,
) -> list[dict] | dict:
    """List a SSE-listed company's disclosures from sse.com.cn.

    Args:
        ticker_or_name: 6-digit SSE ticker.
        title: optional title-substring filter (e.g. "年度报告").
        year: optional fiscal-year filter.
        limit: max rows (default 20).

    Returns: list of {announcement_id, title, form, published, pdf_url,
             stock_code, source} or {error}.
    """
    import sse_client

    company = sse_client.lookup_sse_company(ticker_or_name)
    if not company:
        return {"error": f"no SSE company matched: {ticker_or_name!r} (use a 6-digit SSE code)"}
    return sse_client.list_sse_filings(
        company["stock_code"], title=title, year=year, limit=limit,
    )


@_tool_safe
def get_sse_section(
    ticker_or_name: str,
    year: int,
    section: str,
) -> dict:
    """Extract a named section from a SSE company's annual-report PDF.

    Convenience wrapper: (ticker, year, section) -> SSE filing lookup
    -> PDF URL -> existing text-extraction pipeline (report_cache + outline).

    Returns: {stock_code, year, section, pdf_url, outline_entry, text,
             char_count} or {error}.
    """
    import sse_client
    import report_cache

    company = sse_client.lookup_sse_company(ticker_or_name)
    if not company:
        return {"error": f"no SSE company matched: {ticker_or_name!r} (use a 6-digit SSE code)"}
    filing = sse_client.get_sse_annual_report_filing(company["stock_code"], year)
    if not filing or not filing.get("pdf_url"):
        return {
            "error": f"no annual report filing found for {company['stock_code']} year={year}",
            "stock_code": company["stock_code"],
        }
    pdf = filing["pdf_url"]
    text, _ = report_cache.get_or_fetch(
        pdf,
        stock_code=company["stock_code"],
        year=year,
        form="sse-annual",
        announcement_id=filing.get("announcement_id") or "",
    )
    outline = parse_outline(text)
    entry = resolve_selector(outline, section)
    if entry is None:
        return {
            "error": "no section matched selector",
            "available": [e["title"] for e in outline],
            "pdf_url": pdf,
        }
    body = extract_section_text(text, outline, entry)
    return {
        "stock_code": company["stock_code"],
        "year": year,
        "section": section,
        "pdf_url": pdf,
        "outline_entry": entry,
        "char_count": len(body),
        "text": body,
    }


@_tool_safe
def get_sse_interaction(ticker_or_name: str, limit: int = 20) -> dict:
    """Fetch 上证e互动 investor Q&A for a SSE-listed company.

    Returns: {stock_code, source, questions: [...]} or {stock_code, source,
             error}. Endpoint (sns.sseinfo.com) is undocumented - verify live.
    """
    import sse_client

    company = sse_client.lookup_sse_company(ticker_or_name)
    if not company:
        return {"error": f"no SSE company matched: {ticker_or_name!r} (use a 6-digit SSE code)"}
    return sse_client.get_sse_interaction(company["stock_code"], limit=limit)


# ── SZSE (深圳证券交易所) official-website tools ──────────────────


@_tool_safe
def get_szse_company(ticker_or_name: str) -> dict:
    """Resolve a SZSE-listed company by 6-digit ticker (szse.cn).

    Name fragments are not supported here - resolve via ``get_company`` first.

    Returns: {stock_code, exchange, source, name} or {error}.
    """
    import szse_client

    row = szse_client.lookup_szse_company(ticker_or_name)
    if not row:
        return {"error": f"no SZSE company matched: {ticker_or_name!r} (use a 6-digit SZSE code)"}
    return row


@_tool_safe
def list_szse_filings(
    ticker_or_name: str,
    title: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 20,
) -> list[dict] | dict:
    """List a SZSE-listed company's disclosures directly from szse.cn.

    Returns: list of {announcement_id, title, form, published, pdf_url,
             stock_code, source} or {error}.
    """
    import szse_client

    company = szse_client.lookup_szse_company(ticker_or_name)
    if not company:
        return {"error": f"no SZSE company matched: {ticker_or_name!r} (use a 6-digit SZSE code)"}
    return szse_client.list_szse_filings(
        company["stock_code"], title=title, year=year, limit=limit,
    )


@_tool_safe
def get_szse_section(
    ticker_or_name: str,
    year: int,
    section: str,
) -> dict:
    """Extract a named section from a SZSE company's annual-report PDF.

    Returns: {stock_code, year, section, pdf_url, outline_entry, text,
             char_count} or {error}.
    """
    import szse_client
    import report_cache

    company = szse_client.lookup_szse_company(ticker_or_name)
    if not company:
        return {"error": f"no SZSE company matched: {ticker_or_name!r} (use a 6-digit SZSE code)"}
    filing = szse_client.get_szse_annual_report_filing(company["stock_code"], year)
    if not filing or not filing.get("pdf_url"):
        return {
            "error": f"no annual report filing found for {company['stock_code']} year={year}",
            "stock_code": company["stock_code"],
        }
    pdf = filing["pdf_url"]
    text, _ = report_cache.get_or_fetch(
        pdf,
        stock_code=company["stock_code"],
        year=year,
        form="szse-annual",
        announcement_id=filing.get("announcement_id") or "",
    )
    outline = parse_outline(text)
    entry = resolve_selector(outline, section)
    if entry is None:
        return {
            "error": "no section matched selector",
            "available": [e["title"] for e in outline],
            "pdf_url": pdf,
        }
    body = extract_section_text(text, outline, entry)
    return {
        "stock_code": company["stock_code"],
        "year": year,
        "section": section,
        "pdf_url": pdf,
        "outline_entry": entry,
        "char_count": len(body),
        "text": body,
    }


@_tool_safe
def get_szse_interaction(ticker_or_name: str, limit: int = 20) -> dict:
    """Fetch 互动易 investor Q&A for a SZSE-listed company (irm.cninfo.com.cn).

    Returns: {stock_code, source, questions: [...]} or {error}.
    """
    import szse_client

    company = szse_client.lookup_szse_company(ticker_or_name)
    if not company:
        return {"error": f"no SZSE company matched: {ticker_or_name!r} (use a 6-digit SZSE code)"}
    return szse_client.get_szse_interaction(company["stock_code"], limit=limit)


# ── BSE (北京证券交易所) official-website tools ───────────────────
# BSE-native disclosure with a CNINFO cross-reference fallback; each filing
# row carries a `source` field ("bse" | "cninfo") so callers know the origin.


@_tool_safe
def get_bse_company(ticker_or_name: str) -> dict:
    """Resolve a BSE-listed company by 6-digit ticker (bse.cn).

    Returns: {stock_code, exchange, source, name} or {error}.
    """
    import bse_client

    row = bse_client.lookup_bse_company(ticker_or_name)
    if not row:
        return {"error": f"no BSE company matched: {ticker_or_name!r} (use a 6-digit BSE code)"}
    return row


@_tool_safe
def list_bse_filings(
    ticker_or_name: str,
    title: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 20,
) -> list[dict] | dict:
    """List a BSE-listed company's disclosures (BSE-native, CNINFO fallback).

    Each row carries ``source: "bse" | "cninfo"``. Returns: list of
    {announcement_id, title, form, published, pdf_url, stock_code, source} or
    {error}.
    """
    import bse_client

    company = bse_client.lookup_bse_company(ticker_or_name)
    if not company:
        return {"error": f"no BSE company matched: {ticker_or_name!r} (use a 6-digit BSE code)"}
    return bse_client.list_bse_filings(
        company["stock_code"], title=title, year=year, limit=limit,
    )


@_tool_safe
def get_bse_section(
    ticker_or_name: str,
    year: int,
    section: str,
) -> dict:
    """Extract a named section from a BSE company's annual-report PDF.

    The filing may be served from BSE or CNINFO (fallback); the result carries
    ``source`` so the caller knows the origin.

    Returns: {stock_code, year, section, pdf_url, source, outline_entry, text,
             char_count} or {error}.
    """
    import bse_client
    import report_cache

    company = bse_client.lookup_bse_company(ticker_or_name)
    if not company:
        return {"error": f"no BSE company matched: {ticker_or_name!r} (use a 6-digit BSE code)"}
    filing = bse_client.get_bse_annual_report_filing(company["stock_code"], year)
    if not filing or not filing.get("pdf_url"):
        return {
            "error": f"no annual report filing found for {company['stock_code']} year={year}",
            "stock_code": company["stock_code"],
        }
    pdf = filing["pdf_url"]
    text, _ = report_cache.get_or_fetch(
        pdf,
        stock_code=company["stock_code"],
        year=year,
        form="bse-annual",
        announcement_id=filing.get("announcement_id") or "",
    )
    outline = parse_outline(text)
    entry = resolve_selector(outline, section)
    if entry is None:
        return {
            "error": "no section matched selector",
            "available": [e["title"] for e in outline],
            "pdf_url": pdf,
            "source": filing.get("source") or "bse",
        }
    body = extract_section_text(text, outline, entry)
    return {
        "stock_code": company["stock_code"],
        "year": year,
        "section": section,
        "pdf_url": pdf,
        "source": filing.get("source") or "bse",
        "outline_entry": entry,
        "char_count": len(body),
        "text": body,
    }


# ── CSRC (中国证监会) official-website tools ──────────────────────
# Regulatory data CNINFO/exchanges do not cover: announcements, IPO / 并购重组
# review status, enforcement. HTML-parsed (lxml); endpoints undocumented.


@_tool_safe
def list_csrc_filings(
    category: Optional[str] = None,
    begin_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 20,
) -> list[dict] | dict:
    """List CSRC regulatory announcements/notices (csrc.gov.cn).

    Args:
        category: optional channel hint (informational).
        begin_date / end_date: optional ``YYYY-MM-DD`` post-filter.
        limit: max rows (default 20).

    Returns: list of {title, published, url, source} or {error}.
    """
    import csrc_client

    return csrc_client.list_csrc_filings(
        category, begin_date=begin_date, end_date=end_date, limit=limit,
    )


@_tool_safe
def get_csrc_ipo_review(company_or_code: str) -> dict:
    """Query CSRC IPO (首发) application review status for a company.

    Returns: {company, source, fields} (matching application row) or
             {company, source, error}. Endpoint undocumented - verify live.
    """
    import csrc_client

    return csrc_client.get_csrc_ipo_review(company_or_code)


@_tool_safe
def get_csrc_merger_review(company_or_code: str) -> dict:
    """Query CSRC 并购重组 (M&A) review status for a company.

    Returns: {company, source, fields} or {company, source, error}.
    """
    import csrc_client

    return csrc_client.get_csrc_merger_review(company_or_code)


@_tool_safe
def list_csrc_enforcement(
    begin_date: Optional[str] = None,
    limit: int = 20,
) -> list[dict] | dict:
    """List CSRC administrative-penalty / enforcement actions (csrc.gov.cn).

    Returns: list of {title, published, url, source} or {error}.
    """
    import csrc_client

    return csrc_client.list_csrc_enforcement(begin_date=begin_date, limit=limit)


# ── Ministry statistics (部级部门) tools ──────────────────────────
# Structured economic/financial statistics from NBS/MOF/PBoC/SAFE/GACC/NFRA,
# complementing fd-cn-gov's catalog-archive scraping with data queries.


@_tool_safe
def list_ministries() -> list[dict] | dict:
    """List the supported ministry statistics sources.

    Returns: list of {id, label, en, transport, base} or {error}.
    """
    import ministry_stats_client

    return ministry_stats_client.list_ministries()


@_tool_safe
def get_ministry_stat(
    ministry_id: str,
    url: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Fetch a ministry's statistics page and parse its HTML tables.

    Args:
        ministry_id: one of nbs/mof/pboc/safe/gacc/nfra (use get_nbs_stat for nbs).
        url: optional explicit stat-page URL (overrides the default).
        limit: max rows per table.

    Returns: {ministry, label, source, url, tables, table_count} or {error}.
    """
    import ministry_stats_client

    return ministry_stats_client.get_ministry_stat(ministry_id, url=url, limit=limit)


@_tool_safe
def get_nbs_stat(indicator_code: str, dbcode: str = "hgnd") -> dict:
    """Query an NBS (国家统计局) macro statistic by indicator code.

    Args:
        indicator_code: NBS indicator code (e.g. "A0201" for GDP).
        dbcode: NBS database code (default "hgnd" = national annual).

    Returns: {indicator, source, dbcode, data: {period: value}} or {error}.
    """
    import ministry_stats_client

    return ministry_stats_client.get_nbs_stat(indicator_code, dbcode=dbcode)
