"""Database helpers for fd-cn-report.

SQLAlchemy engine + session factory over the shared mcp/daas.db, CRUD for
the three cnreport tables (ReportDocument, ReportSection, EsIndexMeta).
Mirrors composite_database.py.

Usage:
    from cnreport_database import get_db
    db = get_db()
    session = db.get_session()
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from cnreport_models import (
    Base,
    EsIndexMeta,
    LlmRuleV2 as LlmRule,
    ReportDocument,
    ReportSection,
    ScriptRule,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "daas.db"


def make_report_id(
    source: str,
    company: Optional[str],
    year: Optional[int],
    form: Optional[str] = None,
) -> str:
    """Stable id for a report: hash of source+company+year(+form when given).

    ``form`` is included when provided so an annual report and a prospectus for
    the same company + year do not collide in ``report_documents``. Omitting it
    preserves the legacy hash (source+company+year) for existing callers.
    """
    raw = f"{source}|{company or ''}|{year or ''}"
    if form:
        raw += f"|{form}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class CnreportDatabase:
    """Engine + session factory + CRUD for the cnreport tables."""

    def __init__(self, database_url: Optional[str] = None):
        if database_url is None:
            _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            database_url = os.environ.get(
                "DAAS_DATABASE_URL",
                f"sqlite:///{_DEFAULT_DB_PATH}",
            )
        self._database_url = database_url
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self.init_db()
        assert self._engine is not None
        return self._engine

    def get_session(self) -> Session:
        if self._session_factory is None:
            self.init_db()
        assert self._session_factory is not None
        return self._session_factory()

    def init_db(self) -> None:
        self._engine = create_engine(
            self._database_url,
            echo=False,
            connect_args=(
                {"check_same_thread": False}
                if self._database_url.startswith("sqlite")
                else {}
            ),
        )
        self._session_factory = sessionmaker(bind=self._engine)
        Base.metadata.create_all(self._engine)
        logger.info("Cnreport DB initialized: %s", self._database_url)

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None

    # ── ReportDocument ──────────────────────────────────────────

    def upsert_document(
        self,
        report_id: str,
        source: str,
        company: Optional[str],
        stock_code: Optional[str],
        year: Optional[int],
        raw_path: Optional[str] = None,
        parse_status: str = "ok",
    ) -> dict:
        session = self.get_session()
        try:
            row = (
                session.query(ReportDocument)
                .filter(ReportDocument.report_id == report_id)
                .first()
            )
            if row is None:
                row = ReportDocument(
                    report_id=report_id,
                    source=source,
                    company=company,
                    stock_code=stock_code,
                    year=year,
                    raw_path=raw_path,
                    parse_status=parse_status,
                )
                session.add(row)
            else:
                row.source = source
                row.company = company
                row.stock_code = stock_code
                row.year = year
                row.raw_path = raw_path
                row.parse_status = parse_status
            session.commit()
            session.refresh(row)
            return row.to_dict()
        finally:
            session.close()

    def get_document(self, report_id: str) -> Optional[dict]:
        session = self.get_session()
        try:
            row = (
                session.query(ReportDocument)
                .filter(ReportDocument.report_id == report_id)
                .first()
            )
            return row.to_dict() if row else None
        finally:
            session.close()

    # ── ReportSection ───────────────────────────────────────────

    def upsert_section(
        self,
        report_id: str,
        ordinal: int,
        level: int,
        title: str,
        char_count: int,
        parse_status: str = "ok",
    ) -> dict:
        session = self.get_session()
        try:
            row = (
                session.query(ReportSection)
                .filter(
                    ReportSection.report_id == report_id,
                    ReportSection.ordinal == ordinal,
                )
                .first()
            )
            if row is None:
                row = ReportSection(
                    report_id=report_id,
                    ordinal=ordinal,
                    level=level,
                    title=title,
                    char_count=char_count,
                    parse_status=parse_status,
                )
                session.add(row)
            else:
                row.level = level
                row.title = title
                row.char_count = char_count
                row.parse_status = parse_status
            session.commit()
            session.refresh(row)
            return row.to_dict()
        finally:
            session.close()

    def list_sections(self, report_id: str) -> list[dict]:
        session = self.get_session()
        try:
            return [
                s.to_dict()
                for s in session.query(ReportSection)
                .filter(ReportSection.report_id == report_id)
                .order_by(ReportSection.ordinal)
                .all()
            ]
        finally:
            session.close()

    # ── EsIndexMeta ─────────────────────────────────────────────

    def upsert_es_index(
        self, index_name: str, doc_count: int, mapping_hash: Optional[str]
    ) -> dict:
        session = self.get_session()
        try:
            row = (
                session.query(EsIndexMeta)
                .filter(EsIndexMeta.index_name == index_name)
                .first()
            )
            if row is None:
                row = EsIndexMeta(
                    index_name=index_name,
                    doc_count=doc_count,
                    mapping_hash=mapping_hash,
                )
                session.add(row)
            else:
                row.doc_count = doc_count
                row.mapping_hash = mapping_hash
            session.commit()
            session.refresh(row)
            return row.to_dict()
        finally:
            session.close()

    def remove_es_index(self, index_name: str) -> bool:
        session = self.get_session()
        try:
            row = (
                session.query(EsIndexMeta)
                .filter(EsIndexMeta.index_name == index_name)
                .first()
            )
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    def list_es_indices(self) -> list[dict]:
        session = self.get_session()
        try:
            return [
                m.to_dict()
                for m in session.query(EsIndexMeta).order_by(EsIndexMeta.index_name).all()
            ]
        finally:
            session.close()


_cnreport_db: Optional[CnreportDatabase] = None


def get_db(database_url: Optional[str] = None) -> CnreportDatabase:
    global _cnreport_db
    if _cnreport_db is None:
        _cnreport_db = CnreportDatabase(database_url)
        _cnreport_db.init_db()
    return _cnreport_db


def reset_db() -> None:
    global _cnreport_db
    if _cnreport_db is not None:
        _cnreport_db.dispose()
    _cnreport_db = None
