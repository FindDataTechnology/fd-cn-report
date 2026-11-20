## Context

The current section positioning pipeline:

1. `extract_pdf_text` — extracts text from PDF via pypdf, concatenates page texts with `\n`
2. `parse_outline` — scans text lines with heading regexes (第X章, 一、 etc.) to build a flat outline with ordinal numbers, NO page numbers
3. `resolve_selector` / `resolve_statement` — matches rules' section selectors against the outline via normalized substring
4. `extract_section_text` — finds heading in body text via `_find_section_start`, slices to next outline entry
5. `find_statement_in_text` — body-text fallback with `_STATEMENT_NEXT_BOUNDARY_RE`

Failures for 平安银行 2025:
- "合并资产负债表" doesn't match heading regex → invisible to outline
- "资产负债表" as selector matches "3. 2.2 资产负债表项目分析" (MD&A narrative, not actual statement)
- `_find_section_start` with token `"3."` matches at char 563 (risk warnings), producing ~116K chars of wrong text
- TOC skip only handles dot-leaders (`......12`), misses `标题 7-8`

Design constraints:
- pymupdf (`fitz`) is already installed and added to pyproject.toml
- PDF bytes are already cached alongside text in `.cache/reports/<stem>.pdf`
- Must not break existing reports that work (e.g., those where heading-regex outline works fine)

## Goals / Non-Goals

**Goals:**
- Use `pymupdf.doc.get_toc()` to get real PDF bookmarks with page numbers
- Map page numbers to character offsets in the extracted text for precise section slicing
- Add financial statement titles (合并资产负债表, 合并利润表, 合并现金流量表, 股东权益变动表, 银行资产负债表, 银行利润表, 银行现金流量表) to the outline index via body-text scan, since these are absent from both heading-regex outline and PDF bookmarks
- Fix TOC skip in `_find_section_start` to handle space-separated `"标题 页码"` entries
- Store page-offset index alongside cached text so repeated fetches are fast
- Pass `(text, page_offsets, outline)` through the pipeline so all section slicing functions can use page boundaries

**Non-Goals:**
- Replace pypdf text extraction with pymupdf (pypdf works; only add pymupdf for TOC + page offsets)
- Rewrite the entire section resolution system — keep the `resolve_selector`/`resolve_statement` API surface unchanged
- Fix every individual indicator rule or add new aliases

## Decisions

### Decision 1: Build page-offset index from pypdf (not pymupdf)

pypdf's `page.extract_text()` is already used in `extract_pdf_text`. Re-extracting per-page with pymupdf would give different text (different layout/whitespace), breaking character-offset alignment with the cached text. Instead, add a companion function `get_pypdf_page_offsets()` that runs the same pypdf page loop but tracks cumulative character counts. This guarantees 1:1 alignment with the cached text.

### Decision 2: Hybrid outline — merge PDF bookmarks + heading-regex entries

- PDF bookmarks (from pymupdf) provide page numbers and cover structured sections (chapters, major headings)
- Heading-regex entries (existing `parse_outline`) cover subsections that PDF bookmarks miss
- Merge both sources: bookmarks get page numbers → can be resolved to character offsets; regex-only entries fall back to body-text search (current behavior)
- This ensures non-breaking behavior for reports where the regex outline works fine

### Decision 3: Add statement-title terms directly to the outline

Financial statement table titles (合并资产负债表 etc.) are absent from both PDF bookmarks and heading-regex outline. Add a post-processing step that scans the first ~200K chars of the report body (around the 财务报告 chapter) for these titles, determines their page via the page-offset index, and injects them as virtual outline entries at level 2. This makes `resolve_statement` find them directly without needing the body-text fallback.

### Decision 4: Keep `_find_section_start` as fallback, fix TOC skip

Page-boundary slicing is preferred when available. But for entries without page numbers (regex-only entries), `_find_section_start` remains the fallback. Fix its TOC skip to also handle `"标题 7-8"` (space-separated, no dot-leaders) by checking if the matched text is followed by digits/dash/digits pattern.

### Decision 5: Cache page-offset index in report_cache

Store `page_offsets` as a JSON array `[0, char_pos_p1, char_pos_p2, ...]` alongside the `.txt` and `.outline.json` files. Miss → compute from PDF bytes (which are cached as `.pdf`). Hit → read from disk. This keeps repeated fetches fast.

## Risks / Trade-offs

- **[Risk] Page-offset misalignment**: If pypdf extracts different text on different versions, cached offsets could be wrong. → **Mitigation**: Store `pypdf.__version__` in the offset file; recompute on version mismatch.
- **[Risk] Performance**: Opening PDF with pymupdf + pypdf doubles PDF I/O. → **Mitigation**: Both reads hit cached `.pdf` on disk, not re-download. Total overhead ~100ms per report, acceptable.
- **[Trade-off] Hybrid outline complexity**: Two outline sources merged together is harder to debug. → Keep the merge simple: bookmarks take priority, regex fills gaps, statement titles are injected last.
- **[Risk] Statement title detection**: 合并资产负债表 may appear in table of contents or text, not just as the statement header. → **Mitigation**: Require the match to be on a line by itself (not preceded by 目/录) and verify via page offset that it's within the 财务报告 section.
