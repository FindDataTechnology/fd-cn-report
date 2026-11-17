## 1. Section Map Data

- [x] 1.1 Create a section-map data file (e.g., docs/report_section_map.json) covering annual/semiannual/quarterly forms with canonical keys + alias titles
- [x] 1.2 Add a loader + lookup helper that returns ordered candidates for (form, key_or_title)
- [x] 1.3 Add minimal validation for the map (non-empty aliases, supported forms/compat keys)

## 2. Alias-Aware Section Resolution

- [x] 2.1 Update indicators_client._resolve_section to expand selector.section via the section-map candidates before calling cnreport_tools.resolve_selector
- [x] 2.2 Record the matched outline title in indicator provenance/source for report-type indicators
- [x] 2.3 Improve missing-section diagnostics: when no selector hits, record attempted candidates (post-expansion) in the missing note

## 3. Rule Gap Audit

- [x] 3.1 Implement an audit entry point that scans indicator_rules.json + out/*.json and classifies indicators into missing_rule/inapplicable_rule/missing_section/unresolved_extractor/llm_null_value
- [x] 3.2 Attach suggested_sections for missing_section items using the section map
- [x] 3.3 Output a stable machine-readable JSON report (with summary counts and per-indicator evidence)

## 4. Regression & Verification

- [x] 4.1 Add tests for section-map alias expansion (canonical key matches an alias title in outline)
- [x] 4.2 Add tests for provenance/missing diagnostics (matched title recorded; attempted candidates recorded on miss)
- [x] 4.3 Add a small offline regression check that re-evaluates a few representative out/ bundles and reports the delta in missing/unresolved/nulls
