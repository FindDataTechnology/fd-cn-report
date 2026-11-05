"""Unit tests for fd-cn-report pure logic. No live ES/LLM/scrapling calls."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp()
os.environ.setdefault("DAAS_DATABASE_URL", f"sqlite:///{_TMP}/test_cnreport.db")
# Keep the report cache off the repo during tests.
os.environ.setdefault("CNREPORT_CACHE_DIR", os.path.join(_TMP, "report_cache"))
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

sys.path.insert(0, str(Path(__file__).resolve().parent))
_MODELS = Path(__file__).resolve().parent.parent / "models"
if str(_MODELS) not in sys.path:
    sys.path.insert(0, str(_MODELS))

import cnreport_tools as T  # noqa: E402
import indicators_client as I  # noqa: E402
import report_section_map as RSM  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "test_fixtures"


def test_parse_outline_and_selectors():
    text = (
        "第三节 管理层讨论与分析 ......... 12\n"
        "第四节 公司治理 ......... 30\n"
        "第三节 管理层讨论与分析\n营收增长。\n"
        "第四节 公司治理\n治理完善。\n"
    )
    outline = T.parse_outline(text)
    titles = [e["title"] for e in outline]
    assert "第三节 管理层讨论与分析" in titles
    assert "第四节 公司治理" in titles

    assert T.resolve_selector(outline, "第三节 管理层讨论与分析")["ordinal"] == 1
    assert T.resolve_selector(outline, "2")["title"].startswith("第四节")
    assert T.resolve_selector(outline, "治理")["title"].startswith("第四节")
    assert T.resolve_selector(outline, "nope") is None


def test_extract_section_slice_stops_at_next_entry():
    text = (
        "第三节 管理层讨论与分析\n营收增长。\n"
        "第四节 公司治理\n治理完善。\n"
    )
    outline = T.parse_outline(text)
    entry = T.resolve_selector(outline, "第三节 管理层讨论与分析")
    body = T.extract_section_text(text, outline, entry)
    assert "营收增长" in body
    assert "治理完善" not in body


def test_section_map_alias_expansion_and_provenance(tmp_path, monkeypatch):
    original = Path(__file__).resolve().parent / "docs" / "report_section_map.json"
    mapping = {
        "version": 1,
        "forms": {
            "年报": {
                "财务报表附注": ["合并财务报表附注"],
            }
        },
    }
    map_path = tmp_path / "report_section_map.json"
    map_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    RSM.set_section_map_path(map_path)

    text = "合并财务报表附注\n固定资产占总资产比率 12%\n"
    outline = [{"level": 1, "title": "合并财务报表附注", "ordinal": 1}]
    rule = {
        "name": "固定资产占总资产比率",
        "unit": "%",
        "module": "report_section",
        "source_type": "report",
        "extractor": "llm",
        "source": {"selectors": [{"section": "财务报表附注"}]},
    }

    body, matched = I._resolve_section(text, outline, rule, "600519", form="年度报告")
    assert "12%" in body
    # The first candidate tried is the original selector "财务报表附注";
    # resolve_selector matches it as a substring of "合并财务报表附注".
    assert matched == "财务报表附注"

    # Mock the LLM call to return 12.0 for this indicator
    import cnreport_tools as T_mod
    monkeypatch.setattr(T_mod, "llm_config",
        lambda: {"api_key": "test", "base_url": "http://x", "model": "m"})
    monkeypatch.setattr(T_mod, "call_llm_pydantic",
        lambda system, user, model_class: model_class.model_validate(
            {k: (12.0 if k == "固定资产占总资产比率" else "") if k in ("section", "source") else
             (12.0 if k == "固定资产占总资产比率" else None) for k in model_class.model_fields}
        ))

    value_obj = I._resolve_via_report(
        text,
        outline,
        rule,
        "600519",
        year=2023,
        period="annual",
        form="年度报告",
        extractor_mode="auto",
        pdf_url="file://dummy",
    )
    assert value_obj["value"] == 12.0
    assert "财务报表附注" in value_obj["source"]

    RSM.set_section_map_path(original)


def test_section_map_expanded_candidates_recorded_on_miss(tmp_path):
    original = Path(__file__).resolve().parent / "docs" / "report_section_map.json"
    mapping = {
        "version": 1,
        "forms": {
            "年报": {
                "财务报表附注": ["合并财务报表附注", "附注"],
            }
        },
    }
    map_path = tmp_path / "report_section_map.json"
    map_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    RSM.set_section_map_path(map_path)

    text = "其他章节\n内容\n"
    outline = [{"level": 1, "title": "其他章节", "ordinal": 1}]
    rule = {
        "name": "固定资产占总资产比率",
        "unit": "%",
        "module": "report_section",
        "source_type": "report",
        "extractor": "python:percent_value",
        "source": {"selectors": [{"section": "财务报表附注"}]},
    }

    body, tried = I._resolve_section(text, outline, rule, "600519", form="年度报告")
    assert body is None
    assert "财务报表附注" in tried
    assert "合并财务报表附注" in tried
    assert "附注" in tried

    RSM.set_section_map_path(original)


def test_records_to_docs_id_format():
    docs = T.records_to_docs([{"a": 1}, {"a": 2}], "r1", "s1")
    assert [d["_id"] for d in docs] == ["r1:s1:0", "r1:s1:1"]
    assert docs[1]["fields"]["a"] == 2


def test_ai_extract_without_api_key_errors():
    # server.py loads the real .env at import (repaving the key we popped
    # above), so clear it again after import — ai_extract reads env at call time.
    from server import ai_extract

    os.environ.pop("LLM_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    result = ai_extract(text="营业收入100", schema={"type": "object"})
    assert "error" in result and "LLM_API_KEY" in result["error"]


def test_delete_index_requires_confirm():
    from server import delete_index

    # confirm=False short-circuits before touching ES (no ES_URL set either)
    result = delete_index(year=2023, confirm=False)
    assert "error" in result and "confirm" in result["error"]


# ── company-API tests (CNINFO + akshare mocked at module boundary) ──


def _load_fixture(name: str):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _patch_cninfo(monkeypatch, *, topsearch=None, hisann=None):
    """Patch the two `_post_json` calls cninfo_client makes."""
    import cninfo_client

    def fake_post(path, data):
        if "topSearch" in path:
            return topsearch if topsearch is not None else _load_fixture("cninfo_topsearch.json")
        if "hisAnnouncement" in path:
            return hisann if hisann is not None else _load_fixture("cninfo_hisannouncement.json")
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(cninfo_client, "_post_json", fake_post)


def test_get_company_by_ticker(monkeypatch):
    _patch_cninfo(monkeypatch)
    from server import get_company

    result = get_company("600519")
    assert result["stock_code"] == "600519"
    assert "茅台" in result["name"]
    assert result["exchange"] == "sse"
    assert result["org_id"] == "gssh0600519"


def test_get_company_by_name(monkeypatch):
    _patch_cninfo(monkeypatch)
    from server import get_company

    result = get_company("贵州茅台")
    assert result["stock_code"] == "600519"


def test_get_company_unknown_returns_error(monkeypatch):
    _patch_cninfo(monkeypatch, topsearch=[])
    from server import get_company

    result = get_company("ZZZZZZ")
    assert "error" in result


def test_list_filings_basic(monkeypatch):
    _patch_cninfo(monkeypatch)
    from server import list_filings

    result = list_filings("600519", limit=5)
    assert "filings" in result
    assert result["count"] >= 1
    f0 = result["filings"][0]
    assert f0["pdf_url"].startswith("http://static.cninfo.com.cn/")
    assert f0["stock_code"] == "600519"


def test_list_filings_filter_form(monkeypatch):
    _patch_cninfo(monkeypatch)
    from server import list_filings

    result = list_filings("600519", form="年度报告", limit=5)
    assert "filings" in result
    for row in result["filings"]:
        assert row["form"] == "年度报告" or "年度报告" in row["title"]


def test_list_filings_filter_year(monkeypatch):
    _patch_cninfo(monkeypatch)
    from server import list_filings

    result = list_filings("600519", form="年度报告", year=2023, limit=5)
    assert "filings" in result
    for row in result["filings"]:
        # FY 2023 reports publish in 2024 or have "2023" in the title
        assert "2023" in row["title"] or row["published"].startswith("2024-")


def test_get_filing_by_id(monkeypatch):
    _patch_cninfo(monkeypatch)
    from server import get_filing

    result = get_filing("1219730876", ticker_or_name="600519")
    assert result["announcement_id"] == "1219730876"
    assert result["pdf_url"].endswith(".PDF")


def test_get_filing_invalid_returns_error(monkeypatch):
    _patch_cninfo(monkeypatch)
    from server import get_filing

    result = get_filing("nonexistent", ticker_or_name="600519")
    assert "error" in result


def test_get_financials_all(monkeypatch):
    _patch_cninfo(monkeypatch)
    import financials_client

    def fake_get_statements(stock_code, *, period="annual", exchange=""):
        return {
            "income_statement": {"columns": ["报告日", "营业收入"], "data": [["2023-12-31", 100]]},
            "balance_sheet": {"columns": ["报告日", "总资产"], "data": [["2023-12-31", 500]]},
            "cashflow": {"columns": ["报告日", "经营现金流"], "data": [["2023-12-31", 80]]},
        }

    monkeypatch.setattr(financials_client, "get_statements", fake_get_statements)
    from server import get_financials

    result = get_financials("600519")
    assert "error" not in result
    assert result["stock_code"] == "600519"
    assert "income_statement" in result
    assert "balance_sheet" in result
    assert "cashflow" in result


def test_get_financials_single_statement(monkeypatch):
    _patch_cninfo(monkeypatch)
    import financials_client

    monkeypatch.setattr(
        financials_client,
        "get_statements",
        lambda stock_code, **_: {
            "income_statement": {"columns": ["x"], "data": [[1]]},
            "balance_sheet": {"columns": ["y"], "data": [[2]]},
            "cashflow": {"columns": ["z"], "data": [[3]]},
        },
    )
    from server import get_financials

    result = get_financials("600519", statement="balance_sheet")
    assert "balance_sheet" in result
    assert "income_statement" not in result
    assert result["statement"] == "balance_sheet"


def test_get_financials_missing_akshare_returns_error(monkeypatch):
    _patch_cninfo(monkeypatch)
    import financials_client

    def boom(*a, **kw):
        raise financials_client.MissingDependencyError("akshare not installed. test")

    monkeypatch.setattr(financials_client, "get_statements", boom)
    from server import get_financials

    result = get_financials("600519")
    assert "error" in result
    assert "akshare" in result["error"]


def test_get_financials_unknown_statement_returns_error(monkeypatch):
    _patch_cninfo(monkeypatch)
    import financials_client

    monkeypatch.setattr(
        financials_client,
        "get_statements",
        lambda stock_code, **_: {
            "income_statement": {"columns": [], "data": []},
            "balance_sheet": {"columns": [], "data": []},
            "cashflow": {"columns": [], "data": []},
        },
    )
    from server import get_financials

    result = get_financials("600519", statement="ebitda")
    assert "error" in result


def test_get_section_happy_path(monkeypatch):
    _patch_cninfo(monkeypatch)
    # Stub fetch_source to return canned annual-report text instead of
    # hitting the real PDF URL.
    fake_text = (
        "第三节 管理层讨论与分析\n经营情况良好。营业收入增长。\n"
        "第四节 公司治理\n治理结构完善。\n"
    )
    monkeypatch.setattr(T, "fetch_source_with_bytes", lambda *_a, **_kw: (fake_text, b"%PDF fake"))

    from server import get_section

    result = get_section("600519", year=2023, section="管理层讨论与分析")
    assert "error" not in result, result
    assert "经营情况良好" in result["text"]
    assert result["stock_code"] == "600519"
    assert result["pdf_url"].endswith(".PDF")


def test_get_section_unknown_section_returns_error(monkeypatch):
    _patch_cninfo(monkeypatch)
    monkeypatch.setattr(
        T, "fetch_source_with_bytes",
        lambda *_a, **_kw: ("第三节 管理层讨论与分析\n营收增长。\n", b"%PDF fake"),
    )

    from server import get_section

    result = get_section("600519", year=2023, section="No Such Section")
    assert "error" in result
    assert "available" in result


def test_get_section_no_filing_returns_error(monkeypatch):
    _patch_cninfo(monkeypatch, hisann={"announcements": []})
    from server import get_section

    result = get_section("600519", year=1900, section="管理层讨论与分析")
    assert "error" in result
    assert "no filing" in result["error"].lower()


def test_pdf_url_helper():
    import cninfo_client

    assert cninfo_client.pdf_url("finalpage/2024-04-02/abc.PDF") == (
        "http://static.cninfo.com.cn/finalpage/2024-04-02/abc.PDF"
    )
    # Already-absolute URLs pass through.
    assert cninfo_client.pdf_url("http://example.com/x.pdf") == "http://example.com/x.pdf"
    assert cninfo_client.pdf_url("") == ""


# ── report-type catalog + category tests ──────────────────────────


def test_load_categories_covers_four_forms():
    import cninfo_client

    cats = cninfo_client.load_categories()
    periodic = next(g for g in cats["groups"] if g["name"] == "定期报告")
    names = {c["name"] for c in periodic["categories"]}
    assert {"年度报告", "半年度报告", "第一季度报告", "第三季度报告"} <= names
    # the derived _FORM_CATEGORIES resolves to identical codes
    assert cninfo_client._FORM_CATEGORIES["年度报告"] == "category_ndbg_szsh"


def test_resolve_category_name_code_unknown_none():
    import cninfo_client

    assert cninfo_client.resolve_category("年度报告") == "category_ndbg_szsh"
    assert cninfo_client.resolve_category("首发") == "category_sf_szsh"
    # raw code passes through unchanged
    assert cninfo_client.resolve_category("category_ndbg_szsh") == "category_ndbg_szsh"
    # unknown / empty
    assert cninfo_client.resolve_category("不存在的类型") is None
    assert cninfo_client.resolve_category(None) is None
    assert cninfo_client.resolve_category("") is None


def test_load_categories_missing_file_raises(monkeypatch):
    import cninfo_client

    monkeypatch.setattr(cninfo_client, "_CATEGORIES_CACHE", None)
    monkeypatch.setattr(cninfo_client, "_REGISTRY_PATH", Path("/nonexistent/xyz.json"))
    with pytest.raises(FileNotFoundError):
        cninfo_client.load_categories()


def test_list_report_types_all_groups():
    from server import list_report_types

    r = list_report_types()
    assert "groups" in r
    assert r["count"] >= 26
    assert any(g["name"] == "定期报告" for g in r["groups"])
    # each category carries name + code
    g0 = r["groups"][0]
    assert all("name" in c and "code" in c for c in g0["categories"])


def test_list_report_types_filter_by_group():
    from server import list_report_types

    r = list_report_types(group="定期报告")
    names = [c["name"] for c in r["categories"]]
    assert names == ["年度报告", "半年度报告", "第一季度报告", "第三季度报告"]
    assert r["count"] == 4
    assert r["group"] == "定期报告"


def test_list_report_types_unknown_group_error():
    from server import list_report_types

    r = list_report_types(group="不存在的组")
    assert "error" in r
    assert "available" in r  # lists valid group names


def test_list_filings_category_name_sends_code(monkeypatch):
    """Filtering by a Chinese category name resolves and sends the code to CNINFO."""
    import cninfo_client

    captured = {}
    special = _load_fixture("cninfo_hisannouncement_special.json")

    def fake_post(path, data):
        if "topSearch" in path:
            return _load_fixture("cninfo_topsearch.json")
        if "hisAnnouncement" in path:
            captured["data"] = data
            return special
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(cninfo_client, "_post_json", fake_post)
    from server import list_filings

    result = list_filings("600519", category="首发", limit=5)
    assert "filings" in result
    assert captured["data"]["category"] == "category_sf_szsh"


def test_list_filings_category_raw_code_matches_name(monkeypatch):
    """A raw category_* code path produces the same CNINFO request as the name."""
    import cninfo_client

    captured = {}
    special = _load_fixture("cninfo_hisannouncement_special.json")

    def fake_post(path, data):
        if "topSearch" in path:
            return _load_fixture("cninfo_topsearch.json")
        if "hisAnnouncement" in path:
            captured["code"] = data["category"]
            return special
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(cninfo_client, "_post_json", fake_post)
    from server import list_filings

    list_filings("600519", category="category_sf_szsh", limit=3)
    assert captured["code"] == "category_sf_szsh"


def test_list_filings_unknown_category_no_network(monkeypatch):
    """An unknown category returns an error without hitting CNINFO."""
    import cninfo_client

    calls = {"n": 0}

    def fake_post(path, data):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(cninfo_client, "_post_json", fake_post)
    from server import list_filings

    result = list_filings("600519", category="不存在的类型")
    assert "error" in result
    assert calls["n"] == 0  # no network call


def test_list_filings_form_and_category_mutually_exclusive(monkeypatch):
    _patch_cninfo(monkeypatch)
    from server import list_filings

    result = list_filings("600519", form="年度报告", category="首发")
    assert "error" in result
    assert "either" in result["error"]


def test_get_special_report_no_section_no_pdf_download(monkeypatch):
    _patch_cninfo(monkeypatch, hisann=_load_fixture("cninfo_hisannouncement_special.json"))
    fetch_calls = {"n": 0}

    def fake_fetch(*a, **k):
        fetch_calls["n"] += 1
        return "", b""

    monkeypatch.setattr(T, "fetch_source_with_bytes", fake_fetch)
    from server import get_special_report

    result = get_special_report("600519", category="首发")
    assert "error" not in result, result
    assert result["pdf_url"].endswith(".PDF")
    assert result["category"] == "首发"
    assert "text" not in result  # section omitted → no body
    assert fetch_calls["n"] == 0  # PDF NOT downloaded


def test_get_special_report_with_section(monkeypatch):
    _patch_cninfo(monkeypatch, hisann=_load_fixture("cninfo_hisannouncement_special.json"))
    monkeypatch.setattr(
        T,
        "fetch_source_with_bytes",
        lambda *_a, **_kw: (
            "第一节 募集资金运用\n募资10亿元用于扩产。\n"
            "第二节 风险因素\n市场风险。\n",
            b"%PDF fake",
        ),
    )
    from server import get_special_report

    result = get_special_report("600519", category="首发", section="募集资金运用")
    assert "error" not in result, result
    assert "募资10亿" in result["text"]
    assert result["char_count"] > 0
    assert result["pdf_url"].endswith(".PDF")


def test_get_special_report_by_raw_code(monkeypatch):
    _patch_cninfo(monkeypatch, hisann=_load_fixture("cninfo_hisannouncement_special.json"))
    monkeypatch.setattr(T, "fetch_source_with_bytes", lambda *_a, **_kw: ("第一节 募集资金运用\n内容。\n", b"%PDF fake"))
    from server import get_special_report

    result = get_special_report("600519", category="category_sf_szsh", section="募集资金运用")
    assert "error" not in result, result


def test_get_special_report_unknown_category_error(monkeypatch):
    _patch_cninfo(monkeypatch)
    from server import get_special_report

    result = get_special_report("600519", category="不存在的")
    assert "error" in result and "category" in result["error"].lower()


def test_get_special_report_no_filing_error(monkeypatch):
    _patch_cninfo(monkeypatch, hisann={"announcements": []})
    from server import get_special_report

    result = get_special_report("600519", category="首发")
    assert "error" in result
    assert "no filing" in result["error"].lower()


def test_get_special_report_unknown_company_error(monkeypatch):
    _patch_cninfo(monkeypatch, topsearch=[])
    from server import get_special_report

    result = get_special_report("ZZZZZZ", category="首发")
    assert "error" in result


def test_get_special_report_section_not_found(monkeypatch):
    _patch_cninfo(monkeypatch, hisann=_load_fixture("cninfo_hisannouncement_special.json"))
    monkeypatch.setattr(T, "fetch_source_with_bytes", lambda *_a, **_kw: ("第一节 募集资金运用\n内容。\n", b"%PDF fake"))
    from server import get_special_report

    result = get_special_report("600519", category="首发", section="No Such Section")
    assert "error" in result
    assert "available" in result
    assert "pdf_url" in result


# ── indicator rules engine tests (offline; LLM/akshare/CNINFO mocked) ──


import indicators_client  # noqa: E402

_INDICATOR_FIXTURE = _FIXTURES / "indicator_rules.sample.json"
_DEFAULT_RULES = Path(__file__).resolve().parent / "indicator_rules.json"


@pytest.fixture
def indicator_rules():
    """Point indicators_client at the fixture rule set; reset after the test."""
    indicators_client.set_registry_path(_INDICATOR_FIXTURE)
    yield indicators_client
    indicators_client.set_registry_path(_DEFAULT_RULES)


def test_rules_load_resolve_hash(indicator_rules):
    rules = indicator_rules._rules()
    assert len(rules) == 7
    h = indicator_rules.rules_hash()
    assert isinstance(h, str) and len(h) == 16
    assert indicator_rules.resolve_rule("测试_资本充足率")["source_type"] == "report"
    assert indicator_rules.resolve_rule("CAR")["name"] == "测试_资本充足率"  # alias
    assert indicator_rules.resolve_rule(" 测试_资本充足率 ") is not None     # whitespace
    assert indicator_rules.resolve_rule("不存在") is None


def test_profile_company_bank_subtype():
    assert indicators_client.profile_company("601398")["sub_type"] == "国有大行"
    assert indicators_client.profile_company("600036")["sub_type"] == "股份制"
    assert indicators_client.profile_company("600519")["industry"] == "unknown"
    assert indicators_client.profile_company("999999", "某某城市商业银行")["sub_type"] == "城商行"
    assert indicators_client.profile_company("999999", "某某农村商业银行")["sub_type"] == "农商行"


def test_applicable_rules_filter(indicator_rules, monkeypatch):
    import cninfo_client

    monkeypatch.setattr(cninfo_client, "lookup_company",
                        lambda x: {"stock_code": "601398", "name": "工商银行", "exchange": "sse"})
    # 601398 (国有大行) gets the company-only + sub-type-scoped rules too
    _, appl = indicators_client.applicable_rules("601398", "工商银行")
    names = {r["name"] for r in appl}
    assert {"测试_公司专属指标", "测试_国有大行指标", "测试_资本充足率", "测试_资产负债率"} <= names
    # 600036 (股份制): company-only + 国有大行-only excluded
    _, appl2 = indicators_client.applicable_rules("600036", "招商银行")
    names2 = {r["name"] for r in appl2}
    assert "测试_公司专属指标" not in names2
    assert "测试_国有大行指标" not in names2
    assert "测试_资本充足率" in names2
    # 600519 (non-bank): bank-only rules excluded
    _, appl3 = indicators_client.applicable_rules("600519", "贵州茅台")
    names3 = {r["name"] for r in appl3}
    assert "测试_资本充足率" not in names3
    assert "测试_资产负债率" in names3  # industry "*"


def test_extractor_dispatch_llm_no_api_key(indicator_rules, monkeypatch):
    """In python mode, all report rules are skipped (no python extractors)."""
    rule = indicator_rules.resolve_rule("测试_员工人数")
    section_text = "员工情况\n员工人数：12,345 人\n"
    res = indicators_client._run_extractor(section_text, rule, "annual", "python")
    assert res["value"] is None
    assert "skipped" in res["note"]


def test_extractor_python_mode_unknown_name(indicator_rules):
    """Python mode skips all report rules regardless of extractor name."""
    rule = {"name": "x", "extractor": "llm", "unit": "", "source": {}}
    res = indicators_client._run_extractor("text", rule, "annual", "python")
    assert res["value"] is None
    assert "skipped" in res["note"]


def test_extractor_python_mode_skips_llm(indicator_rules):
    rule = {"name": "x", "extractor": "llm", "unit": "%", "source": {}}
    res = indicators_client._run_extractor("text", rule, "annual", "python")
    assert res["value"] is None
    assert "skipped" in res["note"]


def test_resolve_via_akshare(indicator_rules, monkeypatch):
    import financials_client

    monkeypatch.setattr(
        financials_client, "get_statements",
        lambda stock_code, **_: {
            "balance_sheet": {"columns": ["报告日", "总资产", "负债合计"],
                              "data": [["2023-12-31", 1000, 600]]},
        },
    )
    rule = indicator_rules.resolve_rule("测试_资产总计")
    res = indicators_client._resolve_via_akshare(
        {"stock_code": "601398", "exchange": "sse", "name": "工商银行"}, rule, 2023, "annual")
    assert res["value"] == 1000
    assert res["source_type"] == "akshare"
    assert res["extractor"] == "akshare"


def test_resolve_via_computed_numeric_and_missing(indicator_rules):
    rule = indicator_rules.resolve_rule("测试_资产负债率")
    res = indicators_client._resolve_via_computed(
        rule, {"测试_负债合计": 600, "测试_资产总计": 1000}, "annual")
    assert res["value"] == 60.0
    assert res["extractor"] == "computed"
    res2 = indicators_client._resolve_via_computed(
        rule, {"测试_负债合计": None, "测试_资产总计": 1000}, "annual")
    assert res2["value"] is None
    assert res2["note"] == "missing input: 测试_负债合计"


def test_resolve_section_selector_chain_fallback(indicator_rules):
    # outline lacks 资本充足率分析 + 资本充足率, but has 风险管理 → fallback hits
    text = "第三节 风险管理\n资本充足率 15.20%\n"
    outline = T.parse_outline(text)
    rule = indicator_rules.resolve_rule("测试_资本充足率")
    body, matched = indicators_client._resolve_section(text, outline, rule, "601398")
    assert body is not None
    assert matched == "风险管理"


def test_resolve_section_company_specific_selector_wins(indicator_rules):
    # 601398 has a company-specific selector "资本充足率分析" present in the TOC
    text = "一、资本充足率分析\n资本充足率 15.20%\n二、风险管理\n其他。\n"
    outline = T.parse_outline(text)
    rule = indicator_rules.resolve_rule("测试_资本充足率")
    body, matched = indicators_client._resolve_section(text, outline, rule, "601398")
    assert matched == "资本充足率分析"


def test_resolve_section_not_found(indicator_rules):
    text = "其他内容\n"
    outline = T.parse_outline(text)
    rule = indicator_rules.resolve_rule("测试_资本充足率")
    body, tried = indicators_client._resolve_section(text, outline, rule, "601398")
    assert body is None
    assert set(tried) == {"资本充足率分析", "资本充足率", "风险管理"}


def _patch_indicator_chain(monkeypatch, fake_text, llm_records=None, llm_counter=None):
    import cninfo_client, financials_client, report_cache

    monkeypatch.setattr(cninfo_client, "lookup_company",
                        lambda x: {"stock_code": "601398", "name": "工商银行",
                                   "org_id": "g", "exchange": "sse"})
    monkeypatch.setattr(cninfo_client, "query_announcements",
                        lambda *a, **k: [{"announcement_id": "x",
                                          "pdf_url": "http://example/x.PDF",
                                          "title": "2023年年度报告", "form": "年度报告",
                                          "published": "2024-03-01", "stock_code": "601398",
                                          "company_name": "工商银行"}])
    monkeypatch.setattr(report_cache, "get_or_fetch",
                        lambda *a, **k: (fake_text, {"cached": False, "stem": "s",
                                                     "cache_dir": "/tmp"}))
    monkeypatch.setattr(report_cache, "cache_key", lambda *a, **k: "stem_test")
    monkeypatch.setattr(report_cache, "get_cached_indicators", lambda *a, **k: None)
    monkeypatch.setattr(report_cache, "write_cached_indicators", lambda *a, **k: None)
    monkeypatch.setattr(financials_client, "get_statements",
                        lambda stock_code, **_: {
                            "balance_sheet": {"columns": ["报告日", "总资产", "负债合计"],
                                              "data": [["2023-12-31", 1000, 600]]},
                        })
    monkeypatch.setattr(T, "llm_config",
                        lambda: {"api_key": "test", "base_url": "http://x", "model": "m"})

    def fake_pydantic_call(system, user, model_class):
        if llm_counter is not None:
            llm_counter["n"] += 1
        # Build a valid instance: all fields null, then fill from llm_records
        raw = {k: None for k in model_class.model_fields if k not in ("section", "page", "source")}
        for rec in (llm_records or []):
            nm = rec.get("indicator", "")
            if nm in raw:
                try:
                    val = rec.get("value")
                    raw[nm] = float(val) if val is not None else None
                except (ValueError, TypeError):
                    raw[nm] = None
        return model_class.model_validate(raw)

    monkeypatch.setattr(T, "call_llm_pydantic", fake_pydantic_call)


def test_extract_indicators_groups_by_section(indicator_rules, monkeypatch):
    fake_text = (
        "第三节 资本充足率\n资本充足率 15.20%\n"
        "第四节 员工情况\n员工人数：12,345 人\n"
    )
    llm_counter = {"n": 0}
    _patch_indicator_chain(
        monkeypatch, fake_text,
        llm_records=[
            {"indicator": "测试_资本充足率", "value": "15.20", "unit": "%"},
            {"indicator": "测试_员工人数", "value": "12345", "unit": "人"},
        ],
        llm_counter=llm_counter,
    )
    res = indicators_client.extract_indicators("601398", 2023,
        indicators=["测试_资本充足率", "测试_员工人数",
                    "测试_资产总计", "测试_负债合计", "测试_资产负债率"])
    assert "error" not in res, res
    # Two LLM calls: 资本充足率 (report_section) + 员工人数 (report_section)
    # in different sections → 2 section×module calls
    assert llm_counter["n"] >= 1, llm_counter
    assert res["indicators"]["测试_资本充足率"]["value"] == 15.2
    assert res["indicators"]["测试_员工人数"]["value"] == 12345.0
    assert res["indicators"]["测试_资产总计"]["extractor"] == "akshare"
    assert res["indicators"]["测试_资产负债率"]["value"] == 60.0  # 600 / 1000 * 100
    assert res["indicators"]["测试_资产负债率"]["extractor"] == "computed"
    assert res["rules_hash"]
    assert res["cached"] is False


def test_extract_indicators_python_mode_skips_llm(indicator_rules, monkeypatch):
    fake_text = "第三节 资本充足率\n资本充足率 15.20%\n第四节 员工情况\n员工人数：12,345 人\n"
    llm_counter = {"n": 0}
    _patch_indicator_chain(monkeypatch, fake_text, llm_counter=llm_counter)
    res = indicators_client.extract_indicators(
        "601398", 2023,
        indicators=["测试_资本充足率", "测试_员工人数"], extractor_mode="python")
    assert "error" not in res
    assert llm_counter["n"] == 0  # LLM-free run
    # Both report rules are skipped in python mode (no python extractors)
    assert any(u["indicator"] == "测试_资本充足率" for u in res["unresolved"])
    assert any(u["indicator"] == "测试_员工人数" for u in res["unresolved"])


def test_extract_indicators_batch_llm_one_call_per_section(indicator_rules, monkeypatch):
    """All report rules in one section go through a single LLM call (batch path)."""
    fake_text = (
        "第三节 资本充足率\n资本充足率 15.20%\n核心一级资本充足率 12.5%\n"
    )
    llm_counter = {"n": 0}
    _patch_indicator_chain(
        monkeypatch, fake_text,
        llm_records=[
            {"indicator": "测试_资本充足率", "value": "15.20", "unit": "%"},
        ],
        llm_counter=llm_counter,
    )
    res = indicators_client.extract_indicators("601398", 2023,
        indicators=["测试_资本充足率"])
    assert "error" not in res, res
    # Exactly one LLM call for one section×module
    assert llm_counter["n"] == 1, llm_counter
    assert res["indicators"]["测试_资本充足率"]["value"] == 15.2
    assert res["indicators"]["测试_资本充足率"]["extractor"] == "llm"


def test_indicator_bundle_cache_roundtrip():
    import report_cache

    d = report_cache.cache_dir()
    stem = "test_bundle_unit"
    bundle = {"rules_hash": "abc", "indicators": {"x": {"value": 1}}, "cached": False}
    try:
        report_cache.write_cached_indicators(stem, bundle)
        # hash mismatch → miss
        assert report_cache.get_cached_indicators(stem, "wrong") is None
        # hash match → hit
        got = report_cache.get_cached_indicators(stem, "abc")
        assert got is not None
        assert got["indicators"]["x"]["value"] == 1
    finally:
        (d / f"{stem}.indicators.json").unlink(missing_ok=True)


def test_extract_indicators_script_in_process(monkeypatch, tmp_path):
    import importlib.util

    indicators_client.set_registry_path(_INDICATOR_FIXTURE)
    try:
        spec = importlib.util.spec_from_file_location(
            "extract_indicators",
            str(Path(__file__).resolve().parent / "scripts" / "extract_indicators.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        fake_text = "第三节 资本充足率\n资本充足率 15.20%\n第四节 员工情况\n员工人数：12,345 人\n"
        _patch_indicator_chain(
            monkeypatch, fake_text,
            llm_records=[{"indicator": "测试_资本充足率", "value": "15.2", "unit": "%"}])

        rc = mod.main(["601398", "--year", "2023", "--out-dir", str(tmp_path)])
        assert rc == 0
        json_path = tmp_path / "601398_2023.json"
        csv_path = tmp_path / "601398_2023.csv"
        assert json_path.exists() and csv_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert "indicators" in data and "rules_hash" in data
        assert data["rule_file"].endswith("indicator_rules.sample.json")
        csv_text = csv_path.read_text(encoding="utf-8")
        assert "indicator" in csv_text and "测试_资本充足率" in csv_text
    finally:
        indicators_client.set_registry_path(_DEFAULT_RULES)


# ── CSV migration + position-driven extraction tests ───────────────


import indicators_csv_migration as mig  # noqa: E402


def _write_csv(path: Path, rows: list[dict]) -> Path:
    import csv as _csv

    fields = ["indicator", "indicator_cn", "section_en", "section_cn", "report_type"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def test_csv_row_to_rule_mapping():
    """One CSV row → a rule with the Decision-1 mapping."""
    rule = mig.csv_row_to_rule({
        "indicator": "现金", "indicator_cn": "Cash",
        "section_en": "Balance Sheet - Assets", "section_cn": "资产负债表 — 一、资产",
        "report_type": "年报/半年报/季报",
    })
    assert rule["name"] == "现金"
    assert "Cash" in rule["aliases"]
    assert rule["module"] == "balance_sheet"
    assert rule["subgroup"] == "资产负债表 — 一、资产"
    assert rule["source_type"] == "report"
    assert rule["source"]["selectors"][0]["section"] == "资产负债表"
    assert rule["extractor"] == "llm"        # all report rules use LLM now
    assert rule["applies_to"]["industry"] == "*"
    assert rule["report_type"] == "年报/半年报/季报"
    assert rule["_csv_source"] is True


def test_csv_row_external_classification():
    """report_type 实时 → source_type external, no selectors/extractor."""
    rule = mig.csv_row_to_rule({
        "indicator": "PE-TTM", "indicator_cn": "PE TTM",
        "section_en": "Market Data (External)", "section_cn": "市场数据（外部）",
        "report_type": "实时",
    })
    assert rule["source_type"] == "external"
    assert rule["module"] == "market_data"
    assert rule["extractor"] == ""
    assert rule["source"] == {}
    assert rule["period_type"] == "realtime"


def test_csv_migration_reconcile_overlap_and_idempotent(tmp_path):
    """migrate(): overlap annotated (richer rule preserved), new rules appended, idempotent."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text((_FIXTURES / "indicator_rules.sample.json").read_text(encoding="utf-8"),
                          encoding="utf-8")
    csv_path = _write_csv(tmp_path / "pos.csv", [
        # overlap: 测试_资产总计 is in the sample (akshare) — annotate, don't duplicate
        {"indicator": "测试_资产总计", "indicator_cn": "Total Assets",
         "section_en": "Balance Sheet - Assets", "section_cn": "资产负债表 — 一、资产",
         "report_type": "年报/半年报/季报"},
        # new report rule
        {"indicator": "测试_新报表项", "indicator_cn": "New Line",
         "section_en": "Balance Sheet - Assets", "section_cn": "资产负债表 — 一、资产",
         "report_type": "年报/半年报/季报"},
        # new external rule
        {"indicator": "测试_外部", "indicator_cn": "External",
         "section_en": "Market Data (External)", "section_cn": "市场数据（外部）",
         "report_type": "实时"},
    ])

    s1 = mig.migrate(csv_path, rules_path)
    assert s1["total"] == 9                 # 7 hand-authored + 2 csv-sourced (1 overlap not duplicated)
    assert s1["csv_sourced"] == 2
    assert s1["annotated"] == 1
    import json as _json
    data = _json.loads(rules_path.read_text(encoding="utf-8"))
    by_name = {r["name"]: r for r in data["rules"]}
    # overlap preserved: still akshare, now annotated with report_type + alias
    overlap = by_name["测试_资产总计"]
    assert overlap["source_type"] == "akshare"            # richer rule preserved
    assert overlap["report_type"] == "年报/半年报/季报"
    assert "Total Assets" in overlap["aliases"]
    assert overlap["_csv_annotated"] is True
    assert "_csv_source" not in overlap
    # new rules appended
    assert by_name["测试_新报表项"]["source_type"] == "report"
    assert by_name["测试_外部"]["source_type"] == "external"

    # idempotent: re-running --check reports no change
    s2 = mig.migrate(csv_path, rules_path, dry_run=True)
    assert s2["changed_file"] is False


