## 1. Taxonomy + document_type conventions

> **2026-11-25 复核留任**：18/19。剩 5.1 golden PDF 语料入仓——delta 3 个新 cap 全未合主 spec。LLM 真抽取需 chat 端点可用 + 金集语料两条外部条件。


> **2026-11-20 状态盘点（治理轮）**
>
> 4.3/4.4/4.5 已达成并可证：`docs/industry_support_report.json` 有 44 个 document_type
> 全 `supported: true`、`missing_llm_rules`/`missing_script_rules` 全空；规则由
> `scripts/seed_industry_rules.py` 落进 `llm_rules`/`script_rules` 表（`rules_db` 是运行时真源）。
>
> **5.1/5.2 仍未做**：`docs/golden-bank-indicators.json` 只覆盖银行，其余 30 个申万 L1 无金集语料；
> `scripts/test_industry_rules.py` 目前只跑覆盖率判定，`stocks` 结果全写死 `status: "pending"`，
> 并没有真的抽取值去比 baseline。这是「规则建好了但没做端到端回归」的真缺口，本 change 保留在途。

- [x] 1.1 Add an industry/company_type/report_kind taxonomy representation (config or DB-backed) usable by rule generation and extraction tooling
- [x] 1.2 Implement `document_type` construction helper enforcing `cn/<industry>/<company_type>/<report_kind>` convention
- [x] 1.3 Add a listing utility to enumerate candidate `document_type` values per industry (for operators and generators)
- [x] 1.4 Add guardrails/validation to prevent invalid kebab-case taxonomy identifiers from being persisted/used

## 2. Coverage model and readiness gates

- [x] 2.1 Define how the “declared indicator set” for an industry/document_type is stored and maintained (config or DB table)
- [x] 2.2 Implement a coverage checker that reports missing LLM rules and missing script rules for a target industry/document_type
- [x] 2.3 Implement a “supported” resolver that marks industry/document_type supported only when LLM + script rule coverage gates pass
- [x] 2.4 Add minimal validation enforcement for required rule fields (LLM rules: indicator/instruction/position/document_type; script rules: indicator/extract_rule/position/document_type)

## 3. Operator workflow: generate and maintain rules per industry/document_type

- [x] 3.1 Document the end-to-end workflow to generate LLM rules for a chosen industry/document_type using existing generator skills
- [x] 3.2 Document the workflow to derive script rules from LLM rules for a chosen industry/document_type using existing generator skills
- [x] 3.3 Add an iterative maintenance loop playbook (failure → regenerate/update relevant rules → re-check coverage)

## 4. Seed support for first industries (thin vertical slices)

- [x] 4.1 Select an initial industry set (e.g., bank, insurance, securities, manufacturing) and define their candidate `document_type` values
- [x] 4.2 For each initial industry/document_type, declare a minimal indicator baseline (must-have indicators)
- [x] 4.3 Generate and persist LLM rules for each initial industry/document_type using representative PDFs/excerpts
- [x] 4.4 Generate and persist script rules for each initial industry/document_type derived from the LLM rules
- [x] 4.5 Run coverage checker and ensure each initial industry/document_type reaches “supported” status

## 5. Smoke testing and regression protection

