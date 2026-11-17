## 1. Taxonomy + document_type conventions

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
- [ ] 4.3 Generate and persist LLM rules for each initial industry/document_type using representative PDFs/excerpts
- [ ] 4.4 Generate and persist script rules for each initial industry/document_type derived from the LLM rules
- [ ] 4.5 Run coverage checker and ensure each initial industry/document_type reaches “supported” status

## 5. Smoke testing and regression protection

- [ ] 5.1 Create a small golden PDF corpus per initial industry/document_type (or approved sample pages) for smoke tests
- [ ] 5.2 Add an automated smoke test that runs extraction for the golden corpus and asserts baseline indicator presence
- [x] 5.3 Add a CI-friendly report (per document_type) showing pass/fail and missing indicators to guide rule iteration