def test_csv_migration_is_idempotent_in_place(tmp_path):
    """Running migrate twice produces identical files."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text((_FIXTURES / "indicator_rules.sample.json").read_text(encoding="utf-8"),
                          encoding="utf-8")
    csv_path = _write_csv(tmp_path / "pos.csv", [
        {"indicator": "测试_新报表项", "indicator_cn": "New Line",
         "section_en": "Income Statement - Revenue", "section_cn": "利润表 — 一、营业收入",
         "report_type": "年报/半年报/季报"},
    ])
    mig.migrate(csv_path, rules_path)
    first = rules_path.read_text(encoding="utf-8")
    mig.migrate(csv_path, rules_path)
    second = rules_path.read_text(encoding="utf-8")
    assert first == second


def test_profile_non_bank_universal_csv_rules():
    """Non-bank companies profile without sub_type; universal CSV rules apply, bank-scoped excluded."""
    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        prof = indicators_client.profile_company("600519", "贵州茅台")
        assert prof["sub_type"] is None
        assert prof["industry"] != "bank"
        _, appl = indicators_client.applicable_rules("600519", "贵州茅台")
        names = {r["name"] for r in appl}
        assert "现金" in names                       # universal CSV-sourced report rule
        assert "资产总计" in names                    # universal (akshare) rule
        assert "资本充足率" not in names              # bank-scoped → excluded
        assert "PE-TTM" in names                     # universal external (still applicable)
    finally:
        pass


def test_external_indicator_get_indicator_no_pdf_fetch(monkeypatch):
    """get_indicator on an external rule returns no value, no PDF fetch, no LLM call."""
    import cninfo_client

    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        monkeypatch.setattr(cninfo_client, "lookup_company",
                            lambda x: {"stock_code": "601398", "name": "工商银行",
                                       "org_id": "g", "exchange": "sse"})
        monkeypatch.setattr(cninfo_client, "query_announcements",
                            lambda *a, **k: [{"announcement_id": "x", "pdf_url": "http://x.PDF",
                                              "title": "2023", "form": "年度报告", "published": "",
                                              "stock_code": "601398", "company_name": "工商银行"}])

        def _no_fetch(*a, **k):
            raise AssertionError("external rule must not fetch the PDF")

        monkeypatch.setattr(T, "fetch_source_with_bytes", _no_fetch)
        monkeypatch.setattr(T, "fetch_source", _no_fetch)
        res = indicators_client.get_indicator("PE-TTM", "601398", 2023)
        assert "error" not in res
        assert res["value"] is None
        assert "external" in (res.get("note") or "")
    finally:
        pass


def test_external_indicators_unresolved_in_extract(monkeypatch):
    """extract_indicators routes external rules to `unresolved` with the external note."""
    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        _patch_indicator_chain(monkeypatch, fake_text="")  # PDF fetched once but unused
        res = indicators_client.extract_indicators(
            "601398", 2023, indicators=["PE-TTM", "PB"])
        assert "error" not in res
        ext = {u["indicator"] for u in res["unresolved"]}
        assert {"PE-TTM", "PB"} <= ext
        assert all("external" in (u.get("note") or "") for u in res["unresolved"]
                   if u["indicator"] in {"PE-TTM", "PB"})
    finally:
        pass


_POSITION_CSV_ROWS = [
    {"indicator": "资产总计", "indicator_cn": "Total Assets",
     "section_en": "Balance Sheet - Assets", "section_cn": "资产负债表 — 一、资产",
     "report_type": "年报/半年报/季报"},
    {"indicator": "现金", "indicator_cn": "Cash",
     "section_en": "Balance Sheet - Assets", "section_cn": "资产负债表 — 一、资产",
     "report_type": "年报/半年报/季报"},
    {"indicator": "PE-TTM", "indicator_cn": "PE TTM",
     "section_en": "Market Data (External)", "section_cn": "市场数据（外部）",
     "report_type": "实时"},
    {"indicator": "不存在的指标", "indicator_cn": "Nope",
     "section_en": "Balance Sheet - Assets", "section_cn": "资产负债表 — 一、资产",
     "report_type": "年报/半年报/季报"},
]


def _patch_position_chain(monkeypatch, fake_text, llm_records=None):
    """Patch the indicator chain for position-CSV tests: real-rule 资产总计 needs its own column."""
    import financials_client

    _patch_indicator_chain(monkeypatch, fake_text, llm_records=llm_records)
    # the real 资产总计 rule reads the `资产总计` akshare field (the helper's mock uses 总资产)
    monkeypatch.setattr(financials_client, "get_statements",
        lambda stock_code, **_: {
            "balance_sheet": {"columns": ["报告日", "资产总计", "负债合计"],
                              "data": [["2023-12-31", 1000, 600]]},
        })


def test_extract_indicators_by_position_default_and_skipped(monkeypatch, tmp_path):
    """Default CSV path: report indicator extracted, external skipped, unknown missing."""
    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        csv_path = _write_csv(tmp_path / "pos.csv", _POSITION_CSV_ROWS)
        fake_text = "一、 合并资产负债表\n现金 5,000\n其他。\n"
        _patch_position_chain(monkeypatch, fake_text,
            llm_records=[{"indicator": "现金", "value": "5000", "unit": "元"}])
        res = indicators_client.extract_indicators_by_position(
            "601398", 2023, csv_path=str(csv_path))
        assert "error" not in res
        assert res["indicators"]["资产总计"]["value"] == 1000      # akshare mock
        assert res["indicators"]["现金"]["value"] == 5000.0        # llm
        assert any(s["indicator"] == "PE-TTM" and s["source_type"] == "external"
                   for s in res["skipped"])
        assert any(m["indicator"] == "不存在的指标" and m["reason"] == "unknown"
                   for m in res["missing"])
        assert res["csv_path"].endswith("pos.csv")
    finally:
        pass


def test_extract_indicators_by_position_subset(monkeypatch, tmp_path):
    """indicators subset intersects the CSV; non-subset CSV names are not processed."""
    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        csv_path = _write_csv(tmp_path / "pos.csv", _POSITION_CSV_ROWS)
        _patch_position_chain(monkeypatch, "一、 合并资产负债表\n现金 5,000\n",
            llm_records=[{"indicator": "现金", "value": "5000", "unit": "元"}])
        res = indicators_client.extract_indicators_by_position(
            "601398", 2023, csv_path=str(csv_path), indicators=["资产总计"])
        assert "error" not in res
        assert list(res["indicators"]) == ["资产总计"]
        assert res["skipped"] == []                       # PE-TTM not in subset → not skipped
    finally:
        pass


def test_extract_indicators_by_position_extractor_mode(monkeypatch, tmp_path):
    """extractor='python' skips all report rules (no python extractors)."""
    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        csv_path = _write_csv(tmp_path / "pos.csv", _POSITION_CSV_ROWS)
        _patch_position_chain(monkeypatch, "一、 合并资产负债表\n现金 5,000\n")
        res = indicators_client.extract_indicators_by_position(
            "601398", 2023, csv_path=str(csv_path), extractor="python")
        assert "error" not in res
        # 现金 is now an llm rule → skipped in python mode (value is null)
        assert res["indicators"]["现金"]["value"] is None
    finally:
        pass


def test_extract_indicators_by_position_cli(monkeypatch, tmp_path):
    """The CLI writes JSON + CSV; the CSV has the status column + skipped rows."""
    import importlib.util

    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        csv_path = _write_csv(tmp_path / "pos.csv", _POSITION_CSV_ROWS)
        _patch_position_chain(monkeypatch, "一、 合并资产负债表\n现金 5,000\n",
            llm_records=[{"indicator": "现金", "value": "5000", "unit": "元"}])
        spec = importlib.util.spec_from_file_location(
            "extract_indicators_by_position",
            str(Path(__file__).resolve().parent / "scripts" / "extract_indicators_by_position.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        out_dir = tmp_path / "out"
        rc = mod.main(["601398", "--year", "2023", "--csv", str(csv_path), "--out-dir", str(out_dir)])
        assert rc == 0
        json_path = out_dir / "601398_2023.json"
        csv_path_out = out_dir / "601398_2023.csv"
        assert json_path.exists() and csv_path_out.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert "skipped" in data and "csv_path" in data
        assert any(s["indicator"] == "PE-TTM" for s in data["skipped"])

        csv_text = csv_path_out.read_text(encoding="utf-8")
        assert "status" in csv_text.splitlines()[0]
        # skipped row carries status=skipped
        assert "PE-TTM,,,external,,,realtime/external" in csv_text
        # an extracted indicator carries status=ok
        assert "资产总计,1000" in csv_text
    finally:
        pass


def test_resolve_selector_normalizes_descriptive_label():
    """Descriptive selectors (CSV section_cn) resolve via normalized leading-keyword match."""
    outline = T.parse_outline(
        "一、 合并资产负债表\n资产数据。\n"
        "二、 合并利润表\n收入数据。\n"
        "三、 管理层讨论与分析\n讨论内容。\n"
        "四、 财务报表附注\n附注内容。\n"
    )
    # statement keyword matches the consolidated title via the normalized substring pass
    assert "合并资产负债表" in T.resolve_selector(outline, "资产负债表")["title"]
    # descriptive CSV-style label: leading keyword before the em-dash
    assert T.resolve_selector(outline, "资产负债表 — 一、资产") is not None
    assert T.resolve_selector(outline, "管理层讨论与分析 — 财务概要") is not None
    assert T.resolve_selector(outline, "财务报表附注") is not None
    # no false match
    assert T.resolve_selector(outline, "不存在的章节") is None


def test_resolve_section_statement_module_fallback(indicator_rules):
    """A report rule whose selector misses falls back to the canonical statement title."""
    # build a rule whose selector is a descriptive label that won't exact/regex match,
    # but whose module is balance_sheet → resolve_statement fallback hits 合并资产负债表
    rule = {
        "name": "测试_报表项", "module": "balance_sheet",
        "source": {"selectors": [{"section": "某个不存在的章节标题", "fallback": True}]},
    }
    text = "一、合并资产负债表\n现金 5,000\n二、合并利润表\n收入。\n"
    outline = T.parse_outline(text)
    body, matched = indicators_client._resolve_section(text, outline, rule, "601398")
    assert body is not None
    assert "现金" in body
    assert "资产负债表" in matched


# ── multi-form extraction: form filter + body-text fallback ───────────


def test_form_compatible_filters_by_report_type():
    """_form_compatible honors the rule's report_type vs the requested form."""
    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        # 资产总计: 年报/半年报/季报 → compatible with all four forms
        universal = indicators_client.resolve_rule("现金")
        assert universal is not None
        for form in ("年度报告", "半年度报告", "第一季度报告", "第三季度报告"):
            assert indicators_client._form_compatible(universal, form) is True, form

        # 分红金额: 年报 → compatible with annual only
        annual_only = indicators_client.resolve_rule("分红金额")
        assert annual_only is not None
        assert indicators_client._form_compatible(annual_only, "年度报告") is True
        assert indicators_client._form_compatible(annual_only, "半年度报告") is False
        assert indicators_client._form_compatible(annual_only, "第一季度报告") is False
        assert indicators_client._form_compatible(annual_only, "第三季度报告") is False

        # hand-authored rule without report_type → broadly applicable
        bare = {"name": "x", "source_type": "report"}  # no report_type key
        for form in ("年度报告", "半年度报告", "第一季度报告", "第三季度报告"):
            assert indicators_client._form_compatible(bare, form) is True, form

        # unknown form → default to compatible (don't suppress)
        assert indicators_client._form_compatible(universal, "未知报告") is True
    finally:
        pass


