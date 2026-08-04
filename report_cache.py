"""On-disk cache for downloaded annual reports.

Wraps ``cnreport_tools.fetch_source_with_bytes`` so a repeated fetch (same
stock/year/form/announcement_id, or the same URL) reads from disk instead of
re-downloading and re-running ``pypdf``. The cache is transparent: callers
still receive the extracted text; on a miss the PDF + text + outline are
stored for next time.

Cache layout (one report = up to three files sharing a stem):

  <cache_dir>/<stem>.pdf           — raw PDF bytes (URL sources only)
  <cache_dir>/<stem>.txt           — extracted text (the expensive pypdf parse)
  <cache_dir>/<stem>.outline.json   — parsed outline snapshot (human-browseable)

Stem scheme (see ``cache_key``):

  {stock_code}_{year}_{form}_{announcement_id}  — convenience tools w/ provenance
  url_{sha1(url)[:16]}                           — raw URL without provenance
  (None)                                         — local-path sources, never cached

Env:
  CNREPORT_CACHE_DIR — override the cache directory
                       (default: ``mcp/fd-cn-report/.cache/reports/``)
  CNREPORT_SAVE_DIR  — optional user-visible directory for PDF save
                       (organized by stock_code: {save_dir}/{stock_code}/{stem}.pdf)
  MINIO_UPLOAD_ENABLED — "true" to enable MinIO upload (default: disabled)
  MINIO_ENDPOINT     — MinIO server endpoint (e.g., "localhost:9000")
  MINIO_ACCESS_KEY   — MinIO access key (default: "minioadmin")
  MINIO_SECRET_KEY   — MinIO secret key (default: "minioadmin")
  MINIO_BUCKET       — MinIO bucket name (default: "fd-cn-reports")
  MINIO_SECURE       — "true" for HTTPS (default: "false")

No TTL — CNINFO annual reports are immutable once published. Use
``clear_cache`` for manual eviction.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "reports"


def _save_local(raw: bytes, stem: str, stock_code: Optional[str] = None) -> None:
    """Save PDF to user-visible local directory (opt-in via CNREPORT_SAVE_DIR).

    Organized by stock_code when available: {save_dir}/{stock_code}/{stem}.pdf.
    Falls back to flat layout when stock_code is None. No-op when env var unset.
    """
    save_dir_raw = os.environ.get("CNREPORT_SAVE_DIR", "").strip()
    if not save_dir_raw:
        return
    save_dir = Path(save_dir_raw).expanduser()
    save_dir.mkdir(parents=True, exist_ok=True)
    if stock_code:
        target_dir = save_dir / stock_code
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = save_dir
    pdf_path = target_dir / f"{stem}.pdf"
    _atomic_write(pdf_path, raw)


def _upload_minio(raw: bytes, object_key: str) -> None:
    """Upload PDF to MinIO (opt-in via MINIO_UPLOAD_ENABLED=true).

    Lazy-init the Minio client on first upload. Auto-create bucket if missing.
    Non-critical: exceptions are caught and logged, never break the fetch flow.
    """
    if os.environ.get("MINIO_UPLOAD_ENABLED", "").lower() != "true":
        return
    endpoint = os.environ.get("MINIO_ENDPOINT", "").strip()
    if not endpoint:
        return
    try:
        from minio import Minio  # type: ignore[import-not-found]

        access_key = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
        secret_key = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
        secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"
        bucket = os.environ.get("MINIO_BUCKET", "fd-cn-reports")

        # Lazy-init client (not at import time)
        if not hasattr(_upload_minio, "_client"):
            _upload_minio._client = Minio(endpoint, access_key, secret_key, secure=secure)
        client = _upload_minio._client

        # Auto-create bucket if missing
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        # Upload
        import io
        client.put_object(bucket, object_key, io.BytesIO(raw), len(raw))
    except Exception as exc:
        # Non-critical: log but don't break the fetch flow
        import sys
        print(f"[report_cache] MinIO upload failed: {exc}", file=sys.stderr)


def cache_dir() -> Path:
    """Return the cache directory, creating it on first use."""
    raw = os.environ.get("CNREPORT_CACHE_DIR", "").strip()
    d = Path(raw) if raw else _DEFAULT_CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize(name: str) -> str:
    """Make a string safe to use as a filename component."""
    return name.replace("/", "_").replace("\\", "_").replace(":", "_").replace("\0", "")


def cache_key(
    source: Optional[str],
    stock_code: Optional[str] = None,
    year: Optional[int] = None,
    form: Optional[str] = None,
    announcement_id: Optional[str] = None,
) -> Optional[str]:
    """Return a filename stem for caching, or ``None`` when not cacheable.

    Provenance-keyed (preferred, human-browseable) when ``announcement_id`` is
    present; URL-hash fallback for raw URL sources; ``None`` for local paths.
    """
    if announcement_id:
        parts = [
            stock_code or "unknown",
            str(year) if year else "unknown",
            form or "report",
            announcement_id,
        ]
        return _sanitize("_".join(parts))
    if source and (source.startswith("http://") or source.startswith("https://")):
        return "url_" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]
    return None  # local path → never cache


def _atomic_write(path: Path, data: bytes, *, text: bool = False) -> None:
    """Write to a temp sibling then atomically rename, to avoid partial reads."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    if text:
        tmp.write_text(data.decode("utf-8") if isinstance(data, bytes) else data,
                       encoding="utf-8", errors="replace")
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)


