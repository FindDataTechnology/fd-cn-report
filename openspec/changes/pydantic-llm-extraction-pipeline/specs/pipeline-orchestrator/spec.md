# pipeline-orchestrator

## Purpose

Provide `extract_to_dataframe` as the high-level entry point for multi-ticker, multi-year indicator extraction. Auto-downloads reports, resolves sections, dispatches Pydantic-typed LLM extraction across sections concurrently, and returns a pandas DataFrame.

## ADDED Requirements

### Requirement: `extract_to_dataframe` accepts one or many tickers and years

The system SHALL provide `extract_to_dataframe(tickers, years, rules=None, concurrency=4) -> pd.DataFrame` where `tickers` is a single stock code string or a list of strings, and `years` is a single integer year or a list of integers. When `rules` is provided, only those indicator names are extracted; when omitted, all applicable rules are extracted.

#### Scenario: Single ticker, single year returns a DataFrame

- **WHEN** `extract_to_dataframe("000001", 2025)` is called
- **THEN** the result is a `pd.DataFrame` with columns `["ticker", "year", "indicator", "value", "unit", "source_section", "period"]` and one row per successfully-extracted indicator for 平安银行 2025.

#### Scenario: Multiple tickers and years returns combined DataFrame

- **WHEN** `extract_to_dataframe(["000001", "600036"], [2024, 2025])` is called
- **THEN** the result contains rows for all four (ticker, year) combinations.

#### Scenario: Filter by rule names

- **WHEN** `extract_to_dataframe("000001", 2025, rules=["资产总计", "负债合计"])` is called
- **THEN** the DataFrame contains at most two indicator rows.

### Requirement: Reports are downloaded in parallel across ticker-year combinations

For N unique (ticker, year) pairs, the system SHALL download reports concurrently up to `concurrency` workers using `ThreadPoolExecutor`. Each download reuses `report_cache.get_or_fetch`. A progress indicator SHALL print to stderr showing `[1/N] 平安银行 2025` as each download completes.

#### Scenario: N downloads run concurrently

- **WHEN** `extract_to_dataframe` runs with 3 ticker-year pairs and `concurrency=3`
- **THEN** the three PDF downloads overlap in time; total wall-clock time is less than the sum of individual download times (assuming network latency dominance).

### Requirement: LLM extraction runs concurrently across sections and ticker-years

After downloads complete, the system SHALL resolve sections for each ticker-year and dispatch Pydantic-typed LLM extraction. Sections from different ticker-years are independent and SHALL run concurrently up to `concurrency`. Results are collected and flattened into the DataFrame.

#### Scenario: Concurrent extraction across sections

- **WHEN** two ticker-years each have 4 sections (8 total) to extract and `concurrency=4`
- **THEN** up to 4 LLM calls are in-flight at any moment; all 8 complete in roughly `ceil(8/4) * avg_llm_time` wall time.

### Requirement: Return value is a flat pandas DataFrame

The DataFrame SHALL have the following schema:

| Column | Type | Description |
|--------|------|-------------|
| `ticker` | `str` | Stock code |
| `year` | `int` | Fiscal year |
| `indicator` | `str` | Indicator name (from rule set) |
| `value` | `float64` or `NaN` | Extracted value |
| `unit` | `str` | Unit label |
| `source_section` | `str` | Report section title where found |
| `period` | `str` | Report period (e.g., "annual") |
| `missing_reason` | `str` or `""` | Empty string when found; reason string when not found |

#### Scenario: Found indicators have populated value column

- **WHEN** extraction succeeds for an indicator
- **THEN** the row has `value != NaN`, `missing_reason == ""`, and all other columns populated.

#### Scenario: Missing indicators have NaN value and populated reason

- **WHEN** an applicable indicator cannot be resolved
- **THEN** the row has `value == NaN`, `missing_reason` populated with the reason (e.g., "section not found"), and `source_section` populated with the last tried selector.

### Requirement: Failed extraction for one ticker-year does not block others

If a PDF download fails (404, network error) or LLM extraction fails for a specific ticker-year, the system SHALL record the error in a separate `errors` dict keyed by `(ticker, year)` and continue processing remaining ticker-years. The function SHALL NOT raise an exception for per-ticker failures.

#### Scenario: One ticker fails, others succeed

- **WHEN** `extract_to_dataframe` runs with a valid ticker and an invalid ticker (non-existent stock code)
- **THEN** the DataFrame contains rows for the valid ticker, and the invalid ticker's error is recorded in the returned `errors` dict.

### Requirement: Output is optionally saved to CSV/Parquet

The function SHALL accept optional `output_csv` and `output_parquet` path arguments. When provided, the DataFrame SHALL be written to the specified path (CSV with UTF-8 BOM for Excel compatibility; Parquet with Snappy compression).

#### Scenario: CSV output is readable by Excel

- **WHEN** `output_csv="output.csv"` is specified
- **THEN** the file is written with UTF-8 BOM, comma-delimited, and opens correctly in Excel with Chinese characters intact.

### Requirement: Tests use cached PDFs and mocked LLM

The test suite SHALL use pre-cached PDF text from `report_cache` to avoid network calls. LLM calls SHALL be mocked via patching `call_llm_pydantic`. The suite SHALL run with no network and no API key.

#### Scenario: Integration test runs offline

- **WHEN** the test suite executes with `LLM_API_KEY` unset and no network access
- **THEN** all tests pass using cached report text + mocked LLM responses.