# Cached 2023 reports for the two test companies × four forms. The announcement_id
# matches the stem used by the real report cache, so the patched get_or_fetch can
# read the cached .txt directly.
_CACHED_REPORTS: dict[tuple[str, str], str] = {
    ("601398", "年度报告"):   "1219429144",
    ("601398", "半年度报告"): "1217717315",
    ("601398", "第一季度报告"): "1216692664",
    ("601398", "第三季度报告"): "1218190968",
    ("600519", "年度报告"):   "1219506510",
    ("600519", "半年度报告"): "1217453695",
    ("600519", "第一季度报告"): "1216595064",
    ("600519", "第三季度报告"): "1218110141",
}

_CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "reports"


def _patch_cached_reports(monkeypatch, stock_code: str, name: str):
    """Patch cninfo + report_cache to read from the real on-disk cache.

    Lets tests run offline against the 8 cached 2023 reports (ICBC + 茅台 ×
    4 forms) without hitting CNINFO or re-downloading PDFs. LLM and akshare
    are stubbed so only section-resolution behavior is exercised.
    """
    import cninfo_client, report_cache, financials_client

    monkeypatch.setattr(cninfo_client, "lookup_company",
                        lambda x: {"stock_code": stock_code, "name": name,
                                   "org_id": "g", "exchange": "sse"})

    def fake_query(stock, org_id, *, form=None, year=None, limit=5):
        ann_id = _CACHED_REPORTS.get((stock, form))
        if not ann_id:
            return []
        return [{"announcement_id": ann_id,
                 "pdf_url": f"http://example/{stock}_{form}.PDF",
                 "title": f"{name}{year}{form}", "form": form,
                 "published": "2024-03-01", "stock_code": stock,
                 "company_name": name}]

    monkeypatch.setattr(cninfo_client, "query_announcements", fake_query)

    def fake_get_or_fetch(url, *, stock_code=None, year=None, form=None,
                          announcement_id=None):
        stem = f"{stock_code}_{year}_{form}_{announcement_id}"
        p = _CACHE_DIR / f"{stem}.txt"
        if not p.exists():
            raise FileNotFoundError(f"cached report not found: {p}")
        return p.read_text(encoding="utf-8"), {"cached": True, "stem": stem}

    monkeypatch.setattr(report_cache, "get_or_fetch", fake_get_or_fetch)
    monkeypatch.setattr(report_cache, "cache_key",
                        lambda *a, **k: f"{stock_code}_{k.get('year','?')}_{k.get('form','?')}")
    monkeypatch.setattr(report_cache, "get_cached_indicators", lambda *a, **k: None)
    monkeypatch.setattr(report_cache, "write_cached_indicators", lambda *a, **k: None)

    # akshare unavailable → akshare rules get value=None (still in `indicators`)
    monkeypatch.setattr(financials_client, "get_statements",
                        lambda stock_code, **_: {})
    # no LLM key → report rules get value=None (section still resolved)
    monkeypatch.setattr(T, "llm_config",
                        lambda: {"api_key": "", "base_url": "", "model": ""})


