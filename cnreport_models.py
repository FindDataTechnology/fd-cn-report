"""SQLAlchemy ORM models for fd-cn-report.

Extracted from the shared mcp `models` module so this package is self-contained
and publishable to PyPI without the local mcp-models path dependency.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class ReportTaxonomy(Base):
    """Hierarchical classification of report content sections.

    Stores taxonomy codes like "balance_sheet", "income_statement.revenue"
    with multi-language labels (zh/en/ja/ko).
    """
    __tablename__ = "report_taxonomy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False, index=True)
    parent_code = Column(String(100), nullable=True, index=True)
    level = Column(Integer, nullable=False, default=1)
    label_zh = Column(Text, nullable=False)
    label_en = Column(Text, nullable=False)
    label_ja = Column(Text, nullable=True)
    label_ko = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        """Convert to dict for API responses."""
        return {
            "code": self.code,
            "parent_code": self.parent_code,
            "level": self.level,
            "label_zh": self.label_zh,
            "label_en": self.label_en,
            "label_ja": self.label_ja,
            "label_ko": self.label_ko,
            "description": self.description,
        }


class DocumentTaxonomy(Base):
    """Hierarchical classification of document types.

    Stores document type codes like "cn_annual", "hk_interim"
    with multi-language labels and metadata (country, exchange, report_kind).
    """
    __tablename__ = "document_taxonomy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False, index=True)
    parent_code = Column(String(100), nullable=True, index=True)
    level = Column(Integer, nullable=False, default=1)
    label_zh = Column(Text, nullable=False)
    label_en = Column(Text, nullable=False)
    label_ja = Column(Text, nullable=True)
    label_ko = Column(Text, nullable=True)
    country = Column(String(10), nullable=True, index=True)
    exchange = Column(String(20), nullable=True)
    report_kind = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        """Convert to dict for API responses."""
        return {
            "code": self.code,
            "parent_code": self.parent_code,
            "level": self.level,
            "label_zh": self.label_zh,
            "label_en": self.label_en,
            "label_ja": self.label_ja,
            "label_ko": self.label_ko,
            "country": self.country,
            "exchange": self.exchange,
            "report_kind": self.report_kind,
            "description": self.description,
        }


class ScriptRule(Base):
    """A script (deterministic) indicator rule persisted in SQLite.

    Carries the demand's script-rule shape (``indicator``, ``extract_rule``,
    ``position``, ``document_type``) plus shared metadata. ``extract_rule``
    names a registered extractor in ``script_extractors``.
    """
    __tablename__ = "script_rules"
    __table_args__ = (
        UniqueConstraint("indicator", "document_type", name="uq_script_rule_indicator_doc"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    indicator = Column(String(255), nullable=False, index=True)
    document_type = Column(String(64), nullable=False, index=True)
    extract_rule = Column(String(128), nullable=False)
    position = Column(Text, nullable=True)
    module = Column(String(64), nullable=True, index=True)
    subgroup = Column(String(255), nullable=True)
    source_type = Column(String(32), nullable=True)
    applies_to = Column(JSON, nullable=True)
    unit = Column(String(32), nullable=True)
    period_type = Column(String(32), nullable=True)
    source = Column(JSON, nullable=True)
    aliases = Column(JSON, nullable=True)
    note = Column(Text, nullable=True)

    def to_rule_dict(self) -> dict:
        return {
            "name": self.indicator,
            "indicator": self.indicator,
            "document_type": self.document_type,
            "report_type": self.document_type,
            "extract_rule": self.extract_rule,
            "position": self.position or "",
            "module": self.module,
            "subgroup": self.subgroup,
            "source_type": self.source_type,
            "applies_to": self.applies_to,
            "unit": self.unit,
            "period_type": self.period_type,
            "source": self.source,
            "aliases": self.aliases or [],
            "note": self.note or "",
        }


class LlmRuleV2(Base):
    """New taxonomy-based LLM rule model.

    Uses taxonomy_code (FK to report_taxonomy) and document_type_codes (JSON array
    of FKs to document_taxonomy) instead of free-text module/subgroup/document_type.
    Supports multi-language indicator names.
    """
    __tablename__ = "llm_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    indicator = Column(String(255), nullable=False, index=True)
    taxonomy_code = Column(String(100), nullable=True, index=True)
    document_type_codes = Column(Text, nullable=True)  # JSON array of strings
    indicator_zh = Column(Text, nullable=True)
    indicator_en = Column(Text, nullable=True)
    indicator_ja = Column(Text, nullable=True)
    indicator_ko = Column(Text, nullable=True)
    applies_to = Column(Text, nullable=True)  # JSON
    extractor = Column(String(64), nullable=True)
    source_type = Column(String(32), nullable=True)
    unit = Column(String(32), nullable=True)
    period_type = Column(String(32), nullable=True)
    value_range = Column(Text, nullable=True)  # JSON
    source = Column(Text, nullable=True)  # JSON
    aliases = Column(Text, nullable=True)  # JSON
    note = Column(Text, nullable=True)
    direction = Column(String(32), nullable=True)
    instruction = Column(Text, nullable=True)
    position = Column(Text, nullable=True)

    def to_rule_dict(self) -> dict:
        """Convert to rule dict for pipeline compatibility."""
        import json

        # Parse JSON fields
        doc_type_codes = json.loads(self.document_type_codes) if self.document_type_codes else []
        applies_to = json.loads(self.applies_to) if self.applies_to else None
        value_range = json.loads(self.value_range) if self.value_range else None
        source = json.loads(self.source) if self.source else None
        aliases = json.loads(self.aliases) if self.aliases else []

        # Build indicator_translations
        indicator_translations = {}
        if self.indicator_zh:
            indicator_translations["zh"] = self.indicator_zh
        if self.indicator_en:
            indicator_translations["en"] = self.indicator_en
        if self.indicator_ja:
            indicator_translations["ja"] = self.indicator_ja
        if self.indicator_ko:
            indicator_translations["ko"] = self.indicator_ko

        return {
            "name": self.indicator,
            "indicator": self.indicator,
            "taxonomy_code": self.taxonomy_code,
            "document_type_codes": doc_type_codes,
            "indicator_translations": indicator_translations,
            "applies_to": applies_to,
            "extractor": self.extractor,
            "source_type": self.source_type,
            "unit": self.unit,
            "period_type": self.period_type,
            "value_range": value_range,
            "source": source,
            "aliases": aliases,
            "note": self.note or "",
            "direction": self.direction,
            "instruction": self.instruction or "",
            "position": self.position or "",
        }


class ReportDocument(Base):
    """One fetched annual report. report_id is a stable hash of source+company+year."""
    __tablename__ = "report_documents"
    __table_args__ = (UniqueConstraint("report_id", name="uq_report_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String(128), nullable=False, index=True)
    source = Column(String(2048), nullable=False)
    company = Column(String(255), nullable=True, index=True)
    stock_code = Column(String(32), nullable=True, index=True)
    year = Column(Integer, nullable=True, index=True)
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    raw_path = Column(String(2048), nullable=True)
    parse_status = Column(String(16), default="ok")  # ok | partial | failed

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "source": self.source,
            "company": self.company,
            "stock_code": self.stock_code,
            "year": self.year,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "raw_path": self.raw_path,
            "parse_status": self.parse_status,
        }


class ReportSection(Base):
    """One outline node extracted from a report. Idempotent on report_id+ordinal."""
    __tablename__ = "report_sections"
    __table_args__ = (
        UniqueConstraint("report_id", "ordinal", name="uq_report_section_ordinal"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String(128), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)
    level = Column(Integer, default=1)
    title = Column(String(512), nullable=False)
    char_count = Column(Integer, default=0)
    parse_status = Column(String(16), default="ok")  # ok | missing | failed
    extracted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "ordinal": self.ordinal,
            "level": self.level,
            "title": self.title,
            "char_count": self.char_count,
            "parse_status": self.parse_status,
        }


class EsIndexMeta(Base):
    """Metadata for a cnreport-{year} Elasticsearch index."""
    __tablename__ = "es_index_meta"
    __table_args__ = (UniqueConstraint("index_name", name="uq_es_index_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    index_name = Column(String(128), nullable=False, index=True)
    doc_count = Column(Integer, default=0)
    mapping_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        return {
            "index_name": self.index_name,
            "doc_count": self.doc_count,
            "mapping_hash": self.mapping_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
