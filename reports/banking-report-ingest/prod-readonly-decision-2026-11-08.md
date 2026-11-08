# 线上 fd-cn-report 定位裁定（2026-11-08）

- 决策：**线上保持只读 MCP 面**，不做 LLM 抽取（用户裁定 A）。
- 实测依据：部署无 LLM env（任何抽取返回 `LLM_API_KEY not configured`）；`limits.memory=2Gi`，跑 600036 那份 38.7 万字符报告直接 OOM(137)；缓存 60 份报告只有 3 个 `.indicators.json`。
- 现有 Secret `fd-mcp-env` 的网关 `http://124.223.42.3:30080/v1` + `deepseek-v4-flash` 实测 **401 Invalid token**（过期），不能作为线上凭据。
- 抽取事实源：**本机流水线**（462 份报告 / 152,078 章节 / 90 条 golden 锚 / 101 行观测）。
- 规则同步：仅指标级外科同步（`scripts/sync_bank_rules_to_remote.py`，482→491 行），不整库覆盖（线上是 482 条/9 份报告的另一血统）。
- 若日后要开线上抽取：需在 `fd-infra-deploy/all-services/prod/fd-cn-report.yaml` 加 `envFrom.secretRef`（可用凭据见 `paas/.env`：token.finddatatech.cloud + deepseek-v4.1-flash）并把内存提到 ≥4Gi；live patch 会被 Argo 自动 sync 回卷。
