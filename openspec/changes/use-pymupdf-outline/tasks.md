## 1. Page-offset index from pypdf

- [ ] 1.1 Add `get_pypdf_page_offsets(pdf_bytes: bytes) -> list[int]` in `cnreport_tools.py` that extracts text per-page and records cumulative character counts, returning `[0, p1_end+1, p2_end+1, ...]`
- [ ] 1.2 Verify alignment: total chars from offset index matches `len(full_text)` from `extract_pdf_text`

## 2. Pymupdf outline parser

- [ ] 2.1 Add `parse_pymupdf_outline(pdf_bytes: bytes) -> list[dict]` that calls `fitz.Document(pdf_bytes).get_toc()` and returns entries as `{level, title, page, source: "pymupdf"}`
- [ ] 2.2 Add `merge_outlines(pymupdf_entries, regex_entries) -> list[dict]` — merge pymupdf bookmarks with regex outline, deduplicated by normalized title, pymupdf entries first
- [ ] 2.3 Add `page_to_char_offset(page: int, offsets: list[int], page_count: int) -> int` helper that converts page number to character offset (1-based page 1 = offsets[0])

## 3. TOC skip fix

- [ ] 3.1 Extend `_find_section_start` to also skip space-separated `"合并资产负债表 7-8"` entries by checking if the text after the match is whitespace + digit-range pattern

## 4. Statement title detection

- [ ] 4.1 Add `STATEMENT_TITLES` dict in `cnreport_tools.py` mapping module keys to all known statement table titles (合并资产负债表, 合并利润表, 合并现金流量表, 股东权益变动表, 银行资产负债表, 银行利润表, 银行现金流量表)
- [ ] 4.2 Add `detect_statement_titles(text: str, page_offsets: list[int]) -> list[dict]` that scans body text for these titles on standalone lines (not in TOC), resolves their page via offset index, and returns `{level: 2, title, page, source: "statement_detection"}`
- [ ] 4.3 Integrate statement title detection into `parse_outline` or the calling pipeline so detected titles are injected into the outline before section resolution

## 5. Refactor section slicing to use page boundaries

- [ ] 5.1 Refactor `extract_section_text(text, outline, entry, page_offsets=None, pdf_page_count=None)` — when `entry` has a `page` and `page_offsets` is available, use page-boundary slicing; otherwise fall back to the current body-text search
- [ ] 5.2 Refactor `extract_statement_text` (and `find_statement_in_text`) to use page boundaries when possible, falling back to current behavior

## 6. Cache page offsets in report_cache

- [ ] 6.1 In `get_or_fetch`, when PDF bytes are available and pymupdf yields a non-empty TOC, compute `page_offsets` and `pymupdf_outline` alongside the text cache
- [ ] 6.2 Store as `.page_offsets.json` and `.outline_pymupdf.json` alongside the existing `.txt`/.outline.json files
- [ ] 6.3 On cache hit, read these files back; skip (graceful fallback) if missing

## 7. Wire through the pipeline

- [ ] 7.1 Update `indicators_client._build_ctx` to pass `page_offsets` and `merged_outline` through the extraction context
- [ ] 7.2 Update `_resolve_section` in `indicators_client` to use the enriched outline and page offsets for section text extraction
- [ ] 7.3 Update `indicators_client._resolve_via_report` to use page-boundary slicing
- [ ] 7.4 Verify `get_financial_statements` and `get_section` also benefit from the enriched outline

## 8. Verify with 平安银行 2025

- [ ] 8.1 Clear the report cache for 000001/2025 and re-extract
- [ ] 8.2 Verify "合并资产负债表" is now in the enriched outline
- [ ] 8.3 Re-run `extract_indicators 000001 --year 2025` and compare found count vs baseline 67/309
- [ ] 8.4 Spot-check specific previously-missing indicators (e.g., 客户存款, 发放贷款及垫款, 不良贷款余额) for correct values
- [ ] 8.5 Verify no regressions on a previously-working report (e.g., 601398 工商银行)
