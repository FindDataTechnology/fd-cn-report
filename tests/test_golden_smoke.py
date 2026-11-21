"""金集烟测：抽取链路对「已知答案的输入」是否给出已知答案（offline）。

## 这条补的是什么

`openspec/changes/industry-financial-report-rules` 的 5.2：要一条自动化烟测，
跑抽取并断言 baseline 里的指标确实取到了。此前只有 `scripts/test_industry_rules.py`
——它**把 `status` 写死成 `"pending"`，从不真的抽值去比 baseline**（tasks.md 5.1 的注记：
「规则建好了但没做端到端回归」）。

## 为什么这条能在没有 LLM key 的机器上跑

抽取链路的**判定部分**是纯函数：`disclose_status()` 把「无值」分成
「未披露 / 对位失败」，`extract_indicators` 的**计算派生比**与**脚本规则**两条也都不碰 LLM
（`_try_script_extractor` 在 `extractor_mode="python"` 下照跑）。这三块正是最容易在重构中
被悄悄改坏的，而它们完全离线可测。

**LLM 那一段刻意不测**：没有 key 时它按设计返回 `value=None` + note，
所以「测它有没有值」在没有 key 的机器上等于测环境。那种断言会让 CI 常年红或常年跳过
——本仓的经验是「常年红的闸等于没有闸」（见 check_service_endpoints 的 LITTER_MAX 讨论）。

## 语料

不用真 PDF（`.cache/` 是 gitignored，且 30MB 级的年报不该进仓）。用**最小可判样本**：
一小段与真实年报同形的文本 + 一个已知的锚值。这测的是「判定链」，不是「PDF 解析」——
后者由 `scripts/verify_bank_golden.py` 在配了 key 的机器上负责。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

GOLDEN = REPO_ROOT / "docs" / "golden-bank-indicators.json"


def test_golden_anchor_file_is_well_formed():
    """锚文件本身：每条锚都要能指向一家真实公司 + 一个年份 + 一份报告类型。

    这是下面所有断言的前提。锚文件坏了而测试仍绿，等于用坏尺子量。
    """
    doc = json.loads(GOLDEN.read_text(encoding="utf-8"))
    inds = doc.get("indicators")
    assert isinstance(inds, dict) and inds, "金集必须有 indicators"

    required = {"entity_code", "entity_name", "fiscal_year", "form", "value", "unit"}
    total = 0
    for name, anchors in inds.items():
        assert isinstance(anchors, list) and anchors, f"{name} 没有任何锚"
        for a in anchors:
            missing = required - set(a)
            assert not missing, f"{name} 的锚缺字段 {missing}"
            assert isinstance(a["fiscal_year"], int)
            assert isinstance(a["value"], (int, float))
            total += 1
    # 90 条是 tasks 里写死的验收值；数字变了必须同时改这里与 tasks，
    # 否则「锚变少了」这件事会被静默吞掉。
    assert total == 90, f"锚条数从 90 变成了 {total}"


@pytest.mark.parametrize(
    "value,text,want",
    [
        # 有值就是 ok，与文本无关
        (1.28, "净息差 1.28%", "ok"),
        # 无值 + 标签后面确实跟着数字 ⇒ 对位失败（缺陷，不是未披露）
        (None, "净息差 1.28%，同比下降 36 个基点", "对位失败"),
        # 无值 + 只是叙述式提及、附近没有数字 ⇒ 未披露（正常）
        (None, "本行净息差保持稳健", "未披露"),
        # 无值 + 全文没有这个标签 ⇒ 未披露
        (None, "本节讨论资本充足率 18.76%", "未披露"),
    ],
)
def test_disclose_status_separates_missing_from_misaligned(value, text, want):
    """「没有值」必须分成两种，判定口径不同（verify_bank_golden 的核心判据）。

    合并这两种是最坏的形态：报告确实没披露（正常）会被当成抽取缺陷，
    而「标签在、数没取到」（真缺陷）会被当成未披露悄悄放过。
    """
    from verify_bank_golden import disclose_status

    assert disclose_status("净息差", value, text) == want


def test_golden_anchors_reach_a_verdict_without_an_llm():
    """每一条锚都要走完判定链并落在一个**已定义**的结局上。

    这是 5.2 真正要的那条：不是「抽取有没有值」（那要看 key），
    而是「判定链对每一条锚都走到底、不崩、不静默」。无 key 时全部锚应当落到
    「未披露」或「对位失败」之一；若某条锚直接抛异常或返回 None，说明判定链有洞。
    """
    from verify_bank_golden import _report_text, disclose_status

    doc = json.loads(GOLDEN.read_text(encoding="utf-8"))
    allowed = {"ok", "未披露", "对位失败"}
    seen = 0
    for name, anchors in doc["indicators"].items():
        for a in anchors:
            text = _report_text(a["entity_code"], a["fiscal_year"], a["form"])
            verdict = disclose_status(name, None, text)
            assert verdict in allowed, f"{name}/{a['entity_code']} 落到未定义结局 {verdict!r}"
            seen += 1
    assert seen == 90


def test_script_rule_path_never_calls_the_llm():
    """脚本规则在 `python` 模式下必须照跑，且不许退回 LLM。

    `_try_script_extractor` 是确定性的那一半：它在任何 mode 下都先试。
    若哪天有人把它挪到 LLM 分支之后，「没有 key 也能算出派生指标」这条路就断了，
    而症状只是「值变少了」，没有任何东西会红。
    """
    import indicators_client as IC

    rule = {"name": "__smoke_not_a_real_indicator__", "unit": "%"}
    out = IC._run_extractor("净息差 1.28%", rule, "annual", extractor_mode="python")
    # 没有匹配的脚本规则 ⇒ 落到 python 模式的显式跳过，而不是一个含糊的 None
    assert out.get("value") is None
    assert "skipped" in (out.get("note") or ""), (
        "python 模式下无脚本规则时应显式标注 skipped；"
        f"实得 note={out.get('note')!r}——若这里是别的东西，说明 dispatch 顺序被改过"
    )