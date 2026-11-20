## ADDED Requirements

### Requirement: Detect statement table titles in body text

The system SHALL scan the extracted text for financial statement table titles that are absent from both PDF bookmarks and the heading-regex outline. These include: 合并资产负债表, 合并利润表, 合并现金流量表, 股东权益变动表, 银行资产负债表, 银行利润表, 银行现金流量表. When found, the system SHALL resolve their page number via the page-offset index and inject them as virtual outline entries at level 2 with `source: "statement_detection"`.

#### Scenario: Statement title found in body text
- **WHEN** the text contains "合并资产负债表" on a standalone line (not in TOC, not preceded by 目/录)
- **THEN** the system adds an outline entry `{level: 2, title: "合并资产负债表", page: <detected_page>, source: "statement_detection"}`

#### Scenario: Statement title not found
- **WHEN** none of the statement titles are found in the report body
- **THEN** no virtual entries are added; `resolve_statement` continues to use the body-text fallback (`find_statement_in_text`) as before

### Requirement: TOC line detection for space-separated entries

The `_find_section_start` function's TOC-skip logic SHALL be extended to detect entries like `"合并资产负债表 7-8"` (space-separated title and page range) in addition to dot-leader entries. This prevents TOC lines from being mistaken for body occurrences.

#### Scenario: TOC line is skipped
- **WHEN** a match for "合并资产负债表" is followed by whitespace and a page number or page range (e.g., `" 7-8"`)
- **THEN** the match is treated as a TOC entry and skipped, continuing the search

#### Scenario: Body occurrence is not skipped
- **WHEN** a match for "合并资产负债表" is followed by a newline or table content (not a page number)
- **THEN** the match is accepted as the body occurrence

### Requirement: Statement title detection for bank vs non-bank reports

The system SHALL support both bank-format statements (合并资产负债表) and non-bank statement titles. The detection SHALL be configurable per industry: bank reports detect the full set (including 银行资产负债表, 银行利润表), while non-bank reports detect the standard set (合并资产负债表, 资产负债表, etc.).

#### Scenario: Bank report detection
- **WHEN** the industry is "bank" (or unknown)
- **THEN** all statement titles including bank-specific variants are scanned

#### Scenario: Non-bank report detection
- **WHEN** the industry is explicitly non-bank
- **THEN** only the standard statement titles are scanned
