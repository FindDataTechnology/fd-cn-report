## Context

This repo already provides:

- A rules database and write/read APIs for rule persistence (LLM rules + script rules).
- Generator skills that can produce LLM rules from excerpts/PDFs and derive script rules and full extraction scripts by `document_type`.

What’s missing is a consistent, industry-aware contract that answers:

- What “industry” means in our system (taxonomy, company type)
- How we name and scope `document_type` to avoid collisions
- What minimum rule coverage is required to call an industry/document_type “supported”
- A repeatable workflow to add a new industry/document_type (so it’s mostly data/rules, not bespoke code)

Constraints:

- We should reuse existing generator skills and the rules database as the source of truth.
- We should avoid creating a large new framework; add a small, explicit layer around taxonomy, naming, and coverage.

## Goals / Non-Goals

**Goals:**

- Define a stable taxonomy model: `industry` + `company_type` + `document_family` → `document_type`.
- Establish a `document_type` naming convention that supports multi-industry scaling and avoids collisions.
- Define rule coverage requirements for an industry/document_type:
  - Minimum set of indicators to extract
  - Required fields in LLM rules (instruction, position hints, etc.)
  - Required script rules derived from LLM rules
  - Validation checks and “supported” readiness gates
- Define an operator workflow (human-in-the-loop) to generate and maintain rules per industry/document_type using existing skills.

**Non-Goals:**

- Building an automated crawler to fetch every company report on the internet.
- Guaranteeing perfect extraction quality for every report layout (this remains iterative and rule-driven).
- Rewriting existing rule generator skills; instead, we standardize how they are applied and how outputs are organized.

## Decisions

### Decision: Keep the source-of-truth in the rules database; add a thin taxonomy layer

**Choice:** Treat taxonomy and naming conventions as “planning/config” that determines which `document_type` we generate and extract against; keep generated rules in the existing rules database.

**Why:** It reuses existing infrastructure and preserves a single runtime source-of-truth. The taxonomy layer is explicit and reviewable, and it prevents proliferation of ad-hoc `document_type` strings.

**Alternatives considered:**

- Store industry-specific rules in separate tables/indices per industry.
  - Rejected: adds operational complexity and complicates cross-industry reuse.

### Decision: Encode industry + company type into `document_type`

**Choice:** Use a structured naming convention for `document_type` such as:

- `cn/<industry>/<company_type>/<report_kind>`

Example (illustrative):

- `cn/bank/listed/annual-report`
- `cn/insurance/listed/annual-report`
- `cn/manufacturing/listed/annual-report`

**Why:** `document_type` is already the primary key for generation and extraction workflows. Encoding taxonomy here avoids collisions and makes selection/filtering simple.

**Alternatives considered:**

- Keep `document_type` generic and add separate `industry` fields everywhere.
  - Rejected: would require broad refactors across generator scripts and extraction pipelines.

### Decision: “Supported” is a coverage gate, not a promise of perfect accuracy

**Choice:** Define support in terms of:

- A declared indicator set for each industry/document_type (must-have indicators)
- Presence of validated LLM rules for those indicators
- Presence of validated script rules derived for those indicators
- A small, repeatable smoke test protocol (golden PDFs / sample pages) to prevent regressions

**Why:** This gives a practical, incremental path: add industry → generate rules → validate → test → iterate.

## Risks / Trade-offs

- **Risk:** `document_type` naming convention conflicts with existing types → **Mitigation:** publish a clear convention and provide a mapping/alias plan where needed.
- **Risk:** Industries have overlapping indicators but different phrasing/positions → **Mitigation:** allow shared base indicator definitions but require per-document_type LLM rules; reuse only when empirically safe.
- **Risk:** Quality variance across report templates → **Mitigation:** define minimal coverage and a test corpus; iterate via rule updates rather than code changes.
- **Trade-off:** Encoding taxonomy into `document_type` can feel verbose → **Mitigation:** provide helper utilities/config to list supported types and reduce manual string usage.

