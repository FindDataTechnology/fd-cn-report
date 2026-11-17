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

#: 数值行判据。巨潮 PDF 抽出来是「一格一行」，数值有三种常见形态（都是真机样本）：
#:   工商企业：`1,234,567.89` / `-123.45`        —— 元，两位小数
#:   银行/保险：`268,973` / `(104,954)`          —— 百万元，无小数；负号常写成括号
#:   混合：`1,234`
#: 早先只认第一种，于是银行报表（000001 等）一个科目都抽不出来——那不是"报表里没有"，
#: 是判据太窄。
_NUM = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$")


def _to_float(token: str) -> Optional[float]:
    """数值文本 → float。括号与全角负号都按负处理（财报通用写法）。

    全角括号 ``（1,000）`` 也是负数——2026-11-17 实测：早先只处理半角，
    银行报表里的负值全被读成正值。
    """
    s = token.strip()
    neg = False
    for lo, hi in (("(", ")"), ("（", "）")):
        if s.startswith(lo) and s.endswith(hi):
            neg, s = True, s[1:-1]
            break
    s = s.replace(",", "").replace(" ", "")
    if s[:1] in ("－", "−", "-"):
        neg, s = True, s[1:]
    if not s or not any(ch.isdigit() for ch in s):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v

#: 带序号的科目名（`一、…` / `1.…` / `（一）…`）：这类是**真科目**，不许当续行碎片合并。
_ENUMERATED = re.compile(r"^(?:[一二三四五六七八九十]+[、.．]|\d+[、.．]|[（(][一二三四五六七八九十\d]+[）)])")


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


#: 报表头里的计量单位声明。**必须读出来**：银行/保险用「人民币百万元」，
#: 工商企业用「元」。两者混在同一列里而不标单位，等于给出一个看起来正常、
#: 实际差六个数量级的数字（2026-11-17 真机：000001 资产总计 5,769,270 是
#: 百万元 = 5.77 万亿，而同表里 000019 的 7,714,550,508.01 是元）。
_UNIT_PATTERNS = [
    # `单位：元` / `单位:元 币种:人民币` / `单位：人民币元`
    (re.compile(r"单位[：:]\s*(?:人民币)?\s*(百万元|万元|千元|元)"), 1),
    # `(除特别注明外，金额单位均为人民币百万元)`
    (re.compile(r"金额单位[均为]*\s*(?:人民币)?\s*(百万元|万元|千元|元)"), 1),
    # 无「单位：」前缀时只认大额单位（`百万元` 不会出现在描述性文字里）；
    # `元` 太常见，绝不兜底——那会把正文里的「万元列示」误认成表头声明。
    (re.compile(r"(百万元)"), 1),
]


def detect_unit(text: str) -> str:
    """从报表头读出计量单位，读不出就如实返回空串（**不假设「元」**）。

    只扫前 12 行——单位声明在表头，正文里出现的「万元」多是描述性文字，
    扫全文会误判。
    """
    head = "\n".join(text.splitlines()[:12])
    for rx, _g in _UNIT_PATTERNS:
        m = rx.search(head)
        if m:
            return m.group(1)
    return ""


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
        # 附注号（`37` / `1` / `七、40` / `56(1)`）先于数值行判断。
        # **顺序很重要**：银行报表是「科目 / 附注号 / 数值」三行一组，
        # `1` 既是合法数值也是附注号。先判数值会把附注号当成本期值，
        # 于是 `现金及存放中央银行款项` = 1（真机实测）。
        # 只在「上一行还没有数值」时认成附注号——否则 `1` 是真正的值（百万位整数）。
        if (rows and not rows[-1][1]
                and re.fullmatch(r"[（(]?\d{1,3}[)）]?|[一二三四五六七八九十]+、\d{1,3}", line)):
            continue
        tokens = line.split()
        if tokens and all(_NUM.match(t) for t in tokens):
            if rows:
                rows[-1][1].extend(tokens)
            continue
        # 续行：上一行还是空值行，且本行像是被切断的后半截。
        # 三种形态都见过（真机样本）：
        #   `销售商品、提供劳务收到的现` + `金`                  —— 短碎片（≤2 字）
        #   `1.归属于母公司股东的净利润` + `（净亏损以"-"号填列）`  —— 括号开头
        #   `经营活动产生的现金流` + `量净额`                    —— **3 字碎片**
        # 第三类是 2026-11-17 抓到的真缺陷：阈值写 2 时它不合并，键就成了「量净额」，
        # 于是**合并报表那一行根本没进正确的键**，而同名键只能由后面母公司报表提供
        # ⇒ 面板上 600965/2024「经营现金流净额」显示 −60,698,503.96（母公司）
        # 而页码写的是合并表的 95 页（正确值是 103,672,405.28）。见
        # openspec change `cnreport-statement-slice-bound`。
        # 只在「上一行无值」时合并，所以不会把两个各有数值的相邻科目粘在一起；
        # 冒号/序号开头（`一、`、`（一）`、`1.`）的仍是真科目，不合并。
        # 续行合并：判「这一行是不是被切碎的后半截」。
        #
        # 两边的真机教训**互相冲突**，所以不能单靠长度阈值：
        #   · 600965/2024：`经营活动产生的现金流` + `量净额`（3 字）不合并 ⇒
        #     合并表那行没进正确键，面板显示母公司数 −60,698,503.96（真值是
        #     103,672,405.28）。见 change `cnreport-statement-slice-bound` 2.0。
        #   · 000001/2024：`一、营业收入` + `利息收入`（4 字）若合并 ⇒
        #     「利息收入」这个真科目整条丢失，而银行报表里 4 字科目极多。
        #
        if rows and not rows[-1][1] and (
            len(line) <= 2
            or line[0] in "（("
            or (len(line) <= 4 and not _ENUMERATED.match(line))
        ):
            rows[-1][0] += line
            continue
        rows.append([line, []])

    out: dict[str, float] = {}
    for label, values in rows:
        if not values:
            continue
        v = _to_float(values[0])
        if v is not None:
            out.setdefault(label, v)
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


