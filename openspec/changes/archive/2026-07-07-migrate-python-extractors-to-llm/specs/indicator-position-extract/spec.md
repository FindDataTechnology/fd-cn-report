## MODIFIED Requirements

### Requirement: Section resolution walks the selector chain with statement-table priority
For `report` rules in the `balance_sheet`, `income_statement`, or `cashflow` modules, the system SHALL resolve the section by walking `selectors[]` in order, expanding each `selector.section` through the section map's alias candidates. When a selector like `资产负债表` would match an MD&A analysis sub-section (e.g. `7.2.2 资产负债表项目分析`) via substring, the system SHALL first try the canonical consolidated statement title (`合并资产负债表` / `合并利润表` / `合并现金流量表`) as an expanded candidate before falling back to the MD&A match. The batch extraction path in `extract_indicators` SHALL pass `form=ctx.form` to `_resolve_section` so the section map is form-aware.

#### Scenario: Balance sheet selector resolves to the statement table, not MD&A
- **WHEN** a `balance_sheet` rule declares `selectors: [{section: "资产负债表"}]` and the outline contains both `"7.2.2 资产负债表项目分析"` and `"合并及公司资产负债表"`
- **THEN** the resolved section is the consolidated statement table (not the MD&A analysis), and the LLM receives the actual financial data.

#### Scenario: Form is passed to section resolution in batch path
- **WHEN** `extract_indicators` is called with `form="半年度报告"`
- **THEN** `_resolve_section` receives `form="半年度报告"` and the section map returns semiannual-specific aliases.
