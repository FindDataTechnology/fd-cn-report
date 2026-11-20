## Why

Current PDF section positioning uses text-based heading regex parsing and body-text search, which frequently fails: (1) financial statement titles like "合并资产负债表" don't match the heading regex, so they're invisible to the outline; (2) `_find_section_start` falls back to generic tokens like `"3."` that match wrong positions; (3) TOC skip only handles dot-leaders, not space-separated entries. This causes 207/309 indicators to fail extraction because sections point to narrative discussion chapters instead of actual financial statements.

## What Changes

- Add `pymupdf` (fitz) as a PDF-processing dependency alongside `pypdf`
- Refactor `parse_outline` to read PDF bookmarks (`doc.get_toc()`) for precise section titles with page numbers
- Add financial statement titles (合并资产负债表, 合并利润表, 合并现金流量表, 股东权益变动表, 银行资产负债表, 银行利润表, 银行现金流量表) to the outline index via body-text scanning, since these are absent from both the current parsed outline and PDF bookmarks
- Refactor `_find_section_start` / `extract_section_text` to use page-number boundaries from the outline instead of body-text search, eliminating TOC-spill and wrong-position bugs
- Remove or fix the TOC dot-leader skip to also cover space-separated `"标题 页码"` patterns

## Capabilities

### New Capabilities
- `pymupdf-outline-parser`: Parse PDF bookmarks via `pymupdf.get_toc()` and map page numbers to extracted-text character offsets for precise section slicing
- `statement-title-detection`: Detect financial statement table titles (合并资产负债表, etc.) in body text and add them to the outline with page-level positions

### Modified Capabilities
- `indicator-extraction-script`: Section resolution will use page-boundary slicing instead of text-position search; output may change for indicators that previously got wrong-section text

## Impact

- `cnreport_tools.py`: `parse_outline`, `_find_section_start`, `extract_section_text`, `resolve_selector`, `resolve_statement` — major refactor
- `report_cache.py`: May need to cache `pymupdf` page-offset data alongside text
- `pyproject.toml`: `pymupdf` already added as dependency
- PDF extraction results for 000001/2025 and all previously processed reports: more indicators should resolve correctly
