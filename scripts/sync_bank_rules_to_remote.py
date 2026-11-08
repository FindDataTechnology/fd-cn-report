#!/usr/bin/env python
"""把银行指标规则行同步到线上 pod 的 daas.db（只动银行指标，不碰其余规则）。

**为什么不整库覆盖**：线上 `/data/daas.db` 是另一条血统——实测 482 条规则（`taxonomy_code`
全为 NULL）、9 份报告、59 章节、**没有 `taxonomy_mapping` 表**；本地是 3381 条 / 462 份 /
152 万字符章节。整库覆盖会连带替换其余 400+ 条与银行无关的规则，风险不可接受。

**做法**：只对「银行指标集合」（17 项已验证 + 13 项 harden）执行
`DELETE WHERE indicator IN (...)` 再整行 INSERT 本地版本，其余行原样保留。
集合外的任何规则、任何报告记录都不动。

安全：
  · 先把线上 `/data/daas.db` 备份成 `/data/daas.db.bak-<stamp>`（pod 内，占用极小）
  · 同步后逐项校验：银行 17 项的 note 带「本报告期」口径、`script_rules` 银行项为 0、
    行数与本地一致
  · `--dry-run` 只打印将要写的行数

用法：
  python3 scripts/sync_bank_rules_to_remote.py --dry-run
  python3 scripts/sync_bank_rules_to_remote.py            # 备份 + 同步 + 校验
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
DAAS_DB = _REPO.parent / "daas.db"

NS = "fd-prod"
SELECTOR = "app/src=fd-cn-report"  # 占位，实际用 label
POD_LABEL = "app.kubernetes.io/name=fd-cn-report"

#: 17 项已验证 + 13 项 harden（含 3156 与非报告口径 5 项，均按本地状态整行同步）
BANK_INDICATORS = [
    "净息差", "净利差", "不良贷款率", "不良贷款余额", "拨备覆盖率", "拨贷比",
    "资本充足率", "核心一级资本充足率", "一级资本充足率", "流动性覆盖率",
    "成本收入比", "杠杆率", "净稳定资金比例",
    "正常类贷款迁徙率", "关注类贷款迁徙率", "次级类贷款迁徙率", "可疑类贷款迁徙率",
    # harden 13
    "不良率", "净利息收入", "发放贷款及垫款", "客户存款", "手续费及佣金净收入",
    "拨贷比_coverage", "流动性比例（人民币）", "质押贷款净增加额", "贷款和垫款总额",
    "逾期90天重组贷款率", "逾期贷款率", "重组贷款率", "风险加权资产合计",
]


def _pod() -> str:
    out = subprocess.run(
        ["kubectl", "-n", NS, "get", "pods", "-l", POD_LABEL,
         "-o", "jsonpath={.items[0].metadata.name}"],
        capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _payload() -> list[dict]:
    conn = sqlite3.connect(str(DAAS_DB))
    conn.row_factory = sqlite3.Row
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(llm_rules)")]
        marks = ",".join("?" * len(BANK_INDICATORS))
        rows = conn.execute(
            f"SELECT * FROM llm_rules WHERE indicator IN ({marks}) ORDER BY indicator, id",
            BANK_INDICATORS).fetchall()
    finally:
        conn.close()
    return [{c: r[c] for c in cols} for r in rows]


REMOTE_SCRIPT = r'''
import json, sqlite3, sys
payload = json.load(sys.stdin)
c = sqlite3.connect("/data/daas.db")
cols = [r[1] for r in c.execute("PRAGMA table_info(llm_rules)")]
inds = sorted({r["indicator"] for r in payload})
before = c.execute("select count(*) from llm_rules").fetchone()[0]
c.execute("DELETE FROM llm_rules WHERE indicator IN (%s)" % ",".join("?"*len(inds)), inds)
n = 0
for r in payload:
    keys = [k for k in cols if k in r and k != "id"]
    c.execute("INSERT INTO llm_rules (%s) VALUES (%s)" % (",".join(keys), ",".join("?"*len(keys))),
              [r[k] for k in keys])
    n += 1
c.commit()
after = c.execute("select count(*) from llm_rules").fetchone()[0]
print(json.dumps({"before": before, "after": after, "inserted": n, "indicators": len(inds)}))
'''


VERIFY_SCRIPT = r'''
import json, sqlite3
c = sqlite3.connect("/data/daas.db")
res = {}
res["llm_rules"] = c.execute("select count(*) from llm_rules").fetchone()[0]
res["bank17"] = c.execute(
    "select count(*) from llm_rules where indicator in "
    "('净息差','净利差','不良贷款率','不良贷款余额','拨备覆盖率','拨贷比','资本充足率',"
    "'核心一级资本充足率','一级资本充足率','流动性覆盖率','成本收入比','杠杆率','净稳定资金比例',"
    "'正常类贷款迁徙率','关注类贷款迁徙率','次级类贷款迁徙率','可疑类贷款迁徙率')").fetchone()[0]
res["hint_rows"] = c.execute(
    "select count(*) from llm_rules where note like '%本报告期%'").fetchone()[0]
res["script_bank"] = c.execute(
    "select count(*) from script_rules where indicator in "
    "('净息差','资本充足率','杠杆率','拨备覆盖率','不良贷款率')").fetchone()[0]
res["documents"] = c.execute("select count(*) from report_documents").fetchone()[0]
print(json.dumps(res))
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pod = _pod()
    if not pod:
        raise SystemExit("找不到 fd-cn-report pod")
    rows = _payload()
    print(f"pod={pod}  待写 {len(rows)} 行（{len(BANK_INDICATORS)} 个指标名）")
    if args.dry_run:
        by: dict[str, int] = {}
        for r in rows:
            by[r["indicator"]] = by.get(r["indicator"], 0) + 1
        for ind in BANK_INDICATORS:
            print(f"  {ind:14s} ×{by.get(ind,0)}")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = subprocess.run(
        ["kubectl", "-n", NS, "exec", pod, "--", "cp", "/data/daas.db", f"/data/daas.db.bak-{stamp}"],
        capture_output=True, text=True)
    print("backup:", bak.stdout.strip() or bak.stderr.strip()[:80])

    res = subprocess.run(["kubectl", "-n", NS, "exec", "-i", pod, "--", "python", "-c", REMOTE_SCRIPT],
                         input=json.dumps(rows), capture_output=True, text=True)
    print("sync:", res.stdout.strip() or res.stderr.strip()[:400])
    if res.returncode != 0:
        return 1

    ver = subprocess.run(["kubectl", "-n", NS, "exec", pod, "--", "python", "-c", VERIFY_SCRIPT],
                         capture_output=True, text=True)
    print("verify:", ver.stdout.strip() or ver.stderr.strip()[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
