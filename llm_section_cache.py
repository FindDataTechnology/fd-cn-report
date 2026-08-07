"""On-disk LLM section cache for fd-cn-report.

Persists the raw ``{records: [...]}`` response returned by
``cnreport_tools.call_llm_json`` so the same (PDF, section, period, rules hash)
is queried from the LLM at most once for any subset of indicators, across
runs, callers, and single-indicator entry points.

Cache layout::

    <cache_dir>/llm_sections/<key>.json

where ``<key>`` is a 32-char SHA1 hex digest of the inputs and the JSON body is
``{meta, records}``:

  {
    "meta": {
      "pdf_url": "...",
      "section_key": "...",
      "period": "annual",
      "rules_hash": "abcd1234",
      "cached_at": "2026-07-06T10:00:00Z"
    },
    "records": [
      {"indicator": "A", "value": 1, "unit": "元", "period": "annual"},
      ...
    ]
  }

The records list grows over time as different callers ask for different
indicators in the same section. ``get()`` returns the union; ``put()`` merges
in new records, deduping by normalized indicator name with the new values
winning on conflict.

Cache key scheme (see :func:`compute_key`):

  sha1( f"{pdf_url}|{section_key}|{period}|{rules_hash}" )[:32]

Changes in any of those fields invalidate the cache. ``report_cache.cache_dir``
is reused so the existing ``CNREPORT_CACHE_DIR`` env var and the no-network
test seam work without changes.

Env:
  LLM_SECTION_CACHE  - ``off`` disables the cache (default: enabled)
  CNREPORT_CACHE_DIR - shared with ``report_cache``; the LLM cache lives in
                       ``<dir>/llm_sections/``

No TTL — CNINFO reports are immutable; subset growth is handled by re-querying
the LLM only for the missing indicators and merging. Use
``LLM_SECTION_CACHE=off`` for a runtime kill switch.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_log = logging.getLogger("llm_section_cache")


def cache_dir() -> Path:
    """Return the LLM section cache directory, creating it on first use."""
    import report_cache

    d = report_cache.cache_dir() / "llm_sections"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _enabled() -> bool:
    """True unless ``LLM_SECTION_CACHE=off`` is set in the environment."""
    return os.environ.get("LLM_SECTION_CACHE", "").strip().lower() != "off"


def compute_key(
    pdf_url: str,
    section_key: str,
    period: str,
    rules_hash: str,
) -> str:
    """Return a 32-char SHA1 hex digest for the cache entry.

    The wanted set is intentionally **not** part of the key: a single section
    accumulates records across callers over time, so the cache stores the
    union and the caller computes the missing-subset locally.
    """
    payload = f"{pdf_url}|{section_key}|{period}|{rules_hash}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:32]


def cache_path(key: str) -> Path:
    """Return the JSON file path for ``key``."""
    return cache_dir() / f"{key}.json"


def _normalize_name(name: str) -> str:
    """Strip whitespace + common punctuation for tolerant Chinese name matching."""
    return re.sub(r"[\s　·、，,。.：:（）()\-_/]", "", str(name or ""))


def get(
    pdf_url: str,
    section_key: str,
    period: str,
    rules_hash: str,
) -> Optional[dict]:
    """Return the cached ``{meta, records}`` for the section, or ``None``.

    Returns ``None`` when the cache is disabled, the file is missing, the JSON
    is malformed, or the meta block doesn't match the requested key. The meta
    check guards against silent corruption and key collision.
    """
    if not _enabled():
        return None
    try:
        key = compute_key(pdf_url, section_key, period, rules_hash)
        path = cache_path(key)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _log.debug("llm_section_cache.get: read failure %s", e)
        return None

    if not isinstance(data, dict):
        return None
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        return None
    if meta.get("pdf_url") != pdf_url:
        return None
    if meta.get("section_key") != section_key:
        return None
    if meta.get("period") != period:
        return None
    if meta.get("rules_hash") != rules_hash:
        return None
    records = data.get("records")
    if not isinstance(records, list):
        return None
    return {"meta": meta, "records": records}


def put(
    pdf_url: str,
    section_key: str,
    period: str,
    rules_hash: str,
    records: list[dict],
) -> None:
    """Atomically write the cache entry, merging with any existing records.

    On a re-write, the new ``records`` are merged into the existing ones by
    normalized indicator name (the new value wins on conflict) and the merged
    set is persisted. This keeps the cache growing monotonically: a section
    fetched once for {A, B, C} can later be asked for {A, B, D} without
    losing the {A, B, C} records.

    Silently no-ops on any failure. Writes to a temp sibling then ``os.replace``
    to avoid partial reads.
    """
    if not _enabled():
        return
    try:
        key = compute_key(pdf_url, section_key, period, rules_hash)
        path = cache_path(key)
        existing = get(pdf_url, section_key, period, rules_hash)
        merged = list(records)
        if existing is not None:
            existing_by_norm: dict[str, dict] = {}
            for rec in (existing.get("records") or []):
                if isinstance(rec, dict):
                    nm = rec.get("indicator")
                    if nm:
                        existing_by_norm[_normalize_name(nm)] = rec
            new_by_norm: dict[str, dict] = {}
            for rec in records or []:
                if isinstance(rec, dict):
                    nm = rec.get("indicator")
                    if nm:
                        new_by_norm[_normalize_name(nm)] = rec
            for norm, rec in new_by_norm.items():
                existing_by_norm[norm] = rec
            ordered: list[dict] = []
            seen: set[str] = set()
            for rec in (existing.get("records") or []):
                if not isinstance(rec, dict):
                    continue
                nm = rec.get("indicator")
                if not nm:
                    continue
                norm = _normalize_name(nm)
                if norm in seen:
                    continue
                seen.add(norm)
                ordered.append(existing_by_norm[norm])
            # Append genuinely new records (indicators not previously cached)
            # so the cache actually grows as a superset, not just updates
            # existing rows. Without this, a partial-hit re-query for a new
            # indicator was silently dropped on write.
            for norm, rec in new_by_norm.items():
                if norm not in seen:
                    seen.add(norm)
                    ordered.append(rec)
            merged = ordered
        meta = {
            "pdf_url": pdf_url,
            "section_key": section_key,
            "period": period,
            "rules_hash": rules_hash,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        body = json.dumps({"meta": meta, "records": merged},
                          ensure_ascii=False, indent=2).encode("utf-8")
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError) as e:
        _log.debug("llm_section_cache.put: write failure %s", e)


def cached_subset(cached: dict, wanted_names: list[str]) -> list[dict]:
    """Return the records from ``cached`` matching ``wanted_names``.

    The returned list is in the order of ``wanted_names`` (skipping names that
    are not in the cache). The cache is treated as a superset: a record whose
    normalized name matches a wanted name is included.
    """
    if not cached:
        return []
    records_by_norm: dict[str, dict] = {}
    for rec in (cached.get("records") or []):
        if isinstance(rec, dict):
            nm = rec.get("indicator")
            if nm:
                records_by_norm[_normalize_name(nm)] = rec
    out: list[dict] = []
    for nm in wanted_names or []:
        rec = records_by_norm.get(_normalize_name(nm))
        if rec is not None:
            out.append(dict(rec))
    return out
