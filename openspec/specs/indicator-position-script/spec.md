# indicator-position-script Specification

## Purpose
TBD - created by archiving change extract-indicators-by-position. Update Purpose after archive.
## Requirements
### Requirement: Standalone CSV-driven extraction CLI
The system SHALL provide a standalone script `scripts/extract_indicators_by_position.py` that runs the CSV-driven indicator-extraction pipeline from the command line without the MCP server. It SHALL accept a company (ticker or name) and `--year`, read a position CSV (`--csv`, default `docs/indicators_position.csv`) to determine the indicator set, resolve each name to a rule, partition by `source_type` (skipping `external`), route the rest through the engine, and write results to disk.

#### Scenario: Single company extraction
- **WHEN** `python scripts/extract_indicators_by_position.py 601398 --year 2023` is run
- **THEN** the script reads the default position CSV, resolves 工商银行, fetches the 2023 annual report once via the cache, applies the applicable rules, classifies `external` indicators into `skipped`, and writes a results file for 601398/2023.

#### Scenario: Batch from a file
- **WHEN** `python scripts/extract_indicators_by_position.py --from-file companies.txt --year 2023` is run with one ticker per line
- **THEN** the script processes each company in turn, writing one results file per company.

### Requirement: Selectable position CSV
The script SHALL accept a `--csv <path>` argument selecting the position catalog. The default SHALL be the repo's `docs/indicators_position.csv`. The chosen path SHALL be recorded in the output provenance.

#### Scenario: Override the position CSV
- **WHEN** `python scripts/extract_indicators_by_position.py 601398 --year 2023 --csv docs/my_positions.csv` is run
- **THEN** the script reads the indicator set from `docs/my_positions.csv`, extracts that set for 601398, and records `csv_path: docs/my_positions.csv` in the output.

### Requirement: Extractor mode override
The script SHALL accept an `--extractor {auto|llm|python}` argument. `auto` (default) uses each rule's declared extractor. `llm` forces the LLM extractor for all `report`-type rules. `python` forces Python extractors and SHALL skip (listing in `unresolved`) any `report`-type rule whose declared extractor is not a `python:*` name.

#### Scenario: Force python mode
- **WHEN** `--extractor python` is set and a `report`-type rule declares `extractor: "llm"`
- **THEN** the script skips that rule's extraction and lists it in `unresolved` with note `skipped: llm extractor in python mode`, without calling the LLM.

### Requirement: Indicator subset selection
The script SHALL accept an `--indicators <comma-separated>` argument to extract only the named subset (after intersecting with the CSV's indicator column and applicability filtering). When omitted, the script SHALL attempt every indicator named in the CSV.

#### Scenario: Subset extraction
- **WHEN** `--indicators 资产总计,负债合计` is passed
- **THEN** the script extracts only those two indicators (subject to presence in the CSV and applicability) and the output contains only those keys.

### Requirement: JSON and CSV output with skipped rows
The script SHALL write results to an output directory (`--out-dir`, default `./out`) as both `<stock>_<year>.json` and `<stock>_<year>.csv`. The JSON SHALL match the `extract_indicators_by_position` result shape (header + `indicators` map + `missing` + `unresolved` + `skipped` + `cached` + provenance including `csv_path` and extractor mode). The CSV SHALL be a flat `indicator,value,unit,source_type,extractor,period,note,status` table, one row per attempted indicator — `missing`/`unresolved`/`skipped` rows SHALL appear with empty values, a `note`, and a `status` of `missing`/`unresolved`/`skipped` respectively.

#### Scenario: Output files written
- **WHEN** the script completes for 601398/2023 with `--out-dir ./out`
- **THEN** `./out/601398_2023.json` and `./out/601398_2023.csv` both exist and contain the same indicator set.

#### Scenario: CSV includes skipped and unresolved rows
- **WHEN** an indicator is `external` (skipped) or unresolved
- **THEN** the CSV contains a row for it with an empty `value`, a `note` explaining why, and `status` of `skipped` or `unresolved`.

### Requirement: Reuse the engine, no logic duplication
The script SHALL import and call `indicators_client` (rule load, `profile_company`, `applicable_rules`, section resolution, extractor dispatch, computation, bundle cache) and `report_cache` — it SHALL NOT reimplement fetching, parsing, extraction, or caching. The CSV is used only to select the indicator set and classify `external` entries. A change to the engine SHALL automatically affect both the MCP tools and the script.

#### Scenario: Engine reuse
- **WHEN** the script runs
- **THEN** it calls `indicators_client.extract_indicators(...)` (or its building blocks) for the non-external subset and `report_cache.get_or_fetch`, and contains no independent PDF/LLM/caching code.

