# cn-official-datasources Specification

## Purpose
TBD - created by archiving change add-cn-official-datasources. Update Purpose after archive.
## Requirements
### Requirement: Datasource client contract
Every new official-website datasource client SHALL follow the existing client convention
shared by `cninfo_client.py` and `hk_stock_client.py`: a module-level `_BASE` URL; a
`_client()` factory returning a per-call `httpx.Client` that tests can patch to inject a
mock; public functions returning uniform dict result objects that MUST NOT raise on a
lookup miss (returning an `ok: false` / empty structure instead); and a default
`trust_env=False` so direct exchange/government calls are not broken by proxy environment
variables. The clients are `sse_client.py`, `szse_client.py`, `bse_client.py`,
`csrc_client.py`, and `ministry_stats_client.py`.

#### Scenario: Lookup miss does not raise
- **WHEN** a caller resolves a non-existent stock code via any new exchange/regulatory client
- **THEN** the client returns a dict with an error/empty indicator and does not raise an exception

#### Scenario: Clients are mockable in tests
- **WHEN** a test patches a client's `_client()` factory to return a mock httpx client
- **THEN** the client's public functions issue no real network calls and return the mock's canned responses

### Requirement: SSE (上交所) datasource tools
The MCP SHALL expose tools backed by `sse_client.py` (`www.sse.com.cn` /
`query.sse.com.cn` / `sns.sseinfo.com`) that: resolve an SSE-listed company by ticker or
name; list periodic and annual-report disclosures for a company and year; fetch a named
section from an SSE annual-report PDF; and fetch 上证e互动 investor Q&A for a company.

#### Scenario: List SSE annual reports
- **WHEN** a caller invokes the SSE filings-list tool with a valid SSE stock code and year
- **THEN** the tool returns a list of disclosure records, each including announcement title, date, and a resolvable PDF URL

#### Scenario: Fetch SSE e-interaction Q&A
- **WHEN** a caller requests 上证e互动 Q&A for a stock code
- **THEN** the tool returns recent investor questions and company replies from `sns.sseinfo.com`

### Requirement: SZSE (深交所) datasource tools
The MCP SHALL expose tools backed by `szse_client.py` (`www.szse.cn/api/...`) that: resolve
a SZSE-listed company; list disclosures for a company and year; fetch a named section from a
SZSE annual-report PDF; and fetch 互动易 investor Q&A.

#### Scenario: List SZSE disclosures
- **WHEN** a caller invokes the SZSE filings-list tool with a valid SZSE stock code and year
- **THEN** the tool returns disclosure records with PDF URLs from the SZSE JSON API

### Requirement: BSE (北交所) datasource tools with CNINFO fallback
The MCP SHALL expose tools backed by `bse_client.py` (`www.bse.cn`) that: resolve a
BSE-listed company; list disclosures for a company and year; and fetch a named section from
a BSE annual-report PDF. Where the BSE API is thinner than SSE/SZSE, the client SHALL fall
back to cross-referencing CNINFO for the same disclosure and SHALL record which source
served the result.

#### Scenario: BSE disclosure served from BSE
- **WHEN** a caller requests a BSE disclosure available on `www.bse.cn`
- **THEN** the tool returns the record sourced from BSE with `source: "bse"`

#### Scenario: BSE disclosure falls back to CNINFO
- **WHEN** a caller requests a BSE disclosure not available via the BSE API but present on CNINFO
- **THEN** the tool returns the record with `source: "cninfo"` indicating the fallback was used

### Requirement: CSRC (证监会) regulatory tools
The MCP SHALL expose tools backed by `csrc_client.py` (`www.csrc.gov.cn`) that: list CSRC
regulatory filings/announcements; query IPO application review status; query 并购重组
(merger & restructuring) review status; and list enforcement actions. CSRC pages that
expose no JSON endpoint SHALL be parsed with `lxml` using selectors isolated in module-level
constants.

#### Scenario: Query IPO review status
- **WHEN** a caller queries IPO review status for a company or application
- **THEN** the tool returns the application's current review stage, meeting date (if any), and result from CSRC

