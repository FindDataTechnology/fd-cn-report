## MODIFIED Requirements

### Requirement: Standalone CSV-driven extraction CLI
The system SHALL provide a standalone script `scripts/extract_indicators_by_position.py` that runs the CSV-driven indicator-extraction pipeline from the command line without the MCP server. It SHALL accept a company (ticker or name) and `--year`, read a position CSV (`--csv`, default `docs/indicators_position.csv`) to determine the indicator set, resolve each name to a rule, partition by `source_type` (skipping `external`) and by `report_type` (skipping form-incompatible), route the rest through the engine, and write results to disk. It SHALL accept a `--form {年度报告|半年度报告|第一季度报告|第三季度报告}` argument (default `年度报告`) selecting the CNINFO periodic form to fetch.

#### Scenario: Single company extraction
- **WHEN** `python scripts/extract_indicators_by_position.py 601398 --year 2023` is run
- **THEN** the script reads the default position CSV, resolves 工商银行, fetches the 2023 annual report once via the cache, applies the applicable rules, classifies `external` indicators into `skipped`, and writes a results file for 601398/2023.

#### Scenario: Batch from a file
- **WHEN** `python scripts/extract_indicators_by_position.py --from-file companies.txt --year 2023` is run with one ticker per line
- **THEN** the script processes each company in turn, writing one results file per company.

#### Scenario: Quarterly form flag
- **WHEN** `python scripts/extract_indicators_by_position.py 600519 --year 2023 --form 第一季度报告` is run
- **THEN** the script fetches the 2023 Q1 report, skips indicators whose `report_type` doesn't include `季报`, and records `form: "第一季度报告"` in the JSON output and a `form` column in the CSV provenance.

### Requirement: JSON and CSV output with skipped rows
The script SHALL write results to an output directory (`--out-dir`, default `./out`) as both `<stock>_<year>[_<form>].json` and `<stock>_<year>[_<form>].csv` (the form suffix disambiguates when multiple forms are processed for the same company/year). The JSON SHALL match the `extract_indicators_by_position` result shape (header including `form` + `indicators` map + `missing` + `unresolved` + `skipped` + `cached` + provenance including `csv_path` and extractor mode). The CSV SHALL be a flat `indicator,value,unit,source_type,extractor,period,note,status` table, one row per attempted indicator — `missing`/`unresolved`/`skipped` rows SHALL appear with empty values, a `note`, and a `status` of `missing`/`unresolved`/`skipped` respectively (form-filtered rows use `status: "skipped"` with `source_type: "form_filter"`).

#### Scenario: Output files written
- **WHEN** the script completes for 601398/2023 with `--out-dir ./out`
- **THEN** `./out/601398_2023.json` and `./out/601398_2023.csv` both exist and contain the same indicator set.

#### Scenario: CSV includes skipped and unresolved rows
- **WHEN** an indicator is `external` (skipped), form-filtered (skipped), or unresolved
- **THEN** the CSV contains a row for it with an empty `value`, a `note` explaining why, and `status` of `skipped` or `unresolved`.
