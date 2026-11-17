# report-section-map

## Purpose

Standardize report section targeting across companies and report forms by maintaining a canonical section key set with alias titles, enabling selector resolution to be robust to TOC/outline naming differences.

## ADDED Requirements

### Requirement: Section map defines canonical keys and aliases per report form
The system SHALL maintain a section map data source that, for each supported periodic report form (annual/semiannual/quarterly), defines canonical section keys and a non-empty list of alias titles for matching report TOC/outline headings.

#### Scenario: Canonical key expands to multiple aliases
- **WHEN** the map defines the canonical key `财务报表附注`
- **THEN** it contains at least one alias title (e.g., `财务报表附注`, `合并财务报表附注`, `附注`).

### Requirement: Map lookup returns ordered candidates for matching
Given an input `(form, key_or_title)`, the system SHALL return an ordered list of match candidates suitable for section resolution. If `key_or_title` is a canonical key, candidates SHALL be the canonical key followed by its aliases. If it is not a canonical key, the list SHALL contain the input title itself.

#### Scenario: Non-canonical title returns itself
- **WHEN** lookup is called with a title not present as a canonical key
- **THEN** the candidate list equals `[<input title>]`.

### Requirement: Map supports form compatibility keys
The section map SHALL be addressable both by the raw report form (`年度报告`, `半年度报告`, `第一季度报告`, `第三季度报告`) and by the compatibility keys used for rule gating (`年报`, `半年报`, `季报`).

#### Scenario: Quarterly forms share the same map
- **WHEN** lookup is called for `第一季度报告` and `第三季度报告`
- **THEN** both resolve to the same compatibility key and yield the same candidates for a given canonical key.