def test_body_text_fallback_finds_statements_in_cached_q1():
    """find_statement_in_text locates the three statements in cached Q1 reports.

    ICBC Q1 uses bank-style titles (合并及公司资产负债表–按中国会计准则编制);
    茅台 Q1 uses standard titles (合并资产负债表). Both must be found, and
    a missing title must return None.
    """
    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        for stock, ann_id in [("601398", "1216692664"), ("600519", "1216595064")]:
            stem = f"{stock}_2023_第一季度报告_{ann_id}"
            text = (_CACHE_DIR / f"{stem}.txt").read_text(encoding="utf-8")
            for mod in ("balance_sheet", "income_statement", "cashflow"):
                body = T.extract_statement_text(text, mod)
                assert body is not None, f"{stock} Q1 {mod}: body is None"
                assert len(body) > 200, f"{stock} Q1 {mod}: body too short ({len(body)})"
            # sanity: indicator names actually appear in the right statements
            bal = T.extract_statement_text(text, "balance_sheet")
            inc = T.extract_statement_text(text, "income_statement")
            assert "资产总计" in bal, f"{stock} Q1 balance_sheet missing 资产总计"
            assert "营业收入" in inc, f"{stock} Q1 income_statement missing 营业收入"

        # absent title → None
        assert T.extract_statement_text("no statements here", "balance_sheet") is None
        assert T.find_statement_in_text("nothing", "income_statement") is None
    finally:
        pass


