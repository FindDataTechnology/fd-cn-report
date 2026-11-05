"""CNINFO (巨潮资讯) HTTP JSON-API client.

Single network entry point for the fd-cn-report company API. Wraps three
public, keyless endpoints CNINFO uses to power its own SPA:

  /new/information/topSearch/query   — company lookup by ticker or name
  /new/hisAnnouncement/query         — list announcements (filings)
  static.cninfo.com.cn/<adjunctUrl>  — PDF download URL

Form categories (CNINFO codes) map from user-facing Chinese form names:
  年度报告      → category_ndbg_szsh
  半年度报告    → category_bndbg_szsh
  第一季度报告  → category_yjdbg_szsh
  第三季度报告  → category_sjdbg_szsh

Form categories (CNINFO codes) live in the data-driven registry
`cninfo_categories.json` (loaded via `load_categories`); the four periodic
forms are exposed as the `_FORM_CATEGORIES` dict, derived from that registry so
the existing `form` path resolves to identical codes. `resolve_category`
accepts either a Chinese name from the catalog or a raw `category_*` code.

Used by cnreport_tools.{get_company,list_filings,get_filing,get_section,
list_report_types,get_special_report}. Mock-friendly: tests monkeypatch
`_post_json` and `_client`, not httpx itself.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

import httpx

_BASE = "http://www.cninfo.com.cn"
_PDF_CDN = "http://static.cninfo.com.cn/"
_TIMEOUT = 30.0
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# ── data-driven CNINFO category registry ───────────────────────────
# Source of truth: cninfo_categories.json (sourced from CNINFO's own
# history-notice.js via akshare). Adding a report type = editing the JSON.
_REGISTRY_PATH = Path(__file__).resolve().parent / "cninfo_categories.json"
_CATEGORIES_CACHE: Optional[dict] = None

# User-facing form names that are aliases for registry category names that do
# not match verbatim (e.g. the prospectus is published as 首发 on CNINFO but
# exposed to callers as 招股说明书). `resolve_category` consults this map before
# scanning the registry groups.
_CATEGORY_ALIASES: dict[str, str] = {
    "招股说明书": "首发",
}


def load_categories() -> dict:
    """Load and cache the CNINFO category registry (cninfo_categories.json).

    Returns `{_source, _todo, groups: [{name, categories: [{name, code, description}]}]}`.
    Raises `FileNotFoundError` if the registry file is missing, `json.JSONDecodeError`
    if malformed — both naming the file, so a misconfigured package fails loudly at
    boot rather than silently degrading to an empty catalog.
    """
    global _CATEGORIES_CACHE
    if _CATEGORIES_CACHE is not None:
        return _CATEGORIES_CACHE
    if not _REGISTRY_PATH.exists():
        raise FileNotFoundError(f"CNINFO category registry not found: {_REGISTRY_PATH}")
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"malformed CNINFO category registry {_REGISTRY_PATH}: {e.msg}",
            e.doc,
            e.pos,
        ) from None
    _CATEGORIES_CACHE = data
    return data


def resolve_category(category: Optional[str]) -> Optional[str]:
    """Resolve a CNINFO category name or code to a canonical `category_*` code.

    Accepts either a Chinese name from the catalog (年度报告, 招股说明书, …) or a
    raw CNINFO code (category_ndbg_szsh). A raw `category_`-prefixed code is
    passed through unchanged (escape hatch for codes not yet in the registry).
    Returns `None` when the input is neither a known name nor a `category_` code.
    """
    if not category:
        return None
    if category.startswith("category_"):
        return category
    # Map user-facing aliases (e.g. 招股说明书) to the registry's canonical name
    # (首发) before scanning the groups.
    category = _CATEGORY_ALIASES.get(category, category)
    for group in load_categories().get("groups", []):
        for cat in group.get("categories", []):
            if cat.get("name") == category:
                return cat.get("code")
    return None


def _build_form_categories() -> dict[str, str]:
    """Derive the periodic-form name→code map from the registry.

    Covers the four periodic forms so the existing `form` path resolves to
    identical codes without a hardcoded dict. If the registry's 定期报告 group is
    ever renamed/missing, falls back to the historical four codes so the server
    still boots and existing `form` calls keep working.
    """
    fallback = {
        "年度报告": "category_ndbg_szsh",
        "半年度报告": "category_bndbg_szsh",
        "第一季度报告": "category_yjdbg_szsh",
        "第三季度报告": "category_sjdbg_szsh",
    }
    try:
        for group in load_categories().get("groups", []):
            if group.get("name") == "定期报告":
                return {cat["name"]: cat["code"] for cat in group.get("categories", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return fallback


# Map user-facing Chinese form names → CNINFO category codes (registry-derived).
_FORM_CATEGORIES = _build_form_categories()

# Map CNINFO `category` strings (returned by topSearch) to exchange tag.
_EXCHANGE_BY_PREFIX = {"sh": "sse", "sz": "szse", "bj": "bse"}


def _client() -> httpx.Client:
    """Build a per-call httpx client. Tests patch this to inject a mock."""
    return httpx.Client(
        base_url=_BASE,
        timeout=_TIMEOUT,
        headers={
            "User-Agent": _UA,
            "Accept": "application/json, text/plain, */*",
            "Origin": _BASE,
            "Referer": _BASE + "/",
        },
        follow_redirects=True,
    )


def _post_json(path: str, data: dict[str, Any]) -> Any:
    """POST form-encoded data and return parsed JSON. Errors raise."""
    with _client() as c:
        resp = c.post(path, data=data)
        resp.raise_for_status()
        return resp.json()


def _exchange_from_org_id(org_id: str) -> str:
    """gssh0600519 → sse; gssz0000001 → szse; gsbj0830799 → bse."""
    if not org_id or len(org_id) < 4:
        return ""
    tag = org_id[2:4]  # 'sh' / 'sz' / 'bj'
    return _EXCHANGE_BY_PREFIX.get(tag, "")


def _column_from_org_id(org_id: str) -> str:
    """The `column` parameter hisAnnouncement expects: sse/szse/bj."""
    ex = _exchange_from_org_id(org_id)
    return "bj" if ex == "bse" else ex  # bse → 'bj' for the API


def pdf_url(adjunct_url: str) -> str:
    """Build the static-cdn PDF URL CNINFO uses for filing downloads.

    `adjunct_url` is the path CNINFO returns in announcement rows
    (e.g. `finalpage/2024-04-02/1219730876.PDF`).
    """
    if not adjunct_url:
        return ""
    if adjunct_url.startswith("http"):
        return adjunct_url
    return _PDF_CDN + adjunct_url.lstrip("/")


def lookup_company(ticker_or_name: str) -> Optional[dict]:
    """Resolve a ticker or name fragment to a CNINFO company entry.

    Returns `{stock_code, name, name_en, org_id, exchange, category}` or
    `None` when no match is found. The match is the first row CNINFO's
    own search returns — same ranking the cninfo.com.cn UI shows.
    """
    if not ticker_or_name:
        return None
    payload = _post_json(
        "/new/information/topSearch/query",
        {"keyWord": ticker_or_name, "maxNum": "10"},
    )
    if not isinstance(payload, list) or not payload:
        return None
    # Prefer an exact stock_code match if the input is 6 digits.
    if ticker_or_name.isdigit() and len(ticker_or_name) == 6:
        for row in payload:
            if str(row.get("code")) == ticker_or_name:
                return _map_company_row(row)
    return _map_company_row(payload[0])


def _map_company_row(row: dict) -> dict:
    org_id = row.get("orgId") or ""
    return {
        "stock_code": row.get("code") or "",
        "name": row.get("zwjc") or row.get("pinyin") or "",
        "name_en": row.get("yjc") or "",
        "org_id": org_id,
        "exchange": _exchange_from_org_id(org_id),
        "category": row.get("category") or "",
    }


def query_announcements(
    stock_code: str,
    org_id: str,
    *,
    form: Optional[str] = None,
    category: Optional[str] = None,
    year: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Query CNINFO disclosures for a company, filtered by form/category and window.

    `form` accepts either a Chinese title (`年度报告`) or a raw category
    code (`category_ndbg_szsh`); anything else is sent as a free-text
    title filter (post-hoc, since CNINFO has no title-search field). The
    server-side `category` filter is only applied for the four periodic forms.
    `category` accepts any CNINFO category code or Chinese name from the
    catalog (`招股说明书`, `增发`, …) and is sent verbatim as the server-side
    `category` filter. `form` and `category` are mutually exclusive.
    `year` filters by announcement publication year window — note CN
    annual reports for FY{year} are typically published in {year+1}.

    `since`/`until` (`YYYY-MM-DD`) select an explicit publication window and
    take precedence over `year`; passing both is rejected rather than silently
    picking one. Rows outside the window are dropped post-hoc as a belt-and-
    braces over the server-side `seDate` filter.
    """
    if form and category:
        raise ValueError("specify either form or category, not both")
    if (since or until) and year is not None:
        raise ValueError("specify either year or since/until, not both")
    for name, value in (("since", since), ("until", until)):
        if value is not None and not _is_iso_date(value):
            raise ValueError(f"{name} must be YYYY-MM-DD, got {value!r}")
    if since and until and since > until:
        raise ValueError(f"since ({since}) must not be after until ({until})")

    page_size = max(1, min(int(limit) * 2 + 10, 50))  # over-fetch then post-filter

    data: dict[str, Any] = {
        "stock": f"{stock_code},{org_id}" if org_id else stock_code,
        "tabName": "fulltext",
        "pageSize": str(page_size),
        "pageNum": "1",
        "column": _column_from_org_id(org_id) or "sse",
        "plate": "",
        "searchkey": "",
        "secid": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }

    # Resolve the server-side `category` filter.
    if category is not None:
        category_code = resolve_category(category)
        if not category_code:
            raise ValueError(f"unknown CNINFO category: {category!r}")
        data["category"] = category_code
    else:
        category_code = _FORM_CATEGORIES.get(form or "", form or "")
        if category_code and category_code in _FORM_CATEGORIES.values():
            data["category"] = category_code

    if year is not None:
        # CN annual reports for FY{year} publish in {year+1}; widen window
        # so 半年报/季报 also catch their natural publish windows.
        data["seDate"] = f"{year}-01-01~{year + 1}-12-31"
    elif since or until:
        # Explicit publication window. Missing bound is left open on that side.
        data["seDate"] = f"{since or '2000-01-01'}~{until or '2099-12-31'}"

    payload = _post_json("/new/hisAnnouncement/query", data)
    rows = payload.get("announcements") or [] if isinstance(payload, dict) else []
    if rows is None:
        rows = []

    results: list[dict] = []
    for row in rows:
        mapped = _map_announcement_row(row)
        # Post-hoc form filter (form path only): belt-and-braces over CNINFO's
        # server-side `category` filter. Match by mapped["form"] when it's a
        # known Chinese name; fall back to title substring otherwise.
        if form:
            row_form = mapped.get("form") or ""
            row_title = mapped.get("title") or ""
            if form in _FORM_CATEGORIES:
                if row_form != form:
                    continue
            else:
                if form not in row_form and form not in row_title:
                    continue
        # Post-hoc year filter: periodic-report titles embed the fiscal year
        # (e.g. "2023年年度报告", "2023半年度报告"). Most titles use "{year}年",
        # but some banks omit the 年 between year and form ("2023半年度报告"),
        # so match the bare year string. The `category` path is skipped —
        # special-report titles rarely embed the year; rely on seDate there.
        if (
            year is not None
            and category is None
            and str(year) not in (mapped.get("title") or "")
        ):
            continue
        # Post-hoc window filter (belt-and-braces over server-side seDate).
        published = mapped.get("published") or ""
        if published:
            if since and published < since:
                continue
            if until and published > until:
                continue
        results.append(mapped)
        if len(results) >= limit:
            break
    return results


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_iso_date(value: str) -> bool:
    return bool(_ISO_DATE.match(value or ""))


