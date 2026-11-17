# indicator-extraction-script

## Purpose

Provide a standalone command-line script (`scripts/extract_indicators.py`) that runs the indicator-extraction pipeline without the MCP server. Accepts a company (ticker or name) and `--year`, resolves the company, fetches the annual-report PDF once via the report cache, applies the rules applicable to that company, runs each rule's extractor, and writes the results to disk as both JSON and CSV.

## Requirements

### Requirement: Standalone extraction CLI
The system SHALL provide a standalone script `scripts/extract_indicators.py` that runs the indicator-extraction pipeline from the command line without the MCP server. It SHALL accept a company (ticker or name) and a `--year`, resolve the company, fetch the annual-report PDF once via the report cache, apply the rules applicable to that company, run each rule's extractor, and write the results to disk.

#### Scenario: Single company extraction
- **WHEN** `python scripts/extract_indicators.py 601398 --year 2023` is run
- **THEN** the script resolves 工商银行, fetches the 2023 annual report, applies the applicable rules, and writes a results file for 601398/2023.

#### Scenario: Batch from a file
- **WHEN** `python scripts/extract_indicators.py --from-file companies.txt --year 2023` is run with one ticker per line
- **THEN** the script processes each company in turn, writing one results file per company.

### Requirement: Selectable rule file for per-company processing
The script SHALL accept a `--rules <path>` argument selecting the rule set file. This lets the user process different companies (or company batches) with different rule files — the "process different company in different process rules" path. The default SHALL be the repo's `indicator_rules.json`.

#### Scenario: Override the rule file
- **WHEN** `python scripts/extract_indicators.py 601398 --year 2023 --rules my_bank_rules.json` is run
- **THEN** the script loads rules from `my_bank_rules.json` instead of the default, applies that file's `applicable_rules` for 601398, and records the rule-file path in the output provenance.

#### Scenario: Different rule files per batch
- **WHEN** the user runs the script twice with different `--rules` files for different company batches
- **THEN** each batch is processed against its own rule set, and the two outputs reflect different applicable rules.

### Requirement: Extractor mode override
The script SHALL accept an `--extractor {auto|llm|python}` argument. `auto` (default) uses each rule's declared extractor. `llm` forces the LLM extractor for all `report`-type rules. `python` forces Python extractors and SHALL skip (listing in `unresolved`) any `report`-type rule whose declared extractor is not a `python:*` name — enabling LLM-free runs where possible.

#### Scenario: Force python mode
- **WHEN** `--extractor python` is set and a `report`-type rule declares `extractor: "llm"`
- **THEN** the script skips that rule's extraction and lists it in `unresolved` with `note: "skipped: llm extractor in python mode"`, without calling the LLM.

#### Scenario: Force llm mode
- **WHEN** `--extractor llm` is set and a `report`-type rule declares `extractor: "python:regex_amount"`
- **THEN** the script runs the LLM extractor for that rule's section instead of the Python extractor.

### Requirement: Indicator subset selection
The script SHALL accept an `--indicators <comma-separated>` argument to extract only the named subset (after applicability filtering). When omitted, the script SHALL attempt every applicable rule.

#### Scenario: Subset extraction
- **WHEN** `--indicators 资本充足率,不良率,资产负债率` is passed
- **THEN** the script extracts only those three indicators (subject to applicability) and the output contains only those keys.

### Requirement: JSON and CSV output
The script SHALL write results to an output directory (`--out-dir`, default `./out`) as both `<stock>_<year>.json` and `<stock>_<year>.csv`. The JSON SHALL match the `extract_indicators` result shape (header + `indicators` map + `missing` + `unresolved` + `cached` + provenance including the rule-file path and extractor mode). The CSV SHALL be a flat `indicator,value,unit,source_type,extractor,period,note` table, one row per attempted indicator (including `missing`/`unresolved` rows with empty values and a `note`).

#### Scenario: Output files written
- **WHEN** the script completes for 601398/2023 with `--out-dir ./out`
- **THEN** `./out/601398_2023.json` and `./out/601398_2023.csv` both exist and contain the same indicator set.

#### Scenario: CSV includes unresolved rows
- **WHEN** an indicator is unresolved (missing input or skipped extractor)
- **THEN** the CSV contains a row for it with an empty `value` and a `note` explaining why.

### Requirement: Reuse the engine, no logic duplication
The script SHALL import and call `indicators_client` (rule load, `profile_company`, `applicable_rules`, section resolution, extractor dispatch, computation, bundle cache) and `report_cache` — it SHALL NOT reimplement fetching, parsing, extraction, or caching. A change to the engine SHALL automatically affect both the MCP tools and the script.

#### Scenario: Engine reuse
- **WHEN** the script runs
- **THEN** it calls `indicators_client.extract_indicators(...)` (or its building blocks) and `report_cache.get_or_fetch`, and contains no independent PDF/LLM/caching code.