#: 报表标题行：`合并/母公司` + 四张表之一，独立成行（正文里就是这样排的）。
#: **只认报表标题，不认裸「附注」**：每张表的列头是「项目 / 附注 / 本期…」，
#: 渲染成文本后 `附注` 会独立成行——实测落在区段第 3–7 行，拿它当边界会把 305 行的
#: 利润表砍到第 4 行，比不裁还糟。
_STATEMENT_TITLE = re.compile(
    r"^\s*(?:合并|母公司)?\s*(?:资产负债表|利润表|现金流量表|所有者权益变动表)\s*$"
)

#: 跳过区段开头若干行：本条报表自己的标题也在开头，别把它当边界。
_BOUND_HEAD_LINES = 2


def _bound_to_statement(body: str) -> tuple[str, str]:
    """把区段裁到**下一张报表的标题**之前，返回 ``(裁剪后正文, 触发裁剪的标题)``。

    为什么必须有这一层：三大表的最后一张（现金流量表）在章节目录里常常**没有后继条目**
    （600965/2024 的目录只有资产负债表/利润表/现金流量表三条，`合并所有者权益变动表`
    根本不在目录里），此时 ``extract_section_text`` 回退到「切到文末」⇒ 现金流量表的
    区段里装进了权益变动表与全部附注（实测 1067 行，第 282 行起是 `合并所有者权益变动表`）。
    ``parse_subject_rows`` 只按标签认行，于是附注里同名标签（如「61、营业收入和营业成本」）
    会被当成报表科目**静默返回错数**——而 `announcement_id` 与页码全都看起来正常。

    副作用是好的：裁剪点在 `母公司xx表` 之前，本函数只留下**合并口径**那张表。
    """
    lines = body.splitlines()
    for i in range(_BOUND_HEAD_LINES, len(lines)):
        if _STATEMENT_TITLE.match(lines[i]):
            return "\n".join(lines[:i]), lines[i].strip()
    return body, ""


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
    body, cut_at = _bound_to_statement(body)
    values = parse_subject_rows(body)

    if not values:
        # 裁剪后一个科目都没有 ⇒ 判不出。不返回空序列、也不把整份文档当报表：
        # 「这份报告里这张表切不出来」与「这张表里没有这个科目」是两件事。
        raise SeriesExportError(
            stock_code, year, statement, subject,
            f"判不出：区段裁剪后没有解析出任何科目（切到 {cut_at or '文末'}）"
            "——可能是切章过度或边界误判，不补零",
        )

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
        # 单位从这份报表的头里读——不同公司/行业不一样（元 vs 百万元）。
        # 读不出就留空，下游必须如实显示「单位未标注」，不许当元。
        unit=detect_unit(body),
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