#### Scenario: CSRC announcement listing
- **WHEN** a caller lists CSRC announcements filtered by category and date range
- **THEN** the tool returns announcement records parsed from the CSRC site with title, date, and link

### Requirement: Ministry statistics tools
The MCP SHALL expose structured economic/financial statistic tools backed by a single
`ministry_stats_client.py` covering an initial ministry set: NBS (国家统计局, macro),
MOF (财政部, fiscal), PBoC (人民银行, monetary), SAFE (外汇局, FX/reserves), GACC
(海关总署, trade), and NFRA (金融监管总局, banking/insurance). The module SHALL hold an
internal ministry registry (`{ministry_id: {label, base, endpoints}}`) and per-ministry
query functions. JSON-capable ministries (notably NBS via `data.stats.gov.cn/easyquery.htm`)
SHALL use their JSON API; others SHALL parse HTML tables with `lxml`.

#### Scenario: Query an NBS macro statistic
- **WHEN** a caller requests a national-statistics indicator for a period
- **THEN** the tool returns the value(s) from the NBS `easyquery.htm` JSON API keyed by indicator and period

#### Scenario: Query a ministry HTML statistic
- **WHEN** a caller requests a statistic from a ministry that publishes only HTML tables (e.g. GACC monthly trade)
- **THEN** the tool parses the HTML table with `lxml` and returns structured rows

### Requirement: Complement (not duplicate) fd-cn-gov
Ministry statistics clients SHALL provide structured-stat querying, which is distinct from
`fd-cn-gov`'s catalog-archive document scraping. `ministry_stats_client.py` SHALL reuse
`fd-cn-gov`'s `registry.json` ministry metadata when `fd-cn-gov` is importable, and SHALL
fall back to hardcoded `_BASE` constants when it is not, so `fd-cn-report` remains standalone.

#### Scenario: fd-cn-gov unavailable
- **WHEN** `fd-cn-gov` is not installed/importable
- **THEN** ministry stat tools still resolve their endpoints from hardcoded `_BASE` constants and function correctly

#### Scenario: fd-cn-gov available
- **WHEN** `fd-cn-gov` is importable
- **THEN** `ministry_stats_client.py` reads ministry base-URL metadata from `fd-cn-gov`'s `registry.json` instead of its hardcoded fallback

### Requirement: Stat query caching
Ministry and exchange market-data queries SHALL be cached on disk under `.cache/stats/`,
keyed by endpoint and query arguments, with a per-endpoint TTL. A cache hit SHALL be returned
without a network call. Cache reads/writes MUST NOT raise on miss or corruption (treated as a
miss). Report PDFs continue to flow through the existing `.cache/reports/` cache.

#### Scenario: Cache hit avoids network
- **WHEN** a stat query is repeated within its TTL window
- **THEN** the tool returns the cached value and issues no network call

#### Scenario: Cache corruption treated as miss
- **WHEN** a cached stat file is corrupt or unreadable
- **THEN** the tool treats it as a miss, re-fetches, and does not raise

### Requirement: Rate-limiting and politeness
Each new client SHALL pace requests with a per-client `SLEEP` between calls (default ~0.3s)
and SHALL retry `429`/`5xx` responses with exponential backoff up to a bounded retry count.
Clients SHALL bypass proxy environment variables by default (`trust_env=False`), overridable
per call.

#### Scenario: 429 triggers backoff retry
- **WHEN** a client receives a `429` from an exchange/government endpoint
- **THEN** the client retries with backoff up to the bounded retry count before returning a failure result

### Requirement: Flat-module shipping guardrail
A test SHALL assert that every `*_client.py` module at the `fd-cn-report` package root is
listed in `[tool.setuptools] py-modules`, so a forgotten module fails before release. Each
shipping phase MUST pass `uv build` + `twine check` (no errors/warnings) and a fresh-venv
wheel import smoke test for every new console tool/module.

#### Scenario: Unlisted client module fails the test
- **WHEN** a new `*_client.py` exists at the package root but is absent from `py-modules`
- **THEN** the guardrail test fails, blocking the phase from shipping

#### Scenario: Wheel ships and imports every new module
- **WHEN** a phase is built and installed in a fresh venv
- **THEN** `twine check` passes with no warnings and every new client module imports successfully