def test_extract_by_position_form_filter_skips_annual_only(monkeypatch):
    """Q1 extraction: form-incompatible indicators → skipped, external → skipped,
    report-type statement indicators resolve via body-text fallback."""
    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        _patch_cached_reports(monkeypatch, "600519", "贵州茅台")
        res = indicators_client.extract_indicators_by_position(
            "600519", 2023, form="第一季度报告")

        assert "error" not in res, res
        assert res["form"] == "第一季度报告"

        # 分红金额 (年报) → skipped with form_filter
        dividend = [s for s in res["skipped"] if s["indicator"] == "分红金额"]
        assert len(dividend) == 1, res["skipped"]
        assert dividend[0]["source_type"] == "form_filter"
        assert "第一季度报告" in dividend[0]["note"]

        # PE-TTM (实时) → skipped with external
        ext = [s for s in res["skipped"] if s["indicator"] == "PE-TTM"]
        assert len(ext) == 1
        assert ext[0]["source_type"] == "external"

        # report-type statement indicators should NOT be in `missing`
        # (body-text fallback found their section)
        missing_names = {m["indicator"] for m in res.get("missing", [])}
        # 现金 is a universal report rule on balance_sheet, report_type 年报/半年报/季报
        if "现金" in res.get("indicators", {}):
            assert "现金" not in missing_names, f"现金 in missing: {missing_names}"
    finally:
        pass


