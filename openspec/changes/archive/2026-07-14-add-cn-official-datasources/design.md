## Context

`fd-cn-report` is a flat `py-modules` FastMCP server (26 tools) for Chinese financial-report
extraction. Today it pulls company data from three sources, each a standalone top-level
`*_client.py` module:

| Module | Source | Base URL | Transport |
|---|---|---|---|
| `cninfo_client.py` | CNINFO (巨潮) | `http://www.cninfo.com.cn` | JSON POST + PDF CDN |
| `hk_stock_client.py` | HKEX | `https://www1.hkexnews.hk` | JSON + PDF CDN |
| `financials_client.py` | akshare | (lib) | akshare calls |

Each module follows an established convention: a module-level `_BASE`, a `_client()` factory
returning a per-call `httpx.Client` (tests patch this to inject a mock), small `_post_json` /
`_get_json` helpers, and public functions returning uniform dicts that **never raise on a
lookup miss**. `server.py` registers FastMCP tools that delegate to these clients (often via
`cnreport_tools` imported as `T`). Downloaded report PDFs flow through the on-disk
`.cache/reports/` cache (`report_cache.py`).

`fd-cn-gov` (separate package) already catalog-scrapes 11 ministry *document archives*
(MOF, PBC, NDRC, MOFCOM, MOHURD, MOT, MOA, SAFE, MNR, MEE, MEM) into a `registry.db`/`.json`
- it lists documents, not structured data. `scraw-cnstats`/`scraw-world-bank-data` etc. are
Scrapy bulk crawlers. None of these expose synchronous MCP-queryable company or statistic
tools, which is the gap this change fills.

The new sources have heterogeneous transport: SSE/SZSE/BSE expose (semi-documented) JSON
endpoints; CSRC and most ministries publish data as HTML pages/tables, with NBS the notable
exception (clean `easyquery.htm` JSON API). Several sites rate-limit and/or break behind a
proxy.

## Goals / Non-Goals

**Goals:**
- Add official-website datasource clients for SSE, SZSE, BSE, CSRC, and an initial set of
  ministry departments, each exposed as FastMCP tools with the existing uniform, mockable,
  cached, miss-tolerant interface.
- Reduce single-source dependence on CNINFO for mainland A-share disclosures.
- Give the MCP a primary-source path to regulatory context (CSRC) and macro/financial
  statistics (ministries).
- Make each source **independently shippable and testable** so the large scope can land in
  phases.
- Complement (not duplicate) `fd-cn-gov`: reuse its ministry registry metadata; add the
  structured-stat querying layer that `fd-cn-gov` does not provide.

**Non-Goals:**
- Wiring ministry statistics into the indicator engine as a new extractor routing target
  (a follow-on that would modify `indicator-lookup`; out of scope here).
- Indexing the new sources into Elasticsearch (standalone tools first; ES integration is a
  follow-on).
- Building new `scraw-*` Scrapy projects for these sources (synchronous MCP-query only; bulk
  crawling stays `fd-cn-gov`'s domain).
- Covering all ~26 ministries; an initial 6-stat-set is in scope, the rest deferred.
- Re-spec'ing the existing cninfo / hk / akshare clients (they have no spec today; this
  change introduces the capability fresh).

## Decisions

### D1: One client module per source family, flat at package root
- Exchange clients: `sse_client.py`, `szse_client.py`, `bse_client.py` (one each - their
  endpoints differ enough to warrant separation, mirroring `hk_stock_client.py`).
- `csrc_client.py` for CSRC (distinct regulatory data type).
- **One** `ministry_stats_client.py` for all ministries, with an internal registry
  (`{ministry_id: {label, base, endpoints}}`) and per-ministry query functions - mirrors
  `fd-cn-gov`'s MANIFEST-per-scraper idea but as a single flat module, avoiding 6 near-
  identical files.
- Rationale: matches the existing flat `py-modules` layout; each module is independently
  mockable. Alternative (one giant `official_clients.py`) rejected - loses per-source
  test isolation.

### D2: Transport - JSON-first, `lxml` fallback for HTML
- SSE (`query.sse.com.cn`), SZSE (`www.szse.cn/api/...`), BSE (`www.bse.cn` JSON), NBS
  (`data.stats.gov.cn/easyquery.htm`) use JSON endpoints -> `httpx` only, no parser.
- CSRC and MOF/PBoC/SAFE/GACC/NFRA publish HTML tables -> add **`lxml`** as a dependency for
  XPath-based extraction. Chosen over `selectolax` (lighter but weaker on messy gov HTML/tables)
  and `parsel` (would pull scrapy-style deps into a non-scrapy package).
- Selectors isolated in module-level `_SELECTORS`/`_XPATH` constants for easy patching when
  sites change.

### D3: Reuse the existing client/cache contract
- Every new client: module-level `_BASE`, `_client()` httpx factory (mockable), uniform dict
  returns, no-raise-on-miss. PDFs go through the existing `report_cache.py`.
