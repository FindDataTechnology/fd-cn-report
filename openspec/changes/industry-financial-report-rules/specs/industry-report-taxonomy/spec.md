## ADDED Requirements

### Requirement: Canonical industry and company type taxonomy
The system SHALL define a canonical taxonomy for classifying a company’s report context, including:

- `industry`: a kebab-case industry identifier (e.g., `bank`, `insurance`, `securities`, `manufacturing`)
- `company_type`: a kebab-case company type identifier (e.g., `listed`, `non-listed`, `financial-holding`) as needed
- `report_kind`: a kebab-case report kind identifier (e.g., `annual-report`, `interim-report`, `quarterly-report`)

#### Scenario: A new taxonomy entry is introduced
- **WHEN** a new industry or company_type is added to the taxonomy
- **THEN** it uses kebab-case identifiers and includes enough metadata to construct one or more supported `document_type` values

### Requirement: Deterministic document_type naming convention
The system SHALL define a deterministic naming convention for `document_type` that incorporates taxonomy so rules do not collide across industries and company types.

The `document_type` SHALL follow the form:

- `cn/<industry>/<company_type>/<report_kind>`

#### Scenario: Document type is computed from taxonomy
- **WHEN** an operator selects an industry, company_type, and report_kind from the taxonomy
- **THEN** the system constructs `document_type` as `cn/<industry>/<company_type>/<report_kind>`

### Requirement: Document type mapping for supported industries
For each supported industry, the system SHALL maintain a mapping from taxonomy selections to one or more `document_type` values that are considered candidates for rule generation and extraction.

#### Scenario: Listing document types for an industry
- **WHEN** an operator requests supported/candidate document types for an industry
- **THEN** the system returns the mapped `document_type` values for that industry (including company_type and report_kind variants)