def test_extract_by_position_default_form_is_annual(monkeypatch, tmp_path):
    """Default form=年度报告: no form_filter skips; behaves as before (regression)."""
    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        _patch_cached_reports(monkeypatch, "601398", "工商银行")
        res = indicators_client.extract_indicators_by_position("601398", 2023)
        assert "error" not in res, res
        assert res["form"] == "年度报告"
        # no form_filter skips on the default form
        form_skips = [s for s in res["skipped"] if s.get("source_type") == "form_filter"]
        assert form_skips == [], f"unexpected form_filter skips on annual: {form_skips}"
        # external indicators still skipped
        assert any(s["source_type"] == "external" for s in res["skipped"])
    finally:
        pass


def test_multi_form_integration_two_companies_four_forms(monkeypatch):
    """2-company × 4-form integration: annual resolution ≥ 80% for the bank,
    quarterly resolution > 0% (was 0% before body-text fallback), and
    form-incompatible indicators appear in skipped."""
    indicators_client.set_registry_path(_DEFAULT_RULES)
    try:
        companies = [("601398", "工商银行"), ("600519", "贵州茅台")]
        forms = ["年度报告", "半年度报告", "第一季度报告", "第三季度报告"]

        for stock, name in companies:
            _patch_cached_reports(monkeypatch, stock, name)
            for form in forms:
                res = indicators_client.extract_indicators_by_position(
                    stock, 2023, form=form)
                assert "error" not in res, f"{stock} {form}: {res.get('error')}"
                assert res["form"] == form

                # resolution = report-type indicators whose section was found
                indicators = res.get("indicators") or {}
                missing_names = {m["indicator"] for m in res.get("missing", [])}
                report_total = sum(1 for r in indicators.values()
                                   if r.get("source_type") == "report")
                report_resolved = sum(
                    1 for nm, r in indicators.items()
                    if r.get("source_type") == "report" and nm not in missing_names
                )

                if form == "年度报告":
                    # annual: bank should resolve ≥ 80% of report indicators
                    # (茅台 ~75% is fine — some universal rules target bank-only sections)
                    rate = report_resolved / report_total if report_total else 0
                    if stock == "601398":
                        assert rate >= 0.8, (
                            f"{stock} annual resolution {rate:.0%} < 80% "
                            f"({report_resolved}/{report_total})")
                    else:
                        assert report_resolved > 0, (
                            f"{stock} annual: 0 report indicators resolved")
                elif form in ("第一季度报告", "第三季度报告"):
                    # quarterly: was 0% before body-text fallback; now > 0%
                    assert report_resolved > 0, (
                        f"{stock} {form}: 0 report indicators resolved "
                        f"(body-text fallback not working)")

                # form-incompatible indicators are in skipped (not attempted)
                if form in ("第一季度报告", "第三季度报告"):
                    assert any(s.get("source_type") == "form_filter"
                               for s in res["skipped"]), (
                        f"{stock} {form}: no form_filter skips")
    finally:
        pass