- Add a lightweight **stat-cache** (file-based JSON with TTL, under `.cache/stats/`) for
  ministry/exchange market-data queries that are expensive and low-frequency-changing.
  Rationale: `report_cache.py` keys on PDF URL; stat queries need a TTL-keyed cache.

### D4: Rate-limiting & politeness
- Per-client `SLEEP` (default ~0.3s, matching `fd-cn-gov`) between calls + retry/backoff on
  429/5xx via an httpx transport. Document the proxy caveat (proxy env vars break direct
  exchange/gov calls, same class of issue as the akshare gotcha) - clients SHALL default to
  bypassing proxy env (`trust_env=False`) unless overridden.

### D5: Phasing - exchanges → CSRC → ministries
- **Phase 1**: SSE + SZSE + BSE (JSON APIs, parallel to cninfo disclosure flow, highest
  value, unblocks CNINFO redundancy).
- **Phase 2**: CSRC (regulatory, HTML).
- **Phase 3**: ministry stat clients (mixed JSON/HTML, reuse `fd-cn-gov` registry metadata).
- Each phase is a shippable increment with its own tests; `tasks.md` sequences them.

### D6: `fd-cn-gov` reuse is optional, not a hard dependency
- `ministry_stats_client.py` SHALL read `fd-cn-gov`'s `registry.json` for ministry base URLs/
  metadata **if importable** (`try/except ImportError`), else fall back to hardcoded `_BASE`
  constants. Keeps `fd-cn-report` standalone (matches its current zero-cross-package-dep
  posture) while deduplicating metadata when both are installed.

### D7: Ship guardrail for flat py-modules
- A test SHALL assert `[tool.setuptools] py-modules` includes every `*_client.py` at the
  package root, so a forgotten module fails CI rather than silently not shipping. The
  wheel smoke test (`uv build` + `twine check` + fresh-venv import) is a per-phase gate.

## Risks / Trade-offs

- **[Undocumented/shifting exchange & gov APIs]** -> clients pin to known endpoints, stay
  thin, record fixtures under `test_fixtures/`, mark endpoints `# undocumented`; a `selfcheck`
  extension pings each endpoint and flags 4xx/5xx without failing the suite.
- **[HTML parsing fragility on gov sites]** -> JSON-first (D2); isolate selectors; prefer NBS
  JSON API for macro; accept that MOF/PBoC/GACC HTML selectors may need patching - documented
  in each module.
- **[Rate-limiting / IP blocks]** -> D4 SLEEP + backoff + `trust_env=False`; document proxy
  caveat.
- **[BSE thinner APIs]** -> BSE phase may cross-reference CNINFO (BSE disclosures are also on
  CNINFO); document the fallback in `bse_client.py`.
- **[Large scope / creep]** -> D5 phasing; each phase independently shippable; non-goals
  explicitly exclude indicator routing and ES indexing.
- **[Ministry overlap with `fd-cn-gov`]** -> D6 makes reuse optional; the value-add (structured
  stats vs document catalog) is distinct and documented per ministry.

## Migration Plan

Pure addition - no existing tool changes, no breaking changes. No data migration. Rollback =
remove the new modules + their `server.py` tool registrations + their `py-modules` entries
(revertible per phase). Ship under a minor version bump per phase. No PyPI re-upload of an
existing version (yank rule from CLAUDE.md still applies if a phase's version is broken).

## Open Questions (resolved during implementation)

- **Ministry set**: implemented the proposed 6 - NBS, MOF, PBoC, SAFE, GACC, NFRA. MOF/PBoC/SAFE
  overlap with `fd-cn-gov`'s catalog scrapers, but the value-add here is structured-stat
  querying (data values, not document lists), so they are retained. `ministry_stats_client`
  reuses `fd-cn-gov` base URLs when importable (MOF/PBoC/SAFE, via `_fdcn_gov_lookup`) and falls
  back to hardcoded `_MINISTRIES` entries otherwise; NBS/GACC/NFRA are not in `fd-cn-gov` and
  use hardcoded bases.
- **SZSE 互动易 hosting**: resolved - exposed under `szse_client.get_szse_interaction`
  (hosted on `irm.cninfo.com.cn`), giving SZSE investor Q&A a single entry point rather than a
  cninfo extension.
- **Stat-cache TTL defaults**: all ministries default to 6h (`_MINISTRIES[*].ttl = 6*3600`).
  Per-ministry tuning (NBS annual vs PBoC weekly vs GACC monthly) is deferred - the TTL is a
  per-ministry config field, adjustable without changing the query path.

## Live-verification status (deferred to operator)

All exchange/regulatory/ministry endpoints are undocumented and were built from best-known
shapes; mocked tests assert the *assumed* contract only. Run
`CNREPORT_SELFCHECK_LIVE=1 uv run python selfcheck.py` to ping each source - 4xx/5xx are
flagged per source without failing the suite. Endpoints needing correction after live
verification are centralized: `_URLS`/`_SELECTORS` (csrc_client), `_MINISTRIES[*].stat_path`
(ministry_stats_client), and the per-client `_BASE`/path constants (sse/szse/bse).
