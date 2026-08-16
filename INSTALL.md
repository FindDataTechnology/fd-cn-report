# fd-cn-report — install spec (agent-executable)

> You are an AI agent. A user handed you this file's raw URL. Follow it top to
> bottom. Run every command. Stop and report on the first real failure. This
> spec is idempotent: re-running is safe. Do not commit secrets.

## Goal

Install `fd-cn-report` — an MCP server for Chinese financial reports — and
(optionally) wire it into the finddata open-data hub.

## What is fd-cn-report

- 44 MCP tools covering CNINFO, HKEX, SSE, SZSE, BSE, CSRC, 6 ministries
- 21,698 LLM rules across 31 申万 L1 industries
- AI extraction from annual-report PDFs (DeepSeek on Ark by default)
- Elasticsearch indexing + BM25 search
- Auto-registers via `[project.entry-points."fd_open_data_mcp.datasources"]`
  when installed alongside `fd-open-data-mcp`

## Step 1 — Install

### Option A: standalone (fd-cn-report's own MCP server)

```bash
git clone https://github.com/FindDataTechnology/fd-cn-report.git
cd fd-cn-report
uv sync
```

### Option B: full finddata stack (hub + every datasource + ontology DB)

```bash
pip install "fd-open-data-mcp[data]" fd-polygon fd-cn-report

fd-open-data-mcp migrate \
  && fd-open-data-mcp import-catalog \
  && fd-open-data-mcp consume-concepts \
  && fd-open-data-mcp propose-bindings \
  && fd-open-data-mcp seed-entities \
  && fd-open-data-mcp generate-schedules \
  && fd-open-data-mcp register-discovered
```

`fd-cn-report` auto-registers in `register-discovered` — no manual wiring.

## Step 2 — Environment keys

CNINFO and akshare are **keyless**. The rest need env vars in `.env` (gitignored):

| Var | Used by | Required? |
|-----|---------|-----------|
| `LLM_API_KEY`, `LLM_BASEURL`, `LLM_MODEL` | `ai_extract`, rule generation | Yes for AI features |
| `ES_URL` (+ optional `ES_API_KEY` or `ES_USERNAME`/`ES_PASSWORD`) | `index_records`, `search_reports` | Yes for ES features |
| `EDGAR_IDENTITY` | SEC EDGAR adapter in hub | Yes for EDGAR fetches |

Default LLM provider: **DeepSeek on Ark** (`LLM_BASEURL=https://...api/plan/v1`).
Any OpenAI-compatible endpoint works.

Without keys, install + server start still succeed. Only live fetches against
keyed sources fail (401/403).

## Step 3 — Smoke check

### Standalone mode

```bash
uv run python selfcheck.py           # DB + outline + company API + special reports (no network)
uv run python selfcheck_cache.py     # report cache + three-statements extraction
```

### Full-stack mode

```bash
fd-open-data-mcp list-sources          # cn-report should appear
fd-open-data-mcp list-concepts | head  # should show 926 concepts
```

## Step 4 — Start

### Standalone

```bash
uv run python server.py    # FastMCP over stdio
```

### Full-stack

```bash
fd-open-data-mcp serve     # FastMCP, stdio transport (includes cn-report tools)
```

## Failure modes

| Symptom | Cause |
|---------|-------|
| `ModuleNotFoundError: fd_cn_report` | install didn't complete |
| `selfcheck.py` fails on company API | CNINFO endpoint unreachable (network) |
| `ai_extract` returns empty | `LLM_API_KEY` / `LLM_BASEURL` unset |
| `index_records` fails | `ES_URL` unset or ES unreachable |
| `register-discovered` doesn't find cn-report | entry-point misdeclared |

## What to report back

- install exit code
- selfcheck output (pass/fail per check)
- which env keys are set (do **not** print values)
- whether the server started