def _form_from_title(title: str) -> str:
    """Derive a human-readable Chinese form name from the announcement title.

    CNINFO's `announcementType` field is an opaque, pipe-delimited code
    string (e.g. `01010503||010113||010301`) — not directly usable. The
    title, however, reliably contains the form name as a substring.
    Checks longest forms first so "半年度报告" wins over "年度报告".
    """
    if not title:
        return ""
    # Order matters: longer forms first. 招股说明书 (prospectus) is checked
    # alongside the periodic forms so IPO announcements map to their own form.
    for form in ("半年度报告", "第一季度报告", "第三季度报告", "年度报告", "招股说明书"):
        if form in title:
            return form
    return ""


def _map_announcement_row(row: dict) -> dict:
    published_ms = row.get("announcementTime") or 0
    try:
        from datetime import datetime, timezone

        published = (
            datetime.fromtimestamp(int(published_ms) / 1000, tz=timezone.utc)
            .strftime("%Y-%m-%d")
            if published_ms
            else ""
        )
    except Exception:
        published = ""
    title = row.get("announcementTitle") or ""
    return {
        "announcement_id": str(row.get("announcementId") or ""),
        "title": title,
        "form": _form_from_title(title),
        "published": published,
        "pdf_url": pdf_url(row.get("adjunctUrl") or ""),
        "stock_code": row.get("secCode") or "",
        "company_name": row.get("secName") or "",
    }


def get_announcement(
    announcement_id: str,
    *,
    stock_code: Optional[str] = None,
    org_id: Optional[str] = None,
) -> Optional[dict]:
    """Fetch a single announcement by id, narrowed by stock when supplied.

    CNINFO does not expose a `/announcement/<id>` endpoint, so this falls
    back to the listing endpoint over the company's full disclosure
    history and picks the matching row. With stock_code+org_id supplied,
    this is cheap; without, we must enumerate.
    """
    if stock_code and org_id:
        rows = query_announcements(stock_code, org_id, limit=200)
        for r in rows:
            if r["announcement_id"] == announcement_id:
                return r
    # Fallback: nothing to narrow by → bail.
    return None