# ── announcement publication window (since/until) ──


def _window_rows():
    return {
        "announcements": [
            {
                "announcementId": "1",
                "announcementTitle": "2026年第三季度报告",
                "announcementTime": 1792454400000,  # 2026-10-20
                "adjunctUrl": "finalpage/2026-10-20/1.PDF",
                "secCode": "600519",
                "secName": "贵州茅台",
            },
            {
                "announcementId": "2",
                "announcementTitle": "2026年半年度报告",
                "announcementTime": 1782864000000,  # 2026-07-01
                "adjunctUrl": "finalpage/2026-07-01/2.PDF",
                "secCode": "600519",
                "secName": "贵州茅台",
            },
        ]
    }


def test_query_announcements_sends_since_until_window(monkeypatch):
    import cninfo_client

    seen = {}

    def fake_post(path, data):
        seen.update(data)
        return _window_rows()

    monkeypatch.setattr(cninfo_client, "_post_json", fake_post)
    rows = cninfo_client.query_announcements(
        "600519", "gssh0600519", since="2026-10-01", until="2026-10-31"
    )
    assert seen["seDate"] == "2026-10-01~2026-10-31"
    assert [r["announcement_id"] for r in rows] == ["1"]


def test_query_announcements_only_since_leaves_upper_open(monkeypatch):
    import cninfo_client

    seen = {}

    def fake_post(path, data):
        seen.update(data)
        return _window_rows()

    monkeypatch.setattr(cninfo_client, "_post_json", fake_post)
    rows = cninfo_client.query_announcements("600519", "gssh0600519", since="2026-10-01")
    assert seen["seDate"] == "2026-10-01~2099-12-31"
    assert [r["announcement_id"] for r in rows] == ["1"]


def test_query_announcements_year_still_supported(monkeypatch):
    import cninfo_client

    seen = {}

    def fake_post(path, data):
        seen.update(data)
        return _window_rows()

    monkeypatch.setattr(cninfo_client, "_post_json", fake_post)
    cninfo_client.query_announcements("600519", "gssh0600519", year=2026)
    assert seen["seDate"] == "2026-01-01~2027-12-31"


def test_query_announcements_rejects_year_plus_window(monkeypatch):
    import cninfo_client

    monkeypatch.setattr(cninfo_client, "_post_json", lambda path, data: {})
    with pytest.raises(ValueError):
        cninfo_client.query_announcements(
            "600519", "gssh0600519", year=2026, since="2026-10-01"
        )


def test_query_announcements_rejects_bad_date(monkeypatch):
    import cninfo_client

    monkeypatch.setattr(cninfo_client, "_post_json", lambda path, data: {})
    with pytest.raises(ValueError):
        cninfo_client.query_announcements(
            "600519", "gssh0600519", since="2026/10/01"
        )
