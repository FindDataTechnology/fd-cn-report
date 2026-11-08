#!/usr/bin/env python
"""把银行监管指标抽取结果登记进 semantic_observations（awaken-banking-report-ingest 6.2）。

链路：`daas.db` 的报告清单 → `indicators_client.extract_indicators` 抽 17 项监管指标
      → 中文科目经 `docs/bank-indicator-concepts.json` 映射到 `financials.*` 概念
      → 写本体库 `semantic_observations`（键 (concept_id, entity_type, entity_id,
        date, granularity, source_used)）。

纪律（spec「抽取结果 SHALL 登记进语义观测层并过命名门」）：
  · **不插值、不补零、不与他源合并同点值**：只登记抽到的值；`None` 一律跳过，
    并按「未披露 / 对位失败」分类计数留痕（对位失败非零退出，因为那是缺陷）。
  · **季度与年度口径分开**：年报 granularity=year/date=YYYY-12-31，半年报 half/06-30，
    一季报 quarter/03-31，三季报 quarter/09-30 —— 同一个概念的不同口径是不同行。
  · **幂等**：靠 `uq_sem_obs` + `ON CONFLICT DO NOTHING`，重跑零重复行。
  · **命名门**：概念必须 semantic_code/name_zh/name_en/unit/frequency 齐备且 verified；
    缺一条就拒登记（读取面对未过门指标不可见）。

用法（需要 FD_OPEN_DATA_MCP_DATABASE_URL 指向本体库）：
  python3 scripts/register_semantic_observations.py --codes 601398,600036 --years 2025 --dry-run
  python3 scripts/register_semantic_observations.py --codes 601398,600036 --years 2025
  python3 scripts/register_semantic_observations.py --from-db --years 2025    # 用 daas.db 已入库报告
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
# 本体库包在兄弟仓（fd-open-data-mcp）；本脚本需用它的 venv 跑（有 psycopg2），
# 这里补上源码路径以便同仓导入概念/观测模型。
sys.path.insert(0, str(_REPO.parent / "fd-open-data-mcp"))

MAPPING = _REPO / "docs" / "bank-indicator-concepts.json"
DAAS_DB = _REPO.parent / "daas.db"
CACHE_DIR = _REPO / ".cache" / "reports"
SOURCE_USED = "cn-report"

#: 进程启动时外部导出的 LLM 配置 —— 必须比仓内 `.env/.env.local` 优先。
#: 实测 fd-open-data-mcp 的 `.env.local` 会把 LLM_BASE_URL 覆盖成过期网关（401），
#: 而注册脚本要真的调抽取；故在导入本仓库包之后再钉一次运行时值。
_SHELL_LLM = {k: v for k, v in os.environ.items()
              if k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL") and v}  # spec 口径；历史 'cnreport' 是另一条旧管线（date 为裸年份）

#: 报告类型 → (granularity, 期末日 MM-DD)
FORM_PERIOD = {
    "年度报告": ("year", "12-31"),
    "半年度报告": ("half", "06-30"),
    "第一季度报告": ("quarter", "03-31"),
    "第三季度报告": ("quarter", "09-30"),
}

LABELS = {
    "净息差": ["净息差", "净利息收益率"], "净利差": ["净利差", "净利息差"],
    "不良贷款率": ["不良贷款率"], "不良贷款余额": ["不良贷款"],
    "拨备覆盖率": ["拨备覆盖率"], "拨贷比": ["拨贷比", "贷款拨备率"],
    "资本充足率": ["资本充足率"], "核心一级资本充足率": ["核心一级资本充足率"],
    "一级资本充足率": ["一级资本充足率"], "流动性覆盖率": ["流动性覆盖率"],
    "成本收入比": ["成本收入比"], "杠杆率": ["杠杆率"],
    "净稳定资金比例": ["净稳定资金比例"],
    "正常类贷款迁徙率": ["正常类贷款迁徙率", "正常贷款迁徙率", "贷款迁徙率"],
    "关注类贷款迁徙率": ["关注类贷款迁徙率", "关注类"],
    "次级类贷款迁徙率": ["次级类贷款迁徙率", "次级类"],
    "可疑类贷款迁徙率": ["可疑类贷款迁徙率", "可疑类"],
}


def _report_text(code: str, year: int, form: str) -> str:
    for pat in (f"{code}_{year}_{form}_*.txt", f"{code}_{year}_*.txt"):
        hits = sorted(CACHE_DIR.glob(pat))
        if hits:
            return hits[0].read_text(encoding="utf-8", errors="replace")
    return ""


def _miss_status(indicator: str, text: str, form: str | None = None) -> str:
    """无值分三类：不适用 / 未披露 / 对位失败。判据必须**只在原文真的给了数**时才算对位失败。

    只看「标签是否出现」会把季报的叙述式提及（「本行资本充足率保持稳健」）误判成
    对位失败——实测 601398 一季报因此报出 11 条假缺陷。真缺陷的样子是「标签后面跟着
    一个数字」（`杠杆率 6.28`），所以要求标签 60 字符内出现数字。
    """
    flat = re.sub(r"\s+", "", text or "")
    for label in LABELS.get(indicator, [indicator]):
        needle = re.sub(r"\s+", "", label)
        start = 0
        while True:
            pos = flat.find(needle, start)
            if pos == -1:
                break
            if re.search(r"\d", flat[pos + len(needle):pos + len(needle) + 60]):
                return "对位失败"
            start = pos + 1
    return "未披露"


def _form_applicable(indicator: str, form: str) -> bool | None:
    """该指标是否有规则覆盖这种报告类型（None=查不到，按覆盖处理）。

    实测：不良贷款率(id 88)/拨备覆盖率(1830) 的 `document_type_codes=['cn_annual']`，
    半年报/季报上根本没有可用规则 —— 抽取返回空 bundle 且 missing 为空。若把它算成
    「对位失败」，等于拿规则不适用冒充缺陷；算成「未披露」又掩盖了「这条根本没规则」。
    故单列 `不适用`。"""
    import sqlite3
    doc_type = {"年度报告": "cn_annual", "半年度报告": "cn_interim",
                "第一季度报告": "cn_quarterly", "第三季度报告": "cn_quarterly"}.get(form)
    if not doc_type:
        return None
    conn = sqlite3.connect(str(DAAS_DB))
    try:
        rows = conn.execute(
            "SELECT document_type_codes FROM llm_rules WHERE indicator = ?", (indicator,)
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    for (raw,) in rows:
        try:
            codes = json.loads(raw) if isinstance(raw, str) else (raw or [])
            codes = json.loads(codes) if isinstance(codes, str) else codes
        except Exception:
            continue
        if isinstance(codes, list) and doc_type in codes:
            return True
    return False


def _db_reports(years: list[int]) -> list[tuple[str, int, str]]:
    import sqlite3
    conn = sqlite3.connect(str(DAAS_DB))
    try:
        rows = conn.execute(
            "SELECT DISTINCT stock_code, fiscal_year, form FROM report_documents "
            "WHERE parse_status = 'ok' ORDER BY stock_code, fiscal_year, form"
        ).fetchall()
    finally:
        conn.close()
    return [(c, y, f) for c, y, f in rows if y in years]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--codes", default="", help="逗号分隔股票代码")
    ap.add_argument("--years", default="2025", help="逗号分隔财年")
    ap.add_argument("--forms", default="年度报告", help="逗号分隔报告类型")
    ap.add_argument("--from-db", action="store_true", help="报告清单取自 daas.db")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    years = [int(y) for y in args.years.split(",") if y.strip()]
    forms = [f.strip() for f in args.forms.split(",") if f.strip()]
    if args.from_db:
        targets = [t for t in _db_reports(years) if t[2] in forms]
    else:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        if not codes:
            raise SystemExit("需要 --codes 或 --from-db")
        targets = [(c, y, f) for c in codes for f in forms for y in years]

    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    ind_to_concept = {r["indicator_zh"]: r for r in mapping["indicator_concepts"]}
    indicators = list(ind_to_concept)

    url = os.environ.get("FD_OPEN_DATA_MCP_DATABASE_URL")
    if not url:
        raise SystemExit("未设置 FD_OPEN_DATA_MCP_DATABASE_URL（本体库 Postgres）")

    from sqlalchemy import text as sql

    from fd_open_data_mcp.db import Database
    from fd_open_data_mcp.models import Concept
    from fd_open_data_mcp.semantic.dates import obs_month_of

    if _SHELL_LLM:  # 恢复被仓内 dotenv 覆盖掉的运行时 LLM 配置
        os.environ.update(_SHELL_LLM)

    db = Database(url)
    session = db.get_session()
    import indicators_client as IC

    inserted = existed = 0
    miss = {"不适用": 0, "未披露": 0, "对位失败": 0}
    failures: list[tuple[str, str]] = []
    try:
        # 命名门 + 概念解析（一次）
        concept_by_ind: dict[str, Concept] = {}
        for ind, row in ind_to_concept.items():
            c = session.query(Concept).filter(
                Concept.code == row["code"], Concept.entity_type == mapping["entity_type"],
                Concept.frequency == row["frequency"],
            ).first()
            if c is None:
                failures.append((ind, "概念不存在（先跑 seed_bank_concepts.py）"))
                continue
            if not (c.name_zh and c.name_en and c.unit and c.frequency and c.verified):
                failures.append((ind, "命名门不过（name_zh/name_en/unit/frequency/verified）"))
                continue
            concept_by_ind[ind] = c
        if failures:
            for ind, why in failures:
                print(f"  [门] {ind}: {why}")
            return 1

        for code, year, form in targets:
            gran, md = FORM_PERIOD.get(form, ("year", "12-31"))
            date = f"{year}-{md}"
            entity = session.execute(
                sql("SELECT id FROM entities WHERE entity_type='stock' AND code=:c"),
                {"c": code},
            ).scalar()
            if entity is None:
                failures.append((f"{code}", "实体不存在"))
                continue
            bundle = IC.extract_indicators(code, year, indicators=indicators,
                                           form=form, extractor_mode="llm")
            got = bundle.get("indicators") or {}
            text_cache = _report_text(code, year, form)
            n_ins = 0
            for ind, concept in concept_by_ind.items():
                val = (got.get(ind) or {}).get("value")
                if val is None:
                    if _form_applicable(ind, form) is False:
                        miss["不适用"] += 1
                    else:
                        miss[_miss_status(ind, text_cache)] += 1
                    continue
                row = session.execute(
                    sql("""INSERT INTO semantic_observations
                             (concept_id, entity_type, entity_id, date, granularity, value,
                              unit, source_used, fetched_at, obs_month)
                           VALUES (:cid, 'stock', :eid, :date, :gran, :val, :unit,
                                   :src, now(), :om)
                           ON CONFLICT ON CONSTRAINT uq_sem_obs DO NOTHING
                           RETURNING id"""),
                    {"cid": concept.id, "eid": entity, "date": date, "gran": gran,
                     "val": str(val), "unit": concept.unit, "src": SOURCE_USED,
                     "om": obs_month_of(date)},
                ).first()
                if row is not None:
                    inserted += 1
                    n_ins += 1
                else:
                    existed += 1
            print(f"  {code} FY{year} {form}: +{n_ins} (gran={gran} date={date})",
                  flush=True)
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
    finally:
        session.close()

    print(f"\ninserted={inserted} existed={existed} dry_run={args.dry_run} "
          f"source_used={SOURCE_USED} miss={miss} failures={len(failures)}")
    return 1 if (failures or miss["对位失败"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
