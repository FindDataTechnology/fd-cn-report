## Why

We need a scalable way to ingest and extract indicators from **financial reports across different industries** (banks, insurance, securities, manufacturing, real estate, internet, utilities, etc.). Today, rule generation is possible, but there is no clear contract for **industry → document_type → indicator set → LLM rules → script rules** that makes adding a new industry predictable and repeatable.

## What Changes

- Introduce an **industry-aware report model** that standardizes how we represent industries, companies, and the financial report document types we ingest.
- Define a repeatable workflow to generate and maintain:
  - **LLM rules** per `document_type` (industry-specific indicators + extraction instructions + positions)
  - **Script rules** per `document_type` derived from LLM rules
- Add conventions for naming and scoping `document_type` so rules don’t collide across industries and company types.
- Provide validation and coverage expectations so each industry/document_type has a minimum viable rule set before being considered supported.

## Capabilities

### New Capabilities
- `industry-report-taxonomy`: Define industry/company taxonomy and the mapping to supported financial report `document_type` values.
- `industry-rules-coverage`: Define “supported” criteria and coverage/validation requirements for LLM rules + script rules per industry/document_type.
- `industry-rules-generation-workflow`: Define the end-to-end workflow to generate rules for a target industry/document_type using existing generator skills and the rules database.

### Modified Capabilities
- (none)

## Impact

- Affects how we define and select `document_type` when generating rules and extracting indicators.
- Adds new specs that will guide new rule generation and ingestion work, but should not break existing rule generation skills.
- May require updates to any code that assumes a single global `document_type` namespace without industry scoping.

