"""入仓语料的端到端烟测（openspec: industry-financial-report-rules 5.1 + 5.2）。

## 这条与 `test_golden_smoke.py` 的分工

`test_golden_smoke.py` 测**判定链**（`disclose_status` 的分档、锚文件合法性），
用仓内已有的 90 条银行锚，不需要语料。

本条测**语料本身**：入仓的每份报告文本里，锚文件声称的数**真的能被一字不差地取到**。
两者合起来才覆盖「有尺子 + 尺子能量到东西」。

## 语料是可增长的集合，不是一个文件

`tests/fixtures/golden/*.json` 每份是一个语料（一份报告的纯文本快照 + 若干人工核过的锚）。
本测试对**每个**锚文件跑同一组判据。现有两份：
- `600097_2025_q3`（季报；单季 vs 累计口径）
- `600467_2025_annual`（年报；本期 vs 上年同期口径）
新增语料只需把 .txt + .json 放进 fixtures/golden/，判据自动覆盖它。

## 为什么语料是 .txt 而不是 PDF

上市公司法定公开披露本身没有许可障碍。但 PDF 是二进制：进仓既不可 review
（谁改了哪个字节看不出来），也会让仓白白变大。真正要固化成回归网的，是
「**文本 → 数字**这一跳」——那正是抽取逻辑最容易悄悄坏的地方。所以入仓的是
同一份报告的纯文本快照（几 KB，逐字可读）+ 一页锚。

## 为什么锚里同一个指标有两个期间口径

「营业收入」在一份报告里出现两次：季报是「本报告期（单季）vs 年初至报告期末（累计）」，
年报是「本期 vs 上年同期」。拿错口径**不会报错，只会给出一个看起来合理的错数**——
这是这一族里最难发现的形态。锚把两个都记下来，就是为了让任何拿错口径的实现当场红。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "golden"
ANCHOR_FILES = sorted(FIXTURES.glob("*.json"))
ANCHOR_IDS = [p.stem for p in ANCHOR_FILES]


def _load(anchor_path: Path) -> dict:
    return json.loads(anchor_path.read_text(encoding="utf-8"))


def _text_path(anchor_path: Path, doc: dict) -> Path:
    # text_file 里记的是相对仓根的路径。anchor_path 在 tests/fixtures/golden/，
    # 上溯四级（golden→fixtures→tests→仓根）后拼相对路径。
    repo_root = anchor_path.resolve().parent.parent.parent.parent
    return (repo_root / doc["source"]["text_file"]).resolve()


def test_there_is_at_least_one_corpus():
    """空集合会让下面所有 parametrize 测试「零红」，那不是绿。"""
    assert ANCHOR_FILES, "tests/fixtures/golden/ 里没有任何 *.json 语料锚"


@pytest.mark.parametrize("anchor_path", ANCHOR_FILES, ids=ANCHOR_IDS)
def test_fixture_text_is_byte_identical_to_the_recorded_hash(anchor_path):
    """语料文件的 sha256 必须与锚文件里记的一致。

    文本一旦被人手改（哪怕只删一个空格），下面「取到某个数」的断言仍然可能通过，
    而它测的已经不是原来那份报告了。哈希把这个口子堵上。
    """
    doc = _load(anchor_path)
    text_path = _text_path(anchor_path, doc)
    assert text_path.is_file(), f"语料缺失：{text_path}"
    actual = hashlib.sha256(text_path.read_bytes()).hexdigest()
    assert actual == doc["source"]["sha256"], (
        "语料被改过（哈希不符）——若是有意更新，请同时更新锚文件里的 sha256 与 text_chars")
    assert len(text_path.read_text(encoding="utf-8")) == doc["source"]["text_chars"]


@pytest.mark.parametrize("anchor_path", ANCHOR_FILES, ids=ANCHOR_IDS)
def test_fixture_is_actually_public_and_not_a_secret(anchor_path):
    """语料里不许出现凭据形态。它是公开披露文本，进仓就没有后续闸再看它一眼。"""
    doc = _load(anchor_path)
    text = _text_path(anchor_path, doc).read_text(encoding="utf-8")
    for pat, why in (
        (r"(?i)\b(password|passwd|api[_-]?key|secret)\b\s*[:=]\s*\S+", "凭据赋值形态"),
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "私钥块"),
        (r"sk-[A-Za-z0-9]{20,}", "API key 形态"),
    ):
        assert not re.search(pat, text), f"语料里有{why}——公开披露文本不该带这个"


@pytest.mark.parametrize("anchor_path", ANCHOR_FILES, ids=ANCHOR_IDS)
def test_every_anchor_value_is_literally_present_in_the_text(anchor_path):
    """每一条锚的数值，都必须在入仓文本里逐字出现。

    这是「语料可用」的最小判据：如果连字符串都对不上，抽取链再怎么改都与这份语料无关。
    格式化规则与报表一致：千分位逗号 + 两位小数。
    """
    doc = _load(anchor_path)
    text = _text_path(anchor_path, doc).read_text(encoding="utf-8")
    assert doc["anchors"], "锚文件里没有锚"
    for a in doc["anchors"]:
        formatted = f"{a['value']:,.2f}"
        assert formatted in text, (
            f"锚 {a['indicator']} = {formatted} 在语料里找不到——锚与语料脱节了")


@pytest.mark.parametrize("anchor_path", ANCHOR_FILES, ids=ANCHOR_IDS)
def test_the_two_revenue_periods_are_distinct_in_the_source(anchor_path):
    """营业收入的两个期间口径必须是**两个不同的数**，且在文本里按顺序出现（本期在前）。

    若哪天有人「简化」语料或锚，把两个口径合并成一个，这条会红——
    而那正是最容易让抽取悄悄算错的地方。
    """
    doc = _load(anchor_path)
    text = _text_path(anchor_path, doc).read_text(encoding="utf-8")
    revs = [a for a in doc["anchors"] if a["indicator"] == "营业收入"]
    assert len(revs) == 2, "营业收入应有两个期间口径的锚"
    assert revs[0]["value"] != revs[1]["value"], "两个口径的值不该相同"
    i0 = text.find(f"{revs[0]['value']:,.2f}")
    i1 = text.find(f"{revs[1]['value']:,.2f}")
    assert i0 != -1 and i1 != -1
    assert i0 < i1, "报表里本期值应在上年同期值之前（表体顺序）"
