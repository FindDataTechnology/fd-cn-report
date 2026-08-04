"""Self-check for fd-cn-report — no framework, just asserts.

Run:  cd mcp/fd-cn-report && uv run python selfcheck.py

Covers:
  1. migrate creates the three tables.
  2. DB upserts are idempotent.
  3. parse_outline + selector resolution + section slicing.
  4. records_to_docs mapping.

Uses a temp DB so it never touches mcp/daas.db. No live ES/LLM/scrapling calls.
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp()
os.environ["DAAS_DATABASE_URL"] = f"sqlite:///{_TMP}/selfcheck.db"
# Keep the report cache off the repo during the self-check.
os.environ["CNREPORT_CACHE_DIR"] = os.path.join(_TMP, "report_cache")

sys.path.insert(0, str(Path(__file__).resolve().parent))
_MODELS = Path(__file__).resolve().parent.parent / "models"
if str(_MODELS) not in sys.path:
    sys.path.insert(0, str(_MODELS))

import cnreport_tools as T  # noqa: E402
from cnreport_database import get_db, make_report_id, reset_db  # noqa: E402


def check_db():
    db = get_db()
    rid = make_report_id("http://x/repo.pdf", "贵州茅台", 2023)
    db.upsert_document(rid, "http://x/repo.pdf", "贵州茅台", "600519", 2023, parse_status="ok")
    db.upsert_section(rid, 1, 1, "第三节 管理层讨论与分析", 500)
    # idempotent re-upsert
    db.upsert_section(rid, 1, 1, "第三节 管理层讨论与分析", 501)
    secs = db.list_sections(rid)
    assert len(secs) == 1, f"expected 1 section after re-upsert, got {len(secs)}"
    assert secs[0]["char_count"] == 501, "char_count not updated"
    db.upsert_es_index("cnreport-2023", 42, "abc123")
    assert db.list_es_indices()[0]["doc_count"] == 42
    print("  ✓ db: upsert document/section/es_meta idempotent")
    reset_db()


def check_outline():
    text = (
        "第三节 管理层讨论与分析 ......... 12\n"
        "一、经营情况 ........ 13\n"
        "（一）主营业务 ........ 14\n"
        "第四节 公司治理 ......... 30\n"
        "正文开始\n第三节 管理层讨论与分析\n经营情况良好。营业收入增长。\n"
        "一、经营情况\n细分业务上升。\n第四节 公司治理\n治理结构完善。\n"
    )
    outline = T.parse_outline(text)
    titles = [e["title"] for e in outline]
    assert "第三节 管理层讨论与分析" in titles, titles
    assert "第四节 公司治理" in titles, titles
    assert all("level" in e and "ordinal" in e for e in outline)

    # selector: exact, regex, ordinal
    e_exact = T.resolve_selector(outline, "第三节 管理层讨论与分析")
    e_regex = T.resolve_selector(outline, "管理层")
    e_ord = T.resolve_selector(outline, "1")
    assert e_exact and e_exact["title"].startswith("第三节 管理层")
    assert e_regex and e_regex["title"] == e_exact["title"]
    assert e_ord and e_ord["ordinal"] == 1
    assert T.resolve_selector(outline, "不存在的节") is None

    # section slicing: body between this entry and the next
    body = T.extract_section_text(text, outline, e_exact)
    assert "经营情况良好" in body, body
    assert "治理结构完善" not in body, "body leaked into next section"
    print("  ✓ outline: parse + selector(exact/regex/ordinal) + section slice")


def check_records_to_docs():
    docs = T.records_to_docs(
        [{"item": "营业收入", "amount": "100"}, {"item": "净利润", "amount": "20"}],
        report_id="rid",
        section_id="sec1",
    )
    assert len(docs) == 2
    assert docs[0]["_id"] == "rid:sec1:0"
    assert docs[1]["_id"] == "rid:sec1:1"
    assert docs[0]["fields"]["item"] == "营业收入"
    print("  ✓ records_to_docs: _id = report_id:section_id:seq")


def check_company_api():
    """Exercise the five new tools with mocked CNINFO + akshare."""
    import cninfo_client
    import financials_client

    _orig_post = cninfo_client._post_json
    _orig_get_stmts = financials_client.get_statements

    fixtures = Path(__file__).resolve().parent / "test_fixtures"
    import json as _json
    topsearch = _json.loads((fixtures / "cninfo_topsearch.json").read_text(encoding="utf-8"))
    hisann = _json.loads((fixtures / "cninfo_hisannouncement.json").read_text(encoding="utf-8"))

    def fake_post(path, data):
        if "topSearch" in path:
            return topsearch
        if "hisAnnouncement" in path:
            return hisann
        raise AssertionError(f"unexpected path: {path}")

    def fake_stmts(stock_code, *, period="annual", exchange=""):
        return {
            "income_statement": {"columns": ["报告日", "营业收入"], "data": [["2023-12-31", 100]]},
            "balance_sheet": {"columns": ["报告日", "总资产"], "data": [["2023-12-31", 500]]},
            "cashflow": {"columns": ["报告日", "经营现金流"], "data": [["2023-12-31", 80]]},
        }

    cninfo_client._post_json = fake_post
    financials_client.get_statements = fake_stmts

    try:
        # get_company
        co = T.get_company("600519")
        assert co["stock_code"] == "600519" and "茅台" in co["name"], co

        # list_filings
        filings = T.list_filings("600519", limit=3)
        assert isinstance(filings, list) and filings and filings[0]["pdf_url"], filings

        # get_filing
        f = T.get_filing("1219730876", ticker_or_name="600519")
        assert f["announcement_id"] == "1219730876", f

        # get_financials
        fin = T.get_financials("600519")
        assert "income_statement" in fin and "balance_sheet" in fin and "cashflow" in fin, fin

        # get_section — stub fetch_source_with_bytes (get_section now goes
        # through report_cache.get_or_fetch). Assert cache miss then hit.
        _calls = {"n": 0}
        _orig_fetch = T.fetch_source_with_bytes

        def fake_fetch(*_a, **_kw):
            _calls["n"] += 1
            return (
                "第三节 管理层讨论与分析\n经营情况良好。营业收入增长。\n"
                "第四节 公司治理\n治理结构完善。\n",
                b"%PDF fake",
            )

        T.fetch_source_with_bytes = fake_fetch
        try:
            sec = T.get_section("600519", year=2023, section="管理层讨论与分析")
            assert "经营情况良好" in sec.get("text", ""), sec
            assert _calls["n"] == 1, _calls  # cache miss → fetched once
            # second call → cache hit, no re-fetch
            sec2 = T.get_section("600519", year=2023, section="管理层讨论与分析")
            assert "经营情况良好" in sec2["text"], sec2
            assert _calls["n"] == 1, _calls  # still 1 — served from cache
        finally:
            T.fetch_source_with_bytes = _orig_fetch

        print("  ✓ company API: get_company / list_filings / get_filing / get_financials / get_section")
    finally:
        cninfo_client._post_json = _orig_post
        financials_client.get_statements = _orig_get_stmts


def check_catalog_and_special():
    """Exercise list_report_types, list_filings(category=…), and get_special_report.

    Routes the mocked hisAnnouncement response by `category`: the special
    fixture for 首发/category_sf_szsh, the annual fixture otherwise — so the
    special-report path is covered offline just like the company API.
    """
    import cninfo_client

    _orig_post = cninfo_client._post_json
    fixtures = Path(__file__).resolve().parent / "test_fixtures"
    import json as _json

    topsearch = _json.loads((fixtures / "cninfo_topsearch.json").read_text(encoding="utf-8"))
    hisann = _json.loads((fixtures / "cninfo_hisannouncement.json").read_text(encoding="utf-8"))
    hisann_special = _json.loads(
        (fixtures / "cninfo_hisannouncement_special.json").read_text(encoding="utf-8")
    )

    def fake_post(path, data):
        if "topSearch" in path:
            return topsearch
        if "hisAnnouncement" in path:
            if data.get("category") == "category_sf_szsh":
                return hisann_special
            return hisann
        raise AssertionError(f"unexpected path: {path}")

    cninfo_client._post_json = fake_post
    try:
        # list_report_types — all groups
        r = T.list_report_types()
        assert r["count"] >= 26 and any(g["name"] == "定期报告" for g in r["groups"]), r
        # list_report_types — one group
        r = T.list_report_types(group="定期报告")
        assert r["count"] == 4, r
        # list_filings(category=…) resolves 首发 and returns the special fixture
        rows = T.list_filings("600519", category="首发", limit=3)
        assert isinstance(rows, list) and rows and rows[0]["pdf_url"].endswith(".PDF"), rows
        # unknown category → error, no network call
        assert "error" in T.list_filings("600519", category="不存在的")
        # get_special_report — no section (no PDF download)
        r = T.get_special_report("600519", category="首发")
        assert "error" not in r and r["pdf_url"].endswith(".PDF"), r
        # get_special_report — with section (stub fetch_source_with_bytes;
        # path now goes through report_cache.get_or_fetch)
        _orig_fetch = T.fetch_source_with_bytes
        T.fetch_source_with_bytes = lambda *_a, **_kw: (
            "第一节 募集资金运用\n募资10亿。\n"
            "第二节 风险因素\n市场风险。\n",
            b"%PDF fake",
        )
        try:
            r = T.get_special_report("600519", category="首发", section="募集资金运用")
            assert "error" not in r and "募资10亿" in r["text"], r
        finally:
            T.fetch_source_with_bytes = _orig_fetch
        print("  ✓ catalog + special: list_report_types / list_filings(category) / get_special_report")
    finally:
        cninfo_client._post_json = _orig_post


def check_local_save():
    """Test CNREPORT_SAVE_DIR local file save (opt-in)."""
    import report_cache
    import cnreport_tools as T

    save_dir = os.path.join(_TMP, "local_save")
    os.environ["CNREPORT_SAVE_DIR"] = save_dir

    _orig_fetch = T.fetch_source_with_bytes
    T.fetch_source_with_bytes = lambda *_a, **_kw: (
        "第三节 管理层讨论与分析\n经营情况良好。\n",
        b"%PDF fake local save test",
    )
    try:
        # Clear cache to force a miss
        report_cache.clear_cache()
        text, info = report_cache.get_or_fetch(
            "http://example.com/test.pdf",
            stock_code="600519",
            year=2023,
            form="年度报告",
            announcement_id="test123",
        )
        assert "经营情况良好" in text
        stem = info["stem"]
        # Check local save: {save_dir}/{stock_code}/{stem}.pdf
        expected_path = Path(save_dir) / "600519" / f"{stem}.pdf"
        assert expected_path.exists(), f"local save missing: {expected_path}"
        assert expected_path.read_bytes() == b"%PDF fake local save test"
        print("  ✓ local save: CNREPORT_SAVE_DIR → {save_dir}/{stock_code}/{stem}.pdf")
    finally:
        T.fetch_source_with_bytes = _orig_fetch
        del os.environ["CNREPORT_SAVE_DIR"]


def check_minio_upload():
    """Test MinIO upload (opt-in, mocked)."""
    import report_cache
    import cnreport_tools as T

    os.environ["MINIO_UPLOAD_ENABLED"] = "true"
    os.environ["MINIO_ENDPOINT"] = "localhost:9000"
    os.environ["MINIO_ACCESS_KEY"] = "test"
    os.environ["MINIO_SECRET_KEY"] = "test"
    os.environ["MINIO_BUCKET"] = "test-bucket"
    os.environ["MINIO_SECURE"] = "false"

    # Mock minio.Minio to avoid real network call
    import sys
    from unittest.mock import MagicMock
    mock_minio = MagicMock()
    mock_minio.Minio.return_value.bucket_exists.return_value = True  # bucket exists
    sys.modules["minio"] = mock_minio

    _orig_fetch = T.fetch_source_with_bytes
    T.fetch_source_with_bytes = lambda *_a, **_kw: (
        "第三节 管理层讨论与分析\n经营情况良好。\n",
        b"%PDF fake minio test",
    )
    try:
        # Clear cache to force a miss
        report_cache.clear_cache()
        # Clear the lazy-init client
        if hasattr(report_cache._upload_minio, "_client"):
            delattr(report_cache._upload_minio, "_client")
        text, info = report_cache.get_or_fetch(
            "http://example.com/test2.pdf",
            stock_code="000001",
            year=2023,
            form="年度报告",
            announcement_id="test456",
        )
        assert "经营情况良好" in text
        # Check MinIO was called
        assert mock_minio.Minio.called, "Minio client not created"
        assert mock_minio.Minio.return_value.put_object.called, "put_object not called"
        call_args = mock_minio.Minio.return_value.put_object.call_args
        assert call_args[0][0] == "test-bucket"
        assert call_args[0][1].startswith("reports/")
        print("  ✓ MinIO upload: MINIO_UPLOAD_ENABLED=true → put_object called")
    finally:
        T.fetch_source_with_bytes = _orig_fetch
        for key in ["MINIO_UPLOAD_ENABLED", "MINIO_ENDPOINT", "MINIO_ACCESS_KEY",
                    "MINIO_SECRET_KEY", "MINIO_BUCKET", "MINIO_SECURE"]:
            os.environ.pop(key, None)
        del sys.modules["minio"]


def check_official_sources():
    """Non-failing live-endpoint ping for official-website datasource clients.

    Offline by default (the rest of selfcheck makes no live calls). Set
    ``CNREPORT_SELFCHECK_LIVE=1`` to actually ping each source's base
    endpoint; 4xx/5xx or errors are reported per source but NEVER fail the
    suite - they flag endpoints that need attention (design.md risk:
    undocumented/shifting exchange & government APIs). Each client module
    exposes ``ping() -> {ok, status_code, url}``; modules not yet implemented
    are reported as such.
    """
    sources = [
        ("SSE 上交所", "sse_client"),
        ("SZSE 深交所", "szse_client"),
        ("BSE 北交所", "bse_client"),
        ("CSRC 证监会", "csrc_client"),
        ("ministry stats", "ministry_stats_client"),
    ]
    if os.environ.get("CNREPORT_SELFCHECK_LIVE") != "1":
        print("  · official sources: skipped (set CNREPORT_SELFCHECK_LIVE=1 to ping live)")
        return
    import importlib

    for label, modname in sources:
        try:
            mod = importlib.import_module(modname)
        except ImportError:
            print(f"  · {label}: not implemented yet")
            continue
        try:
            r = mod.ping()
            if r.get("ok"):
                print(f"  ✓ {label}: {r.get('status_code')} {r.get('url')}")
            else:
                print(f"  ✗ {label}: {r.get('status_code')} {r.get('url')} (needs attention)")
        except Exception as e:  # noqa: BLE001 - non-failing ping
            print(f"  ✗ {label}: {type(e).__name__}: {e}")


def main():
    print("db checks:")
    check_db()
    print("outline checks:")
    check_outline()
    print("mapping checks:")
    check_records_to_docs()
    print("company-api checks:")
    check_company_api()
    print("catalog + special-report checks:")
    check_catalog_and_special()
    print("local-save checks:")
    check_local_save()
    print("MinIO-upload checks:")
    check_minio_upload()
    print("official-source checks:")
    check_official_sources()
    print("\nALL SELF-CHECKS PASSED")


if __name__ == "__main__":
    main()
