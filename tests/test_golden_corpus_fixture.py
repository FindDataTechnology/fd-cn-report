"""入仓语料的端到端烟测（openspec: industry-financial-report-rules 5.1 + 5.2）。

## 这条与 `test_golden_smoke.py` 的分工

`test_golden_smoke.py` 测**判定链**（`disclose_status` 的分档、锚文件合法性），
用仓内已有的 90 条银行锚，不需要语料。

本条测**语料本身**：入仓的那份季报文本里，锚文件声称的三个数**真的能被一字不差地取到**。
两者合起来才覆盖「有尺子 + 尺子能量到东西」。

## 为什么语料是一份 .txt 而不是 PDF

`600097` 2025 三季报是**上市公司法定公开披露**，本身没有许可障碍。但 PDF 是二进制：
进仓既不可 review（谁改了哪个字节看不出来），也会让仓大 190KB 而收益为零。
真正要固化成回归网的，是「**文本 → 数字**这一跳」——那正是抽取逻辑最容易悄悄坏的地方。
所以入仓的是同一份报告的纯文本快照（10KB，逐字可读）+ 一页锚。

## 为什么锚里同一个指标有两个期间口径

「营业收入」在季报里出现两次：本报告期（单季）与年初至报告期末（累计）。把单季值当成
累计值（或反之）不会报错，只会给出一个**看起来合理的错数**——这是这一族里最难发现的
形态。锚把两个都记下来，就是为了让任何拿错口径的实现当场红。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "golden"
ANCHOR_FILE = FIXTURES / "600097_2025_q3.json"


def _load():
    return json.loads(ANCHOR_FILE.read_text(encoding="utf-8"))


def test_fixture_text_is_byte_identical_to_the_recorded_hash():
    """语料文件的 sha256 必须与锚文件里记的一致。

    这条不是形式主义：文本一旦被人手改（哪怕只删一个空格），下面所有「取到 450,167,434.57」
    的断言仍然可能通过，而它测的已经不是原来那份报告了。哈希把这个口子堵上。
    """
    doc = _load()
    text_path = Path(__file__).resolve().parent.parent / doc["source"]["text_file"]
    assert text_path.is_file(), f"语料缺失：{text_path}"
    actual = hashlib.sha256(text_path.read_bytes()).hexdigest()
    assert actual == doc["source"]["sha256"], (
        "语料被改过（哈希不符）——若是有意更新，请同时更新锚文件里的 sha256 与 text_chars")
    assert len(text_path.read_text(encoding="utf-8")) == doc["source"]["text_chars"]


def test_fixture_is_actually_public_and_not_a_secret():
    """语料里不许出现凭据形态。它是公开披露文本，进仓就没有后续闸再看它一眼。"""
    doc = _load()
    text_path = Path(__file__).resolve().parent.parent / doc["source"]["text_file"]
    text = text_path.read_text(encoding="utf-8")
    for pat, why in (
        (r"(?i)\b(password|passwd|api[_-]?key|secret)\b\s*[:=]\s*\S+", "凭据赋值形态"),
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "私钥块"),
        (r"sk-[A-Za-z0-9]{20,}", "API key 形态"),
    ):
        assert not re.search(pat, text), f"语料里有{why}——公开披露文本不该带这个"


@pytest.mark.parametrize("idx", range(3))
def test_anchor_value_is_literally_present_in_the_text(idx):
    """每一条锚的数值，都必须在入仓文本里逐字出现。

    这是「语料可用」的最小判据：如果连字符串都对不上，抽取链再怎么改都与这份语料无关。
    格式化规则与年报一致：千分位逗号 + 两位小数。
    """
    doc = _load()
    text_path = Path(__file__).resolve().parent.parent / doc["source"]["text_file"]
    text = text_path.read_text(encoding="utf-8")
    a = doc["anchors"][idx]
    formatted = f"{a['value']:,.2f}"
    assert formatted in text, (
        f"锚 {a['indicator']} = {formatted} 在语料里找不到——锚与语料脱节了")


def test_the_two_revenue_periods_are_distinct_in_the_source():
    """营业收入的两个期间口径必须是**两个不同的数**，且在文本里按顺序出现。

    若哪天有人「简化」语料或锚，把两个口径合并成一个，这条会红——
    而那正是最容易让抽取悄悄算错的地方（单季 ↔ 累计）。
    """
    doc = _load()
    text_path = Path(__file__).resolve().parent.parent / doc["source"]["text_file"]
    text = text_path.read_text(encoding="utf-8")
    revs = [a for a in doc["anchors"] if a["indicator"] == "营业收入"]
    assert len(revs) == 2, "营业收入应有两个期间口径的锚"
    assert revs[0]["value"] != revs[1]["value"], "两个口径的值不该相同"
    i0 = text.find(f"{revs[0]['value']:,.2f}")
    i1 = text.find(f"{revs[1]['value']:,.2f}")
    assert i0 != -1 and i1 != -1
    assert i0 < i1, "季报里单季值应在累计值之前（表体顺序）"
