"""Pydantic models for rules written to the rules database.

The generator skills validate their LLM output against these before persisting,
and the write API (``rules_db.upsert_llm_rule`` / ``upsert_script_rule``)
validates again on insert. The demand's required fields are:

- LLM rule:    ``indicator``, ``instruction``, ``position``, ``document_type``
- script rule: ``indicator``, ``extract_rule``,  ``position``, ``document_type``

Shared metadata (``module``, ``applies_to``, ``unit``, ...) is optional so a
skill can generate a minimal rule and the migration can carry the full set.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LlmRuleModel(BaseModel):
    """Validated LLM rule for persistence to ``llm_rules_v2``."""

    model_config = ConfigDict(extra="allow")

    indicator: str = Field(..., min_length=1, description="indicator name (Chinese)")
    instruction: str = Field(default="", description="LLM extraction instruction")
    position: str = Field(default="", description="section position / selectors")

    # New taxonomy-based fields
    taxonomy_code: Optional[str] = Field(None, description="taxonomy code, e.g. balance_sheet.current_assets")
    document_type_codes: list[str] = Field(default_factory=list, description="list of document type codes, e.g. ['cn_annual']")
    indicator_translations: Optional[dict[str, str]] = Field(None, description="multi-language indicator names")

    # Legacy field for backward compatibility
    document_type: Optional[str] = Field(None, min_length=1, description="report type, e.g. 年报 (legacy)")

    module: Optional[str] = None
    subgroup: Optional[str] = None
    source_type: Optional[str] = None
    extractor: Optional[str] = None
    applies_to: Optional[dict[str, Any]] = None
    unit: Optional[str] = None
    period_type: Optional[str] = None
    value_range: Optional[dict[str, Any]] = None
    source: Optional[dict[str, Any]] = None
    aliases: list[str] = Field(default_factory=list)
    note: Optional[str] = None
    direction: Optional[str] = None

    @field_validator("indicator")
    @classmethod
    def _non_empty_indicator(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be non-empty")
        return v.strip()

    @field_validator("document_type")
    @classmethod
    def _non_empty_document_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (not v or not v.strip()):
            raise ValueError("must be non-empty")
        return v.strip() if v else v


class ScriptRuleModel(BaseModel):
    """Validated script rule for persistence to ``script_rules``."""

    model_config = ConfigDict(extra="allow")

    indicator: str = Field(..., min_length=1, description="indicator name (Chinese)")
    extract_rule: str = Field(..., min_length=1, description="registered extractor name")
    position: str = Field(default="", description="section position / selectors")
    document_type: str = Field(..., min_length=1, description="report type, e.g. 年报")

    module: Optional[str] = None
    subgroup: Optional[str] = None
    source_type: Optional[str] = None
    applies_to: Optional[dict[str, Any]] = None
    unit: Optional[str] = None
    period_type: Optional[str] = None
    source: Optional[dict[str, Any]] = None
    aliases: list[str] = Field(default_factory=list)
    note: Optional[str] = None

    @field_validator("indicator", "document_type", "extract_rule")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be non-empty")
        return v.strip()
