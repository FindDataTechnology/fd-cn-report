# indicator-position-extract (delta)

## ADDED Requirements

### Requirement: Position-extraction result includes section evidence when available
When extracting `report`-type indicators by position, the system SHALL attach section evidence to each extracted indicator when the information is available from the report cache or outline resolver. Evidence SHALL include the matched section title and MAY include page range or a short heading snippet.

#### Scenario: Evidence includes matched section title
- **WHEN** an indicator is extracted from a resolved section
- **THEN** its provenance includes the matched section title that was used to source the section text.

### Requirement: Missing-section indicators include attempted candidates
When a `report`-type indicator is missing because no selector matched any report section, the system SHALL record the attempted section candidates (after section-map expansion) in the `missing` list entry to support rule debugging.

#### Scenario: Missing records attempted candidates
- **WHEN** a report indicator misses section resolution
- **THEN** the `missing` entry includes the list of attempted section titles.

