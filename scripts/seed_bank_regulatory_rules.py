#!/usr/bin/env python
"""补齐银行监管指标缺失规则（awaken-banking-report-ingest 4.1）。

缺口实况（2026-11-08 查 daas.db）：`llm_rules` 已有 净息差 / 净利差 / 不良贷款率 /
拨备覆盖率 / 拨贷比 / 资本充足率 / 核心一级资本充足率 / 一级资本充足率 /
流动性覆盖率 / 四级迁徙率，**缺** 杠杆率、成本收入比、净稳定资金比例（NSFR）。
本脚本按既有范式（参照 id 3082 资本充足率：taxonomy_code + document_type_codes +
applies_to + position 段名选择器 + company 级选择器）补这三条。

position 全部取自**实测正文**，不是凭空写的段名（601398 FY2025 年报）：
  · "8.5.1 资本充足率及杠杆率情况" / "杠杆率7.51%"
  · 财务指标表内 "成本收入比（6）28.05 28.04 26.96"；正文 "成本收入比28.05%"
  · "2025 年四季度末，净稳定资金比例126.35%，比上季度末下降1.76 个百分点"

写入口径必须与**读取面**一致，而不是照抄坏行：`cnreport_models.LlmRuleV2.to_rule_dict`
对 applies_to / source / aliases / value_range 各只 `json.loads` **一次**，因此列里必须是
**单层编码**（存 `{"industry": ...}` 本身），document_type_codes 同样是单层数组。

⚠️ daas.db 现况是错的：全库 3392 条 applies_to 全是双重编码（存的是「一个 JSON 字符串」），
一次解码得到字符串，`indicators_client.applies_to()` 只认 `"*"/"null"/"None"` 这几个字符串，
于是**所有带真实行业范围的规则一律静默判 not applicable**，银行监管指标组 12 项全部命中此坑。
（`_resolve_section` 对 source 有防御性二次解析，所以 source 双层还能读；applies_to 没有。）
本脚本因此额外做一次 scoped 降层修复，见 `_collapse_one_level`。

幂等：(indicator, taxonomy_code, document_type_codes) 已存在则更新，不重复插入。

用法（fd-cn-report venv 或系统 python3，仅标准库）：
  python3 scripts/seed_bank_regulatory_rules.py --dry-run   # 只看差异
  python3 scripts/seed_bank_regulatory_rules.py             # 落库
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = _REPO.parent / "daas.db"  # finddata/daas.db

_ANNUAL_INTERIM = ["cn_annual", "cn_interim"]
_ANNUAL_INTERIM_QUARTER = ["cn_annual", "cn_interim", "cn_quarterly"]

#: 银行监管核心指标组（spec 12 项 + 本轮补齐 3 项）；修 NULL source 只在这个集内做
BANK_INDICATORS = [
    "净息差", "净利差", "不良贷款率", "不良贷款余额", "拨备覆盖率", "拨贷比",
    "资本充足率", "核心一级资本充足率", "一级资本充足率", "流动性覆盖率",
    "成本收入比", "正常类贷款迁徙率", "关注类贷款迁徙率", "次级类贷款迁徙率",
    "可疑类贷款迁徙率", "杠杆率", "净稳定资金比例",
]

#: 银行股公司级选择器：四大行段名与股份行不同，先按公司指路再按通用段名兜底
_BIG4 = ["601398", "601939", "601288", "601988"]


def _d(value) -> str:
    """单层 JSON 编码，与读取面（to_rule_dict 只解一层）对齐。"""
    return json.dumps(value, ensure_ascii=False)


#: 读取面只解一层，故需降层的 JSON 列
_JSON_COLS = ("applies_to", "source", "aliases", "value_range")


def _collapse_one_level(raw: str):
    """把双重编码的列值降成单层。

    返回 (new_raw, changed)。只有「解一层仍是 str、且再解一次合法」才降层，
    纯字符串（如 source 里的 "null"）和已单层的值原样保留。
    """
    if not raw:
        return raw, False
    try:
        once = json.loads(raw)
    except (TypeError, ValueError):
        return raw, False
    if not isinstance(once, str):
        return raw, False
    try:
        twice = json.loads(once)
    except (TypeError, ValueError):
        return raw, False  # 纯字符串，不是"编码套编码"
    return json.dumps(twice, ensure_ascii=False), True


RULES = [
    {
        "indicator": "杠杆率",
        "taxonomy_code": "balance_sheet",
        "document_type_codes": json.dumps(_ANNUAL_INTERIM, ensure_ascii=False),
        "indicator_zh": "杠杆率",
        "indicator_en": "Leverage Ratio",
        "applies_to": _d({"industry": "bank", "sub_types": ["*"],
                          "companies": ["*"], "exclude_companies": []}),
        "extractor": "llm",
        "source_type": "report",
        "unit": "%",
        "period_type": "annual",
        "value_range": _d(None),
        "aliases": _d(["LR", "Leverage Ratio", "杠杆率（监管）"]),
        "note": ("Bank regulatory leverage ratio (tier-1 capital / adjusted on- and "
                 "off-balance-sheet assets), disclosed alongside capital adequacy. "
                 "Not in akshare standard statements."),
        "direction": "higher_is_better",
        "position": json.dumps([
            {"company": _BIG4, "section": "资本充足率及杠杆率情况"},
            {"section": "资本充足率及杠杆率"},
            {"section": "杠杆率", "fallback": True},
            {"section": "风险管理", "fallback": True},
        ], ensure_ascii=False),
        "source": _d({
            "selectors": [
                {"company": _BIG4, "section": "资本充足率及杠杆率情况"},
                {"section": "资本充足率及杠杆率"},
                {"section": "杠杆率", "fallback": True},
            ],
            "extractor": "llm",
            "schema_hint": {"indicator": "杠杆率", "period": "本年", "unit": "%"},
        }),
    },
    {
        "indicator": "成本收入比",
        "taxonomy_code": "financial_ratios",
        "document_type_codes": json.dumps(_ANNUAL_INTERIM_QUARTER, ensure_ascii=False),
        "indicator_zh": "成本收入比",
        "indicator_en": "Cost-to-Income Ratio",
        "applies_to": _d({"industry": "bank", "sub_types": ["*"],
                          "companies": ["*"], "exclude_companies": []}),
        "extractor": "llm",
        "source_type": "report",
        "unit": "%",
        "period_type": "annual",
        "value_range": _d(None),
        "aliases": _d(["CIR", "Cost to Income Ratio", "成本收入比率"]),
        "note": ("Business and administrative expenses / operating income. Appears in "
                 "the financial-indicator table and in the business review narrative. "
                 "Lower is better (cost efficiency), unlike the other regulatory ratios."),
        "direction": "lower_is_better",
        "position": json.dumps([
            {"section": "财务指标"},
            {"section": "主要财务指标"},
            {"section": "成本收入比", "fallback": True},
            {"section": "经营情况讨论与分析", "fallback": True},
        ], ensure_ascii=False),
        "source": _d({
            "selectors": [
                {"section": "财务指标"},
                {"section": "主要财务指标"},
                {"section": "成本收入比", "fallback": True},
            ],
            "extractor": "llm",
            "schema_hint": {"indicator": "成本收入比", "period": "本年", "unit": "%"},
        }),
    },
    {
        "indicator": "净稳定资金比例",
        "taxonomy_code": "balance_sheet",
        "document_type_codes": json.dumps(_ANNUAL_INTERIM, ensure_ascii=False),
        "indicator_zh": "净稳定资金比例",
        "indicator_en": "Net Stable Funding Ratio",
        "applies_to": _d({"industry": "bank", "sub_types": ["*"],
                          "companies": ["*"], "exclude_companies": []}),
        "extractor": "llm",
        "source_type": "report",
        "unit": "%",
        "period_type": "annual",
        "value_range": _d(None),
        "aliases": _d(["NSFR", "Net Stable Funding Ratio", "净稳定资金比率"]),
        "note": ("Available stable funding / required stable funding, disclosed in the "
                 "liquidity-risk section (often quoted as a quarter-end value, e.g. "
                 "'2025 年四季度末，净稳定资金比例126.35%')."),
        "direction": "higher_is_better",
        "position": json.dumps([
            {"section": "流动性风险"},
            {"section": "净稳定资金比例"},
            {"section": "流动性风险管理", "fallback": True},
            {"section": "风险管理", "fallback": True},
        ], ensure_ascii=False),
        "source": _d({
            "selectors": [
                {"section": "流动性风险"},
                {"section": "净稳定资金比例"},
                {"section": "风险管理", "fallback": True},
            ],
            "extractor": "llm",
            "schema_hint": {"indicator": "净稳定资金比例", "period": "本年", "unit": "%"},
        }),
    },
]


def _instruction(rule: dict) -> str:
    """与既有行一致：把 note / aliases / source 拼进 instruction 尾部。"""
    aliases = json.loads(rule["aliases"])
    return (f"{rule['note']} | aliases: {', '.join(aliases)} | "
            f"source: {json.loads(rule['source'])}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"DB 不存在：{db}")

    conn = sqlite3.connect(str(db), timeout=30)
    conn.row_factory = sqlite3.Row
    inserted = updated = repaired = collapsed = 0
    try:
        for rule in RULES:
            row = conn.execute(
                "SELECT id FROM llm_rules WHERE indicator = ? AND taxonomy_code = ? "
                "AND document_type_codes = ?",
                (rule["indicator"], rule["taxonomy_code"], rule["document_type_codes"]),
            ).fetchone()
            payload = dict(rule, instruction=_instruction(rule))
            cols = list(payload)
            if row is None:
                print(f"[insert] {rule['indicator']} ({rule['taxonomy_code']})")
                if not args.dry_run:
                    conn.execute(
                        f"INSERT INTO llm_rules ({', '.join(cols)}) "
                        f"VALUES ({', '.join('?' for _ in cols)})",
                        [payload[c] for c in cols],
                    )
                inserted += 1
            else:
                print(f"[update] {rule['indicator']} -> id={row['id']}")
                if not args.dry_run:
                    sets = ", ".join(f"{c} = ?" for c in cols)
                    conn.execute(f"UPDATE llm_rules SET {sets} WHERE id = ?",
                                 [payload[c] for c in cols] + [row["id"]])
                updated += 1

        # 修 NULL source：`_resolve_section` 对 source=NULL 的规则会在
        # `src.get("selectors")` 上抛 AttributeError，整批抽取直接崩（实测
        # 不良贷款率 id=88：source 存的是字面 "null"，一取这一项就炸）。
        # 按既有范式用 position 反推 selectors 补上，不动引擎。
        # **范围只限银行监管指标集**：全库还有 2300+ 条 NULL source（历史遗留），
        # 一次全改会越出本 change 范围并影响别的消费面，故按指标白名单收窄。
        marks = ", ".join("?" for _ in BANK_INDICATORS)
        for row in conn.execute(
            f"SELECT id, indicator, source, position FROM llm_rules "
            f"WHERE (source IS NULL OR source IN ('', 'null', '\"null\"')) "
            f"AND indicator IN ({marks})",
            list(BANK_INDICATORS),
        ).fetchall():
            pos_raw = (row["position"] or "").strip()
            try:
                pos_obj = json.loads(pos_raw)
            except (TypeError, ValueError):
                pos_obj = None
            if isinstance(pos_obj, list) and pos_obj:
                selectors = pos_obj
            elif isinstance(pos_obj, str) and pos_obj:
                selectors = [{"section": pos_obj}]
            elif pos_raw:
                selectors = [{"section": pos_raw}]
            else:
                print(f"[skip-repair] id={row['id']} {row['indicator']}: 无 position 可用")
                continue
            print(f"[repair] id={row['id']} {row['indicator']}: source <- selectors")
            if not args.dry_run:
                conn.execute(
                    "UPDATE llm_rules SET source = ? WHERE id = ?",
                    (_d({"selectors": selectors, "extractor": "llm"}), row["id"]),
                )
            repaired += 1
        if not args.dry_run:
            conn.commit()

        # ── 编码降层：让 applies_to（及同族列）能被读取面的单次 json.loads 解成对象 ──
        # 只动银行指标集，全库另有 3300+ 条同病（跨行业），不在本 change 范围。
        marks = ", ".join("?" for _ in BANK_INDICATORS)
        for row in conn.execute(
            f"SELECT id, indicator, {', '.join(_JSON_COLS)} FROM llm_rules "
            f"WHERE indicator IN ({marks}) ORDER BY id",
            list(BANK_INDICATORS),
        ).fetchall():
            sets, vals = [], []
            for col in _JSON_COLS:
                new_raw, changed = _collapse_one_level(row[col])
                if changed:
                    sets.append(f"{col} = ?")
                    vals.append(new_raw)
            if not sets:
                continue
            print(f"[collapse] id={row['id']} {row['indicator']}: "
                  f"{', '.join(s.split(' =')[0] for s in sets)} 双层 -> 单层")
            if not args.dry_run:
                conn.execute(f"UPDATE llm_rules SET {', '.join(sets)} WHERE id = ?",
                             vals + [row["id"]])
            collapsed += 1
        if not args.dry_run:
            conn.commit()
        total = conn.execute("SELECT count(*) FROM llm_rules").fetchone()[0]
    finally:
        conn.close()

    print(f"\ninserted={inserted} updated={updated} repaired={repaired} "
          f"collapsed={collapsed} dry_run={args.dry_run} "
          f"llm_rules_total={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
