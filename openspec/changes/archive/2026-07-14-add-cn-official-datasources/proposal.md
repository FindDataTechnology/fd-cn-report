## Why

`fd-cn-report` extracts Chinese company financial data from only three sources today:
**CNINFO** (the disclosure aggregator), **HKEX** (Hong Kong), and **akshare** (三大报表).
For mainland A-share companies it depends entirely on CNINFO, with no direct path to the
exchanges' own disclosure portals, their interactive investor Q&A
(上证e互动 / 互动易), or exchange market data; and it has no access to **CSRC** regulatory
context (IPO / 并购重组 review, enforcement) or to the structured economic/financial
statistics published by **ministry-level departments (部级部门)**. Adding these
official-website datasources gives the MCP a primary-source view of Chinese company and
macro-financial data, reduces single-source dependence on CNINFO, and lets extraction pull
values straight from the issuing authority.

## What Changes

- **SSE client (`sse_client.py`)** — 上交所 (`www.sse.com.cn`): resolve SSE-listed
  companies; list/query annual-report & periodic disclosures from the SSE disclosure
  portal; fetch 上证e互动 Q&A; market/index snapshots. New MCP tools
  (`get_sse_company`, `list_sse_filings`, `get_sse_section`, `get_sse_interaction`, …).
- **SZSE client (`szse_client.py`)** — 深交所 (`www.szse.cn`): resolve SZSE-listed
  companies; disclosure listing; 互动易 Q&A; market data. New MCP tools.
- **BSE client (`bse_client.py`)** — 北交所 (`www.bse.cn`): resolve BSE-listed companies;
  disclosure listing (where CNINFO coverage is thinner). New MCP tools.
- **CSRC client (`csrc_client.py`)** — 证监会 (`www.csrc.gov.cn`): list regulatory
  filings/announcements; query IPO & 并购重组 review status; enforcement actions.
  New MCP tools.
- **Ministry datasource clients (部级部门)** — expose structured economic/financial
  **statistics** as queryable MCP tools, complementing `fd-cn-gov`'s catalog-archive
  scrapers (which list *documents*, not *data*). Initial set: NBS (国家统计局, macro),
  MOF (财政部, fiscal), PBoC (人民银行, monetary), SAFE (外汇局, FX/reserves),
  GACC (海关总署, trade), NFRA (金融监管总局, banking/insurance). Reuse `fd-cn-gov`
  registry metadata and any already-structured ministry endpoints where applicable.
- **Wire all new clients as FastMCP tools in `server.py`**, following the existing
  `cninfo_client` / `hk_stock_client` pattern: per-call `httpx` client (mockable),
  on-disk report cache, uniform result objects that never raise on lookup miss.
- **Ship & document**: add every new top-level module to `[tool.setuptools] py-modules`
  (flat-package requirement — unlisted modules do not ship in the wheel); extend the
  README tool table and add per-source sections.

## Capabilities

### New Capabilities
- `cn-official-datasources`: Official-website datasource clients for SSE, SZSE, BSE, CSRC,
  and ministry-level departments, exposing company disclosures, regulatory filings, and
  economic/financial statistics as FastMCP tools with a uniform, mockable, cached,
  miss-tolerant interface. Establishes the `*_client.py` contract that the existing
  cninfo / hk / financials clients already follow informally.

### Modified Capabilities
<!-- None. The existing cninfo / hk / akshare clients have no spec today; this change
     introduces the datasource-client capability fresh. Indicator routing to ministry
     stats (a new extractor target in indicator-lookup) is an optional follow-on, not
     part of this change. -->

## Impact

- **New code**: `sse_client.py`, `szse_client.py`, `bse_client.py`, `csrc_client.py`, and
  one or more ministry client modules at the `fd-cn-report` package root (flat py-modules).
- **`server.py`**: register ~15–25 new FastMCP tools delegating to the new clients.
- **`pyproject.toml`**: extend `[tool.setuptools] py-modules` with every new module.
- **`README.md`**: extend the tool table; add per-source usage sections.
- **Dependencies**: `httpx` already in use; may add a lightweight HTML parser
  (`lxml` or `selectolax`) for exchange/ministry pages that lack JSON APIs. No heavy deps.
- **Tests**: new `test_<src>_client.py` per source using mocked `httpx` (matching the
  existing `test_cnreport.py` pattern) + a `selfcheck.py` extension.
- **Relationship to `fd-cn-gov`**: ministry coverage *complements* (not duplicates)
  `fd-cn-gov`'s 11 catalog-archive scrapers — fd-cn-gov lists documents; fd-cn-report
  exposes structured statistics as queryable tools. Reuse `fd-cn-gov` registry metadata.
- **Relationship to `scraw-*`**: new clients are synchronous MCP-query tools, not Scrapy
  crawlers; no new `scraw-*` project is required. Bulk ministry crawling stays
  `fd-cn-gov`'s domain.
- **Scope guardrail**: phasing (exchanges first, then CSRC, then ministries) is captured
  in `tasks.md`; each source is independently shippable.
