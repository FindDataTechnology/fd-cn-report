"""Coverage checks for industry/document_type rule readiness."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select

import cnreport_database
from cnreport_models import LlmRuleV2 as LlmRule, ScriptRule


def default_baseline_path() -> Path:
    return Path(__file__).resolve().parent / "docs" / "industry_indicator_baseline.json"


def load_baselines(path: str | Path | None = None) -> dict[str, list[str]]:
    p = Path(path) if path is not None else default_baseline_path()
    raw = json.loads(p.read_text(encoding="utf-8"))
    baselines = raw.get("baselines") if isinstance(raw, dict) else None
    if not isinstance(baselines, dict):
        raise ValueError("baseline file must contain top-level { baselines: {document_type: [indicators...] } }")
    out: dict[str, list[str]] = {}
    for dt, inds in baselines.items():
        if not isinstance(dt, str) or not dt.strip():
            continue
        if not isinstance(inds, list):
            continue
        out[dt.strip()] = [str(x).strip() for x in inds if str(x).strip()]
    return out


def _session():
    return cnreport_database.get_db().get_session()


def existing_llm_indicators(document_type: str) -> set[str]:
    """该 document_type 已有 LLM 规则的指标集合。

    2026-11-22 修：`llm_rules` 表在 v0.3.0（`00f27c8`）换成了 `LlmRuleV2` 形状 ——
    没有 `document_type` 列，改存 `document_type_codes`（JSON 数组，值是
    `cn_annual` 这种分档码，不是 `cn/801780/listed/annual-report` 这种全路径）。
    本模块当时没跟上，于是 `from cnreport_models import LlmRule` 直接 ImportError：
    **整条行业覆盖率链路（4.5 的产物、5.x 的回归）从那天起根本没跑过**。
    能一直看不出来，是因为这些脚本都不在 CI 里、只有人去手工跑时才会撞上。

    口径按 `document_type` 的**最后一段**换成分档 token 再与 `document_type_codes` 取交集；
    库里中文分档串（`年报/半年报/季报`，439/482 条）与新码（`cn_annual`）并存，两种都认。
    """
    dt = (document_type or "").strip()
    if not dt:
        return set()
    want = _form_tokens(dt)
    if not want:
        return set()
    out: set[str] = set()
    with _session() as session:
        rows = session.execute(select(LlmRule.indicator, LlmRule.document_type_codes)).all()
    for indicator, raw in rows:
        if not indicator or not raw:
            continue
        if _has_document_type(raw, dt) or (want & _normalize_codes(raw)):
            out.add(indicator)
    return out


#: document_type 的最后一段 → 该分档在 `llm_rules.document_type_codes` 里可能出现的写法
#:
#: 库里**两种形态并存**（2026-11-22 实测统计 482 条规则）：
#:   439 条 `年报/半年报/季报` · 20 条 `年报/半年报` · 12 条 `年报` · 8 条 `实时` · 3 条 `季报/半年报`
#: 都是**中文分档串**，不是 `cn_annual` 那种码。新写入的面（`scripts/seed_bank_regulatory_rules.py`）
#: 用的是 `cn_annual`。所以匹配必须是「规范化成 token 集合再取交集」，不能只认一种。
_FORM_TOKENS = {
    "annual-report": {"年报", "cn_annual", "annual"},
    "interim-report": {"半年报", "cn_interim", "interim"},
    "semi-annual-report": {"半年报", "cn_interim", "interim"},
    "half-year-report": {"半年报", "cn_interim", "interim"},
    "quarterly-report": {"季报", "cn_quarterly", "quarterly"},
}


def _form_tokens(document_type: str) -> set[str]:
    """该 document_type 对应的分档 token 集合（空集 = 认不出的报告期）。"""
    tail = document_type.rstrip("/").rsplit("/", 1)[-1].strip().lower()
    return _FORM_TOKENS.get(tail, set())


def _has_document_type(raw, document_type: str) -> bool:
    """`document_type_codes` 里是否含**这个完整 document_type**。

    库里存法有两族，这里都要认：
      · 全路径数组：`["cn/801780/listed/annual-report"]`（`upsert_llm_rule` 写的就是这个）
      · 分档串：`"年报/半年报/季报"` / `["cn_annual"]`（历史数据与 bank 线）
    只认分档串的话，逐行业写进去的规则对覆盖率**永远不可见**——2026-11-22 实测
    `upsert_llm_rule` 一条全路径规则后 `existing_llm_indicators` 仍返回空集。
    """
    dt = (document_type or "").strip()
    if not dt:
        return False
    v = raw
    for _ in range(3):
        if isinstance(v, str):
            try:
                v2 = json.loads(v)
            except ValueError:
                break
            if v2 == v:
                break
            v = v2
        else:
            break
    if isinstance(v, dict):
        v = list(v.values())
    if not isinstance(v, (list, tuple, set)):
        v = [v]
    return any(str(item).strip() == dt for item in v)


def _normalize_codes(raw) -> set[str]:
    """把 `document_type_codes` 的任何存法化成 token 集合。

    见过的三种存法：`["cn_annual"]`（JSON 数组）、`"年报/半年报/季报"`（中文串）、
    `"\"年报/半年报\""`（JSON 里套一层 JSON 的早期坏行）。都在这里摊平。
    """
    if raw is None:
        return set()
    v = raw
    for _ in range(3):                     # 最多剥三层引号/编码
        if isinstance(v, str):
            try:
                v2 = json.loads(v)
            except ValueError:
                break
            if v2 == v:
                break
            v = v2
        else:
            break
    if isinstance(v, dict):
        v = list(v.values())
    if not isinstance(v, (list, tuple, set)):
        v = [v]
    tokens: set[str] = set()
    for item in v:
        for piece in str(item).split("/"):
            piece = piece.strip()
            if piece:
                tokens.add(piece)
                tokens.add(piece.lower())
    return tokens


def existing_script_indicators(document_type: str) -> set[str]:
    """该 document_type 已有脚本规则的指标集合。

    2026-11-22 补：`script_rules.document_type` 也有**两种存法**（实测 5531 条）：
    大宗的 `年报/半年报/季报`（276 条那种中文分档串），以及逐 document_type 的全路径
    （`cn/801790/listed/annual-report`，每行业 30 条）。旧实现只比全路径，
    于是中文分档串那 276 条规则对任何 document_type 都不可见——与
    `existing_llm_indicators` 修掉的是同一类错（比法比产线窄）。
    """
    dt = (document_type or "").strip()
    if not dt:
        return set()
    want = _form_tokens(dt)
    out: set[str] = set()
    with _session() as session:
        rows = session.execute(select(ScriptRule.indicator, ScriptRule.document_type)).all()
    for indicator, raw in rows:
        if not indicator or not raw:
            continue
        stored = str(raw).strip()
        if stored == dt or (want & _normalize_codes(stored)):
            out.add(indicator)
    return out


@dataclass(frozen=True)
class CoverageReport:
    document_type: str
    declared: list[str]
    missing_llm_rules: list[str]
    missing_script_rules: list[str]

    @property
    def llm_ready(self) -> bool:
        return not self.missing_llm_rules

    @property
    def script_ready(self) -> bool:
        return not self.missing_script_rules

    @property
    def supported(self) -> bool:
        return self.llm_ready and self.script_ready


def _resolved_llm_names(document_type: str, declared: list[str]) -> set[str]:
    """`existing_llm_indicators` + 在**同一个库**里按别名/归一化再认一遍声明名。

    抽取侧是按 `indicators_client.resolve_rule`（精确 → 别名 → 归一化子串）找规则的，
    所以声明里的「净资产收益率」命中的是库里的「净资产收益率（ROE）」。覆盖率若只比
    裸名，会对 43/44 个 document_type 报「缺 净资产收益率」——那不是缺规则，是这道闸
    用了和产线不同的查找语义。

    ⚠ **别名解析必须在本库内做，不能借 `indicators_client.resolve_rule`**：
    那条路读 `rules_db` 自己的进程缓存，两者虽同源 `DAAS_DATABASE_URL`，但缓存
    （`_RULES_CACHE`）与 `cnreport_database` 的连接池是**两套生命周期**。2026-11-22
    实测：在空库上跑 `_resolved_llm_names` 仍返回 `{资产总计, 净利润}` —— 它拿真实库的
    规则给被替换的库背书，而那正是 `test_coverage_report_and_supported_flag` 一开跑就红的原因。
    两套真源比出来的「一致」不算一致。
    """
    have = existing_llm_indicators(document_type)
    want = _form_tokens(document_type)
    if not want or not declared:
        return have
    pending = [n for n in declared if n not in have]
    if not pending:
        return have
    with _session() as session:
        rows = session.execute(
            select(LlmRule.indicator, LlmRule.document_type_codes, LlmRule.aliases)
        ).all()
    for indicator, raw_codes, raw_aliases in rows:
        if not indicator or not (want & _normalize_codes(raw_codes)):
            continue
        accepted = {indicator, *_normalize_codes(raw_aliases)}
        for name in pending:
            if name in accepted or name == indicator or name in indicator:
                have.add(name)
    return have


def check_coverage(
    document_type: str,
    declared_indicators: Iterable[str],
) -> CoverageReport:
    declared = [str(x).strip() for x in declared_indicators if str(x).strip()]
    llm_have = _resolved_llm_names(document_type, declared)
    script_have = existing_script_indicators(document_type)
    missing_llm = [ind for ind in declared if ind not in llm_have]
    missing_script = [ind for ind in declared if ind not in script_have]
    return CoverageReport(
        document_type=document_type,
        declared=declared,
        missing_llm_rules=missing_llm,
        missing_script_rules=missing_script,
    )


def check_from_baselines(
    *,
    document_type: str,
    baseline_path: str | Path | None = None,
) -> CoverageReport:
    baselines = load_baselines(baseline_path)
    declared = baselines.get(document_type, [])
    return check_coverage(document_type, declared)