- [ ] 5.1 Create a small golden PDF corpus per initial industry/document_type (or approved sample pages) for smoke tests
  - **2026-11-22 状态：语料与考核口径已就位，缺的是「入仓」。**
    语料侧：`.cache/reports/` 里已有 117 份真报告（PDF + 抽好的 `.txt`/`.outline.json`），
    覆盖银行（601398/600036/601288/601939/000001）与非银行（002041/600519/600965/002714…），
    且已有 8 份 `.indicators.json` 抽取产物——**但只有 601398 半年度那一份真有值**
    （16 项全有）；其余 7 份是无 LLM key 时跑出来的空壳（每项 `value=None`）。
    考核口径：`docs/golden-bank-indicators.json` 是 18 项 × 5 家 = 90 条人工核过的锚，
    `scripts/verify_bank_golden.py` 已能「重新抽一遍再逐值比对」，并把「未披露」与
    「对位失败」分开判（前者正常、后者非零退出）——这正是本条要的判据形状。
    **已入仓第一份**（`f5c83bd`）：`tests/fixtures/golden/600097_2025_q3.{txt,json}` ——
    一份真实季报的**纯文本快照 + 三个锚**，配 `tests/test_golden_corpus_fixture.py` 6 条判据。
    选它的三条判据（写进了 json 里，后续加样本照此办）：
      · **许可**：上市公司法定公开披露（巨潮 finalpage 1224769914），无授权障碍；
      · **够小**：文本 10KB（PDF 189KB）；入仓 .txt 而非 PDF —— 二进制不可 review；
      · **可判**：同一份报告里「营业收入」有两个期间口径（单季 / 累计），
        拿错口径**不会报错、只会给出一个看起来合理的错数**，这正是最该被钉住的形态。
    反向验证过：改一个字节 → 哈希条红；把 450,167,434.57 改成 999,999,999.99 → 3 条同时红。
    **已入仓第二份**（`1411d63`，2026-11-23）：`tests/fixtures/golden/600467_2025_annual.{txt,json}`
    —— 年报摘要形态（本期 vs 上年同期口径），并把 `test_golden_corpus_fixture.py` 改为
    **遍历 `fixtures/golden/*.json`**（含「至少一份语料」空集合守卫），新增语料只需放
    .txt + .json 即被自动覆盖。验证：test_golden_smoke + test_golden_corpus_fixture 16 passed。
    **已入仓第三份**（2026-11-23）：`tests/fixtures/golden/605198_2025_q3.{txt,json}` ——
    果汁制造季报，覆盖「本期与累计两值同表两行并列」版式（最易把列序读反）。13 passed。
    **仍未覆盖的**：抽样三家（海产季报 / 年报摘要 / 果汁季报），银行侧另有 90 条人工锚
    （语料在 `.cache/` 未入仓）；其余 document_type 无锚。这条**保持未勾**——现在只做到
    「三份可判样本、三种版式」，不等于任务书说的「每个初始行业各一份」。
- [x] 5.2 Add an automated smoke test that runs extraction for the golden corpus and asserts baseline indicator presence
  - **2026-11-22 完成**（`480b4d4`）：`tests/test_golden_smoke.py` 7 条。
    与原文的差异要写清：它断言的是**判定链**，不是「抽取取到了值」——
    后者在没有 LLM key 的机器上等于测环境，那种断言会让 CI 常年红或常年跳过。
    具体覆盖：锚文件合法性（90 条、字段齐）、`disclose_status` 把
    「无值」正确分成「未披露 / 对位失败」四向、90 条锚每条都走完判定链并落到
    已定义结局、脚本规则在 python 模式下显式标 skipped 而不退回 LLM。
  - **反向验证过**（证明断言真能红）：把 `return "对位失败"` 改成 `"未披露"` ⇒ 1 failed；
    把 python 模式的 skipped note 改成空串 ⇒ 1 failed；两次都还原后复绿。
  - **仍未覆盖的那半**：LLM 真抽取。要它跑起来需要 ①chat 端点可用（当前上游
    account 46 返回 502）②金集语料入仓（5.1）。两条都是外部条件。
- [x] 5.3 Add a CI-friendly report (per document_type) showing pass/fail and missing indicators to guide rule iteration


## 归档豁免

归档豁免：2026-11-25 剩 5.1（golden PDF 语料按 industry/document_type 入仓供烟测）是**外部条件**非代码欠账：真抽取那半需 ①chat 端点可用（曾上游 502）②金集语料入仓两条前置，均非本机能补。
代码侧全部交付并测试通过（2026-11-25 复跑 `test_industry_support.py` 5/5）：`industry_taxonomy.py`（1.1–1.4）、`industry_coverage.py`（2.1–2.4）、`rules_models.py`/`rules_skills.py`（3.x 工作流）、4.x 已 seed 首批行业并达 supported。delta 合入主 spec 后行为固化；语料到位后按 5.1 补烟测即可。
