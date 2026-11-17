# Tasks — add-cn-official-datasources

Phased per `design.md` D5: **Phase 1** = SSE + SZSE + BSE (JSON APIs, highest value,
unblocks CNINFO redundancy) → **Phase 2** = CSRC (regulatory, HTML) → **Phase 3** = ministry
statistics (mixed JSON/HTML, reuse `fd-cn-gov`). Each phase is independently shippable.

Identity contract: add NEW tools/modules only - do not rename or change existing tools,
flags, or env vars. `fd-cn-report` is flat `py-modules`: every new top-level module MUST be
listed in `[tool.setuptools] py-modules` or it will not ship (enforced by task 1.3).

## 1. Foundation & shared contract

- [x] 1.1 Add `lxml` to dependencies in `pyproject.toml` (HTML-scraping clients) and `uv sync`
- [x] 1.2 Create `official_client_utils.py`: shared retry/backoff httpx transport, `trust_env=False` client factory, per-client `SLEEP` helper, and stat-cache read/write under `.cache/stats/` (TTL-keyed, miss/corruption-tolerant)
- [x] 1.3 Add guardrail test asserting every `*_client.py` (and `official_client_utils.py`) at the package root is listed in `[tool.setuptools] py-modules`
- [x] 1.4 Extend `selfcheck.py` with a non-failing endpoint-ping section that flags 4xx/5xx per new source

## 2. Phase 1 — SSE (上交所)

- [x] 2.1 Create `sse_client.py`: `_BASE`, `_client()` (mockable, `trust_env=False`); `get_sse_company` (resolve ticker/name) and `list_sse_filings` (periodic + 年度报告) via `query.sse.com.cn`
- [x] 2.2 `get_sse_section`: fetch a named section from an SSE annual-report PDF through `report_cache.py`
- [x] 2.3 `get_sse_interaction`: 上证e互动 investor Q&A via `sns.sseinfo.com`
- [x] 2.4 Register SSE FastMCP tools in `server.py`
- [x] 2.5 `test_sse_client.py` with mocked httpx + recorded fixtures under `test_fixtures/sse/`
- [x] 2.6 Add `sse_client.py` + `official_client_utils.py` to `[tool.setuptools] py-modules`

## 3. Phase 1 — SZSE (深交所)

- [x] 3.1 Create `szse_client.py`: `get_szse_company`, `list_szse_filings` via `www.szse.cn/api/...`, `get_szse_section`
- [x] 3.2 `get_szse_interaction`: 互动易 Q&A (hosted on `irm.cninfo.com.cn` — resolve hosting per open question)
- [x] 3.3 Register SZSE FastMCP tools in `server.py`
- [x] 3.4 `test_szse_client.py` + fixtures under `test_fixtures/szse/`
- [x] 3.5 Add `szse_client.py` to `[tool.setuptools] py-modules`

## 4. Phase 1 — BSE (北交所)

- [x] 4.1 Create `bse_client.py`: `get_bse_company`, `list_bse_filings` via `www.bse.cn`, `get_bse_section`
- [x] 4.2 Implement CNINFO cross-reference fallback with a `source` field (`bse` | `cninfo`) for thin BSE API coverage
- [x] 4.3 Register BSE FastMCP tools in `server.py`
- [x] 4.4 `test_bse_client.py` + fixtures, including the CNINFO-fallback scenario
- [x] 4.5 Add `bse_client.py` to `[tool.setuptools] py-modules`

## 5. Phase 1 ship gate

- [x] 5.1 `uv build` + `twine check dist/*` (no errors/warnings)
- [x] 5.2 Fresh-venv wheel smoke test (`uv venv /tmp/v --python 3.12` + install wheel + import each exchange client + `fd-cn-report --help`)
- [x] 5.3 Update README tool table + add per-source sections for SSE/SZSE/BSE
- [x] 5.4 `pytest` + `selfcheck.py` green; minor version bump

## 6. Phase 2 — CSRC (证监会)

- [x] 6.1 Create `csrc_client.py`: `_BASE`, `lxml` selectors isolated in module-level `_SELECTORS`; `list_csrc_filings` (announcements by category + date range)
- [x] 6.2 `get_csrc_ipo_review`: IPO application review stage, meeting date, result
- [x] 6.3 `get_csrc_merger_review`: 并购重组 review status
- [x] 6.4 `list_csrc_enforcement`: enforcement actions
- [x] 6.5 Register CSRC FastMCP tools in `server.py`
- [x] 6.6 `test_csrc_client.py` with HTML fixtures under `test_fixtures/csrc/`
- [x] 6.7 Add `csrc_client.py` to `[tool.setuptools] py-modules`; run Phase 2 ship gate (build/twine/smoke)

## 7. Phase 3 — Ministry statistics

- [x] 7.1 Create `ministry_stats_client.py` with internal ministry registry for the initial set: NBS, MOF, PBoC, SAFE, GACC, NFRA
- [x] 7.2 Optional `fd-cn-gov` `registry.json` metadata read with `try/except ImportError` fallback to hardcoded `_BASE`
- [x] 7.3 NBS query via `data.stats.gov.cn/easyquery.htm` JSON API
- [x] 7.4 MOF / PBoC / SAFE / GACC / NFRA HTML-table queries via `lxml` (per-ministry functions, selectors isolated)
- [x] 7.5 Wire stat-cache (`.cache/stats/` TTL) via `official_client_utils` for ministry/exchange market-data queries
- [x] 7.6 Register ministry FastMCP tools in `server.py`
- [x] 7.7 `test_ministry_stats_client.py` with JSON (NBS) + HTML (e.g. GACC) fixtures
- [x] 7.8 Add `ministry_stats_client.py` to `[tool.setuptools] py-modules`; run Phase 3 ship gate

## 8. Finalization

- [x] 8.1 Resolve open questions from `design.md` (ministry set confirmation, SZSE 互动易 hosting, stat-cache TTL defaults); update design.md
- [x] 8.2 Full `pytest` + `selfcheck.py` green; confirm py-modules guardrail test passes with all new modules
- [x] 8.3 README tool table + per-source sections complete for all sources; final minor version bump
- [x] 8.4 Update auto-memory `MEMORY.md` pointer noting the new `cn-official-datasources` capability and phasing status
