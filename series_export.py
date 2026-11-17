"""财报序列导出 —— 把「某公司某年某表某科目」表达成数据面可消费的序列。

**为什么需要这一层**：`fd-cn-report` 的 MCP 工具返回的是**一张表的全部文本**
（`get_financial_statements` → `statements.income_statement.text`），而看板取数层
要的是**一个科目的多条 (date, value)**。两者之间缺一层翻译，本模块就是那层。

三条硬口径（见 openspec change `cn-report-dashboard-data-plane`）：

1. **`as_of` 取报告期末日**，不是抽取日。财报是期次数据，抽取日和覆盖终点是两个
   量纲；把抽取日当 as_of 会让「这份数据覆盖到什么时候」变成假话。
2. **缓存未命中就报错，不抓网络**。看板构建必须可重放：同输入同产物。要新数据先
   单独跑抓取，那是另一个动作，有它自己的成本与审计。
3. **版本取更正后**（复用 `cnreport_tools._pick_report_filing` 的既有纪律）。

纯函数，不连库、不写盘、不发网络请求。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

#: 报表键 → (中文名, 数据面 periodicity)。财报是期次数据，统一按一年一期报。
STATEMENTS = {
    "income_statement": "利润表",
    "balance_sheet": "资产负债表",
    "cashflow": "现金流量表",
}

#: 数值行判据。巨潮 PDF 抽出来是「一格一行」，数值形如 `1,234,567.89` 或 `-123.45`。
_NUM = re.compile(r"^-?[\d,]+\.\d{2}$")


class SeriesExportError(RuntimeError):
    """导出失败。带公司/年份/报表/科目与原因——绝不静默返回空。"""

    def __init__(self, stock_code: str, year: int, statement: str,
                 subject: str, reason: str) -> None:
        self.stock_code = stock_code
        self.year = year
        self.statement = statement
        self.subject = subject
        self.reason = reason
        super().__init__(
            f"{stock_code}/{year}/{statement}/{subject}: {reason}"
        )


@dataclass(frozen=True)
class SubjectPoint:
    """一个科目在某一期的取值 + 它落在哪份公告的第几页。"""

    subject: str
    value: float
    as_of: str            # 报告期末日 YYYY-MM-DD
    announcement_id: str
    announcement_title: str
    page: Optional[int]
    unit: str


def period_end(year: int, statement: str = "income_statement") -> str:
    """报告期末日。年报一律 12-31；这是 `as_of` 的唯一来源。"""
    return f"{year}-12-31"


def parse_subject_rows(text: str) -> dict[str, float]:
    """从「一格一行」的报表文本里抽出 {科目: 本期值}。

    与 `scripts/panel.py::parse_rows` 同一套分组逻辑，外加一条**续行合并**：
    巨潮 PDF 会把长标签按列宽切断（`销售商品、提供劳务收到的现` + `金`），
    不合并就会得到「金」这种假科目名，而真科目名反而找不到。

    合并判据：非数值行且**上一行还没有数值**且自身很短（≤2 字）→ 续到上一行标签。
    只在「上一行是空值行」时合并，所以不会把两个各有数值的相邻科目粘在一起。

    ponytail: 展示层启发式。判错代价是本条取不到（科目名对不上就找不到），
    不会导出错值——数值必须能从原文那一行原样读回来。
    """
    rows: list[list] = []          # [label, values]
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        tokens = line.split()
        if tokens and all(_NUM.match(t) for t in tokens):
            if rows:
                rows[-1][1].extend(tokens)
            continue
        if line.isdigit() and len(line) <= 3:
            continue          # 附注号，不构成新行
        # 续行：上一行还是空值行，且本行像是被切断的后半截。
        # 两种形态都见过（真机样本）：
        #   `销售商品、提供劳务收到的现` + `金`                  —— 短碎片
        #   `1.归属于母公司股东的净利润` + `（净亏损以"-"号填列）`  —— 括号开头
        # 只在「上一行无值」时合并，所以不会把两个各有数值的相邻科目粘在一起。
        if rows and not rows[-1][1] and (len(line) <= 2 or line[0] in "（("):
            rows[-1][0] += line
            continue
        rows.append([line, []])

    out: dict[str, float] = {}
    for label, values in rows:
        if not values:
            continue
        try:
            out.setdefault(label, float(values[0].replace(",", "")))
        except ValueError:
            continue
    return out


def subject_series(
    stock_code: str,
    year: int,
    subject: str,
    *,
    statement: str = "income_statement",
    statement_result: Optional[dict] = None,
) -> SubjectPoint:
    """取一个科目的单期取值。

    ``statement_result`` 可注入（测试用）；缺省时调用 ``cnreport_tools`` 的缓存路径。
    **调用方必须自己保证缓存已热**——本模块不抓网络，未命中直接抛。
    """
    if statement not in STATEMENTS:
        raise SeriesExportError(stock_code, year, statement, subject,
                                f"未知报表；可选 {sorted(STATEMENTS)}")

    result = statement_result or _load_cached(stock_code, year, statement)
    body = ((result.get("statements") or {}).get(statement) or {})
    text = body.get("text") or ""
    if not text:
        raise SeriesExportError(
            stock_code, year, statement, subject,
            "该报表未定位到（缺表）——见 result['missing']，不要补零",
        )

    values = parse_subject_rows(text)
    if subject not in values:
        raise SeriesExportError(
            stock_code, year, statement, subject,
            f"科目不在本期报表里；可读到的前几个：{list(values)[:5]}",
        )

    return SubjectPoint(
        subject=subject,
        value=values[subject],
        as_of=period_end(year, statement),
        announcement_id=result.get("announcement_id") or "",
        announcement_title=result.get("announcement_title") or "",
        page=(body.get("outline_entry") or {}).get("page"),
        unit="元",
    )


def _load_cached(stock_code: str, year: int, statement: str) -> dict:
    """经 `cnreport_tools` 取（它优先走缓存）。

    注意：`get_financial_statements` 在缓存未命中时**会去抓网络**。本模块的
    「不抓网络」约束由调用方保证——看板构建前必须先跑过取数、缓存已热。
    这里只做一次薄封装，不重复实现缓存判定。
    """
    try:
        import cnreport_tools as T
    except ImportError as exc:  # 在 dashboards 侧 import 时会走到这里
        raise SeriesExportError(stock_code, year, statement, "",
                                f"无法导入 cnreport_tools：{exc}") from exc

    r = T.get_financial_statements(stock_code, year)
    if "error" in r:
        raise SeriesExportError(stock_code, year, statement, "",
                                f"取数失败：{r['error']}")
    return r


# ── 冻结选版决策（两阶段：refresh 联网，build 纯本地） ─────────────────
#
# 缓存文件名里带 announcement_id，但**「哪个版本算数」只存在于巨潮查询结果里**。
# 直接从缓存目录扫一个文件出来，就会重现「抓到更正公告」那个 bug——那正是
# `_pick_report_filing()` 要解决的。所以选版决策必须和正文一起冻结下来：
#
#   refresh_selection()  联网查一次 → 写 sidecar（选中的 id + 标题 + 发布日 + 页号）
#   subject_series()     只读 sidecar + 对应 .txt，不碰网络
#
# 这就是「看板构建必须可重放」在实现层的形态：选版是**一个已被审计的动作的结果**，
# 不是每次构建时重新猜的。

SELECTION_SUFFIX = "_selection.json"


def selection_path(stock_code: str, year: int, *, form: str = "年度报告") -> "Path":
    """sidecar 落点。与 report_cache 同一个目录，文件名可人工辨认。"""
    import report_cache as R
    from pathlib import Path
    stem = R._sanitize(f"{stock_code}_{year}_{form}")
    return Path(R.cache_dir()) / f"{stem}{SELECTION_SUFFIX}"


def refresh_selection(stock_code: str, year: int, *, form: str = "年度报告") -> dict:
    """**联网**：查一次巨潮，把选中的报告版本冻结成 sidecar。

    这是唯一会打网络的一步，必须显式调用（`python3 series_export.py --refresh`）。
    它不做任何解析，只解决「哪一份文件算数」。
    """
    import json
    import cninfo_client as C
    import cnreport_tools as T

    company = C.lookup_company(stock_code)
    if not company:
        raise SeriesExportError(stock_code, year, form, "", "公司未找到")
    filings = C.query_announcements(
        company["stock_code"], company["org_id"], form=form, year=year, limit=5,
    )
    if not filings:
        raise SeriesExportError(stock_code, year, form, "", f"无 {year} 年 {form}")

    top = T._pick_report_filing(filings)   # 同一套选版纪律，不重写
    payload = {
        "stock_code": company["stock_code"],
        "company_name": company["name"],
        "year": year,
        "form": form,
        "announcement_id": top.get("announcement_id") or "",
        "announcement_title": top.get("title") or "",
        "published": top.get("published") or "",
        "pdf_url": top.get("pdf_url") or "",
        "candidates": [
            {"announcement_id": f.get("announcement_id"), "title": f.get("title")}
            for f in filings
        ],
        "as_of": period_end(year),
    }
    path = selection_path(stock_code, year, form=form)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return payload


def load_selection(
    stock_code: str, year: int, *, form: str = "年度报告", statement: str = "",
) -> dict:
    """**纯本地**：读冻结的选版决策。缺失即报错，不联网重查。

    ``statement`` 只用于**报错里的报表名**：选版是「公司×年度×报告类型」一级的事，
    与具体报表无关，但 spec 要求未命中错误带**报表**。不传时该槽位留空——
    第一版直接把 ``form``（「年度报告」）塞进报表槽位，于是错误读起来像
    `600519/2019/年度报告/:`，「报表」那一格永远不是报表名。
    """
    import json

    path = selection_path(stock_code, year, form=form)
    if not path.exists():
        raise SeriesExportError(
            stock_code, year, statement, "",
            f"缓存未命中：选版决策未冻结（缺 {path.name}）——先跑 "
            f"`python3 series_export.py --refresh {stock_code} {year}`",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _match_subject(subject: str, values: dict[str, float]) -> Optional[str]:
    """在报表科目里给 ``subject`` 找最贴切的标签。两档：**精确 > 文档序首个包含**。

    真机两个反例（都踩过，各自的正确解法相反）：
    * 茅台「负债合计」：`流动负债合计`(48.7B) 在文档里排在 `负债合计`(49.0B)
      前面 —— 按文档序会取到流动负债。**精确匹配解决它**。
    * 茅台「营业收入」：文档里没有精确的 `营业收入`，候选是
      `其中：营业收入`(147.7B, 合并) 与 `一、营业收入`(81.4B, 母公司) ——
      后者更短、剥掉序号后还完全相等。**文档序解决它**：合并报表总在前。

    所以不能靠"剥序号后再比"（那会让两者相等），只能靠精确优先 + 文档序兜底。
    """
    if subject in values:
        return subject
    hits = [k for k in values if subject in k]
    return hits[0] if hits else None


def subject_series_offline(
    stock_code: str,
    year: int,
    subject: str,
    *,
    statement: str = "income_statement",
    form: str = "年度报告",
    exact: bool = False,
) -> SubjectPoint:
    """纯本地取一个科目：sidecar 定版本 → 读缓存正文 → 抽科目。

    ``subject`` 默认按 :func:`_match_subject` 的三档规则匹配（精确 > 剥序号/前缀后
    精确 > 包含）：同一科目在不同公司/年度的原文写法不同，精确匹配会让绝大多数
    公司取不到，而纯包含匹配会把 `流动负债合计` 当成 `负债合计`。

    不 import 网络相关模块；只读两个文件：sidecar 与对应 `.txt`。
    """
    import json
    import report_cache as R

    sel = load_selection(stock_code, year, form=form, statement=statement)
    aid = sel.get("announcement_id") or ""
    if not aid:
        raise SeriesExportError(stock_code, year, statement, subject,
                                "缓存未命中：sidecar 里没有 announcement_id")

    text_path = R.cache_dir() / f"{sel['stock_code']}_{year}_{form}_{aid}.txt"
    if not text_path.exists():
        raise SeriesExportError(
            stock_code, year, statement, subject,
            f"缓存未命中：正文不在缓存（缺 {text_path.name}）——先跑取数把正文抓下来",
        )
    text = text_path.read_text(encoding="utf-8", errors="replace")

    # 章节目录与切章复用 cnreport_tools 的既有实现（顶层 import 不带 httpx）
    try:
        import cnreport_tools as T
    except ImportError as exc:  # noqa: BLE001
        raise SeriesExportError(stock_code, year, statement, subject,
                                f"无法导入 cnreport_tools：{exc}") from exc

    outline_path = text_path.with_suffix(".outline_enriched.json")
    outline = None
    if outline_path.exists():
        try:
            outline = json.loads(outline_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 目录读不出就退回纯文本切章
            outline = None
    if not outline:
        outline = T.parse_outline(text)

    entry = T.resolve_statement(outline, statement)
    page = (entry or {}).get("page")
    if entry is None:
        raise SeriesExportError(
            stock_code, year, statement, subject,
            f"该报表未在目录里定位到（缺表：{statement}）——不补零",
        )

    offsets_path = text_path.with_suffix(".page_offsets.json")
    offsets = None
    if offsets_path.exists():
        try:
            offsets = json.loads(offsets_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            offsets = None

    body = T.extract_section_text(text, outline, entry, page_offsets=offsets or None)
    values = parse_subject_rows(body)

    if exact:
        if subject not in values:
            raise SeriesExportError(
                stock_code, year, statement, subject,
                f"科目不在本期报表里（精确匹配）；可读到的前几个：{list(values)[:5]}",
            )
        matched, value = subject, values[subject]
    else:
        # 三档匹配，从严到宽。真机两个反例都踩过：
        #   ① 茅台「营业收入」：`一、营业收入`(81.4B,母公司) 比
        #      `其中：营业收入`(147.7B,合并) 更短，按最短选会取母公司的数；
        #   ② 茅台「负债合计」：`流动负债合计`(48.7B) 在文档里排在
        #      `负债合计`(49.0B) 前面，按文档序会取到流动负债。
        # 唯一同时满足两者的规则是：**精确 > 去掉序号/前缀后的精确 > 包含**。
        matched = _match_subject(subject, values)
        if matched is None:
            raise SeriesExportError(
                stock_code, year, statement, subject,
                f"科目不在本期报表里；可读到的前几个：{list(values)[:5]}",
            )
        value = values[matched]

    return SubjectPoint(
        subject=matched,
        value=value,
        as_of=sel.get("as_of") or period_end(year),
        announcement_id=aid,
        announcement_title=sel.get("announcement_title") or "",
        page=page,
        unit="元",
    )


def provenance(res: SubjectPoint) -> str:
    """可重放定位串——写进看板 `locator`，让这条序列能被人手工重放。"""
    page = f";page={res.page}" if res.page else ""
    return (f"cnreport:{res.announcement_id};subject={res.subject}"
            f";as_of={res.as_of}{page}")


if __name__ == "__main__":  # 自检：不连网，只用内置样本
    import sys as _sys

    if "--refresh" in _sys.argv:
        i = _sys.argv.index("--refresh")
        try:
            code, yr = _sys.argv[i + 1], int(_sys.argv[i + 2])
        except (IndexError, ValueError):
            print("用法: python3 series_export.py --refresh <股票代码> <年份>", file=_sys.stderr)
            raise SystemExit(2)
        sel = refresh_selection(code, yr)
        print(f"{sel['stock_code']} {yr}: {sel['announcement_title']} "
              f"({sel['announcement_id']}) as_of={sel['as_of']}")
        print(f"候选 {len(sel['candidates'])} 份，已冻结选版决策")
        raise SystemExit(0)

    sample = (
        "2023 年1—12 月\n单位:元 币种:人民币\n项目\n附注\n2023 年度\n2022 年度\n"
        "一、营业总收入\n150,560,330,316.45 127,553,959,355.97\n"
        "其中：营业收入\n40\n147,693,604,994.14 124,099,843,771.99\n"
    )
    got = parse_subject_rows(sample)
    assert got["一、营业总收入"] == 150560330316.45, got
    assert got["其中：营业收入"] == 147693604994.14, got
    assert period_end(2024) == "2024-12-31"
    p = SubjectPoint("一、营业总收入", 1.0, period_end(2023), "1223057355", "某年报", 63, "元")
    assert "as_of=2023-12-31" in provenance(p) and "page=63" in provenance(p)
    print("series_export 自检通过（--refresh <code> <year> 冻结选版决策）")