def get_or_fetch(
    source: str,
    fetcher: str = "uv",
    *,
    stock_code: Optional[str] = None,
    year: Optional[int] = None,
    form: Optional[str] = None,
    announcement_id: Optional[str] = None,
) -> tuple[str, dict]:
    """Return ``(text, cache_info)`` for ``source``, caching when cacheable.

    ``cache_info = {"cached": bool, "stem": str|None, "cache_dir": str,
                    "enriched_outline": ..., "page_offsets": ...}``.
    On a hit the cached ``.txt`` is returned (no download, no pypdf). On a miss
    the PDF + text + outline + page offsets are written atomically. Local-path
    sources pass straight through to ``fetch_source`` with no cache write.
    """
    import cnreport_tools as T

    d = cache_dir()
    stem = cache_key(source, stock_code, year, form, announcement_id)
    if stem is None:
        text = T.fetch_source(source, fetcher)
        return text, {"cached": False, "stem": None, "cache_dir": str(d)}

    txt_path = d / f"{stem}.txt"
    enriched_path = d / f"{stem}.outline_enriched.json"
    offsets_path = d / f"{stem}.page_offsets.json"
    if txt_path.exists():
        try:
            text = txt_path.read_text(encoding="utf-8", errors="replace")
            info: dict = {"cached": True, "stem": stem, "cache_dir": str(d)}
            # load enriched cache artifacts (graceful if missing — older cache)
            if enriched_path.exists():
                try:
                    info["enriched_outline"] = json.loads(enriched_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            if offsets_path.exists():
                try:
                    info["page_offsets"] = json.loads(offsets_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            return text, info
        except Exception:
            pass  # corrupt cache file → fall through to re-fetch

    # miss → fetch, then store
    text, raw = T.fetch_source_with_bytes(source, fetcher)
    if raw is not None:
        _atomic_write(d / f"{stem}.pdf", raw)
        _save_local(raw, stem, stock_code)  # local save (opt-in)
        _upload_minio(raw, f"reports/{stem}.pdf")  # MinIO upload (opt-in)
        _save_local(raw, stem, stock_code)  # opt-in local save
        prefix = os.environ.get("MINIO_PREFIX", "reports/").strip()
        _upload_minio(raw, f"{prefix}{stem}.pdf")  # opt-in MinIO upload
    _atomic_write(d / f"{stem}.txt", text.encode("utf-8"))
    try:
        outline = T.parse_outline(text)
        _atomic_write(
            d / f"{stem}.outline.json",
            json.dumps(outline, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    except Exception:
        pass
    # enriched outline + page offsets (pymupdf-backed)
    enriched = None
    offsets = None
    if raw is not None:
        try:
            enriched, offsets, _ = T.build_enriched_outline(text, pdf_data=raw)
            _atomic_write(
                d / f"{stem}.outline_enriched.json",
                json.dumps(enriched, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            _atomic_write(
                d / f"{stem}.page_offsets.json",
                json.dumps(offsets, ensure_ascii=False).encode("utf-8"),
            )
        except Exception:
            pass  # non-critical — fall back to regular outline
    return text, {
        "cached": False,
        "stem": stem,
        "cache_dir": str(d),
        "enriched_outline": enriched,
        "page_offsets": offsets,
    }


def get_cached_indicators(stem: str, expected_rules_hash: str) -> Optional[dict]:
    """Return the cached indicator bundle for ``stem`` if its ``rules_hash`` matches.

    A bundle miss (no file) or a hash mismatch (rule set changed since the
    bundle was written) returns ``None`` so the caller re-extracts. The bundle
    is the ``{stem}.indicators.json`` artifact stored alongside the PDF/text/outline.
    """
    if not stem:
        return None
    d = cache_dir()
    path = d / f"{stem}.indicators.json"
    if not path.exists():
        return None
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if bundle.get("rules_hash") != expected_rules_hash:
        return None
    return bundle


def write_cached_indicators(stem: str, bundle: dict) -> None:
    """Atomically write the indicator bundle for ``stem``.

    The caller stamps ``generated_at`` and ``rules_hash`` on the bundle; this
    function only persists it. No-op when ``stem`` is ``None`` (uncacheable source).
    """
    if not stem:
        return
    d = cache_dir()
    _atomic_write(
        d / f"{stem}.indicators.json",
        json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8"),
    )


def _parse_stem(stem: str) -> dict:
    """Parse a provenance stem back into stock/year/form/announcement_id.

    ``url_*`` stems return ``{"kind": "url"}``. Provenance stems split as
    ``{stock}_{year}_{form}_{announcement_id}`` where ``form`` may itself
    contain underscores (re-joined from the middle).
    """
    if stem.startswith("url_"):
        return {"kind": "url", "stock_code": None, "year": None, "form": None,
                "announcement_id": None}
    parts = stem.split("_")
    if len(parts) >= 4:
        stock = parts[0]
        year_s = parts[1]
        ann_id = parts[-1]
        form = "_".join(parts[2:-1])
        year = None if year_s == "unknown" else year_s
        stock = None if stock == "unknown" else stock
        return {"kind": "provenance", "stock_code": stock, "year": year,
                "form": form, "announcement_id": ann_id}
    return {"kind": "unknown", "stock_code": None, "year": None, "form": None,
            "announcement_id": None}


def list_cache() -> dict:
    """List cached reports as ``{cache_dir, count, entries: [...]}``.

    Each entry carries the parsed provenance (stock/year/form/announcement_id
    or ``kind: url``), ``cached_at`` (file mtime, ISO-8601 UTC) and ``size``
    (sum of its ``.pdf`` + ``.txt`` + ``.outline.json``).
    """
    d = cache_dir()
    entries = []
    for txt_path in sorted(d.glob("*.txt")):
        if txt_path.suffix == ".tmp":
            continue
        stem = txt_path.stem
        entry = _parse_stem(stem)
        try:
            mtime = datetime.fromtimestamp(txt_path.stat().st_mtime, tz=timezone.utc)
            entry["cached_at"] = mtime.isoformat()
        except Exception:
            entry["cached_at"] = None
        size = 0
        for ext in (".pdf", ".txt", ".outline.json", ".indicators.json"):
            p = d / f"{stem}{ext}"
            if p.exists():
                size += p.stat().st_size
        entry["stem"] = stem
        entry["size"] = size
        entries.append(entry)
    return {"cache_dir": str(d), "count": len(entries), "entries": entries}


def clear_cache(
    stock_code: Optional[str] = None, year: Optional[int] = None
) -> dict:
    """Evict cached reports. Returns ``{removed, cache_dir}``.

    No args → evict everything. ``stock_code`` → only that company's entries.
    ``stock_code + year`` → only that company + year.
    """
    d = cache_dir()
    removed = 0
    for txt_path in list(d.glob("*.txt")):
        if txt_path.suffix == ".tmp":
            continue
        stem = txt_path.stem
        parsed = _parse_stem(stem)
        if stock_code is not None and parsed.get("stock_code") != stock_code:
            continue
        if year is not None and str(parsed.get("year")) != str(year):
            continue
        for ext in (".pdf", ".txt", ".outline.json", ".indicators.json",
                    ".pdf.tmp", ".txt.tmp", ".outline.json.tmp", ".indicators.json.tmp"):
            p = d / f"{stem}{ext}"
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        removed += 1
    return {"removed": removed, "cache_dir": str(d)}
