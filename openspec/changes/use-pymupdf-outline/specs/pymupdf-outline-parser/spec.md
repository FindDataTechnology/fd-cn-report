## ADDED Requirements

### Requirement: Parse PDF bookmarks with page numbers

The system SHALL use pymupdf (`fitz.doc.get_toc()`) to read the PDF's internal bookmark table of contents, producing a tree of `(level, title, page_number)` entries. These SHALL be merged into the text-based outline parsed by `parse_outline`, with PDF bookmarks taking priority. Each bookmark entry SHALL carry its page number for later resolution to character offsets.

#### Scenario: PDF bookmarks are available
- **WHEN** a PDF is fetched and cached
- **THEN** the system reads its bookmarks via pymupdf and includes them in the outline, tagged with `{level, title, page, source: "pymupdf"}`

#### Scenario: PDF has no bookmarks
- **WHEN** a PDF has no internal bookmarks (empty `get_toc()`)
- **THEN** the system falls back entirely to the heading-regex `parse_outline` with no change in behavior

### Requirement: Map page numbers to text character offsets

The system SHALL build a page-to-character-offset index from the pypdf-extracted text, so that any page number from a bookmark can be converted to a `(start_char, end_char)` slice into the full text. The index SHALL be computed alongside text extraction and cached as a JSON file alongside the `.txt` and `.outline.json`.

#### Scenario: Page offset computation
- **WHEN** the PDF is processed
- **THEN** the system extracts text per-page via pypdf (same loop as `extract_pdf_text`), records the cumulative character count per page, and stores the result as `[0, p1_offset, p2_offset, ..., total_chars]`

#### Scenario: Cache hit for page offsets
- **WHEN** a report is fetched from the cache and a `.page_offsets.json` file exists with a matching pypdf version
- **THEN** the system reads the cached offsets instead of recomputing

### Requirement: Section slicing via page boundaries

When an outline entry has a page number, `extract_section_text` SHALL use page boundaries to determine the section start and end instead of `_find_section_start` body-text search. The end boundary SHALL be either the next outline entry's page or the end of the page range.

#### Scenario: Page-boundary slicing
- **WHEN** an outline entry has `page: 107` and the next sibling has `page: 110`
- **THEN** the section text is sliced from page 107's offset to page 110's offset, without any body-text search

#### Scenario: Fallback to text search
- **WHEN** an outline entry has no page number (heading-regex-only entry)
- **THEN** the existing `_find_section_start` fallback is used
