## 1. Taxonomy + document_type conventions

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
- [ ] 5.2 Add an automated smoke test that runs extraction for the golden corpus and asserts baseline indicator presence
- [x] 5.3 Add a CI-friendly report (per document_type) showing pass/fail and missing indicators to guide rule iteration

