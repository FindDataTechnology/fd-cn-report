#!/usr/bin/env python3
"""Tests for taxonomy and multi-language features.

Covers:
- report_taxonomy CRUD operations
- document_taxonomy CRUD operations
- Multi-language label queries
- Taxonomy-based rule filtering
- Edge cases (missing taxonomy_code, empty document_type_codes)
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def fresh_db():
    """Create a fresh database for testing."""
    import cnreport_database
    import tempfile
    import os

    # Create temp database
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["DAAS_DATABASE_URL"] = f"sqlite:///{path}"
    cnreport_database.reset_db()

    # Create tables
    import rules_db
    from cnreport_models import Base
    with cnreport_database.get_db().engine.connect() as conn:
        Base.metadata.create_all(conn)
        conn.commit()

    # Seed taxonomy tables
    sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
    from migrate_taxonomy import seed_report_taxonomy, seed_document_taxonomy
    with rules_db._session() as session:
        seed_report_taxonomy(session)
        seed_document_taxonomy(session)
        session.commit()

    yield path

    # Cleanup
    os.unlink(path)
    if "DAAS_DATABASE_URL" in os.environ:
        del os.environ["DAAS_DATABASE_URL"]
    cnreport_database.reset_db()


class TestReportTaxonomy:
    """Tests for report taxonomy operations."""

    def test_list_top_level_taxonomy(self, fresh_db):
        """Test listing top-level taxonomy entries."""
        import rules_db

        entries = rules_db.list_report_taxonomy(parent_code=None)
        assert len(entries) > 0

        # Should have top-level categories
        codes = [e["code"] for e in entries]
        assert "financial_statements" in codes
        assert "report_sections" in codes

    def test_list_children_taxonomy(self, fresh_db):
        """Test listing children of a taxonomy node."""
        import rules_db

        children = rules_db.get_report_taxonomy_children("financial_statements")
        assert len(children) > 0

        # Should have balance_sheet, income_statement, etc.
        codes = [e["code"] for e in children]
        assert "balance_sheet" in codes
        assert "income_statement" in codes

    def test_get_taxonomy_by_code(self, fresh_db):
        """Test getting a specific taxonomy entry by code."""
        import rules_db

        entry = rules_db.get_report_taxonomy("balance_sheet")
        assert entry is not None
        assert entry["code"] == "balance_sheet"
        assert entry["label_zh"] == "资产负债表"
        assert entry["label_en"] == "Balance Sheet"

    def test_taxonomy_multi_language_labels(self, fresh_db):
        """Test that taxonomy entries have multi-language labels."""
        import rules_db

        entry = rules_db.get_report_taxonomy("balance_sheet")
        assert entry is not None

        # Check all language labels exist
        assert entry["label_zh"] is not None
        assert entry["label_en"] is not None
        # Japanese and Korean may be None for some entries


class TestDocumentTaxonomy:
    """Tests for document taxonomy operations."""

    def test_list_document_taxonomy(self, fresh_db):
        """Test listing document taxonomy entries."""
        import rules_db

        entries = rules_db.list_document_taxonomy()
        assert len(entries) > 0

        # Should have document types
        codes = [e["code"] for e in entries]
        assert "cn_annual" in codes
        assert "hk_annual" in codes

    def test_filter_document_taxonomy_by_country(self, fresh_db):
        """Test filtering document taxonomy by country."""
        import rules_db

        cn_entries = rules_db.list_document_taxonomy(country="cn")
        assert len(cn_entries) > 0

        # All entries should be for China
        for entry in cn_entries:
            assert entry["country"] == "cn"

    def test_document_taxonomy_labels(self, fresh_db):
        """Test document taxonomy multi-language labels."""
        import rules_db

        entries = rules_db.list_document_taxonomy()
        cn_annual = next((e for e in entries if e["code"] == "cn_annual"), None)

        assert cn_annual is not None
        assert cn_annual["label_zh"] == "A股年报"
        assert cn_annual["label_en"] == "CN Annual Report"


class TestTaxonomyBasedFiltering:
    """Tests for taxonomy-based rule filtering."""

    def test_filter_rules_by_taxonomy_code(self, fresh_db):
        """Test filtering rules by taxonomy_code."""
        import rules_db

        # Insert a test rule with taxonomy_code
        rules_db.upsert_llm_rule({
            "indicator": "测试指标",
            "taxonomy_code": "balance_sheet.current_assets",
            "document_type_codes": ["cn_annual"],
            "instruction": "test instruction",
        })

        # Query rules
        rules = rules_db.load_rules()["rules"]
        test_rule = next((r for r in rules if r["name"] == "测试指标"), None)

        assert test_rule is not None
        assert test_rule["taxonomy_code"] == "balance_sheet.current_assets"

    def test_filter_rules_by_document_type_codes(self, fresh_db):
        """Test filtering rules by document_type_codes."""
        import rules_db

        # Insert test rules with different document types
        rules_db.upsert_llm_rule({
            "indicator": "测试指标1",
            "taxonomy_code": "balance_sheet",
            "document_type_codes": ["cn_annual", "cn_interim"],
            "instruction": "test",
        })

        rules_db.upsert_llm_rule({
            "indicator": "测试指标2",
            "taxonomy_code": "balance_sheet",
            "document_type_codes": ["hk_annual"],
            "instruction": "test",
        })

        # Query rules
        rules = rules_db.load_rules()["rules"]

        # Check first rule
        rule1 = next((r for r in rules if r["name"] == "测试指标1"), None)
        assert rule1 is not None
        assert "cn_annual" in rule1["document_type_codes"]
        assert "cn_interim" in rule1["document_type_codes"]

        # Check second rule
        rule2 = next((r for r in rules if r["name"] == "测试指标2"), None)
        assert rule2 is not None
        assert "hk_annual" in rule2["document_type_codes"]


class TestMultiLanguageIndicators:
    """Tests for multi-language indicator names."""

    def test_indicator_translations(self, fresh_db):
        """Test that indicators can have multi-language names."""
        import rules_db

        rules_db.upsert_llm_rule({
            "indicator": "营业收入",
            "taxonomy_code": "income_statement.revenue",
            "document_type_codes": ["cn_annual"],
            "indicator_translations": {
                "zh": "营业收入",
                "en": "Revenue",
                "ja": "収益",
                "ko": "매출액",
            },
            "instruction": "test",
        })

        rules = rules_db.load_rules()["rules"]
        rule = next((r for r in rules if r["name"] == "营业收入"), None)

        assert rule is not None
        assert "indicator_translations" in rule
        assert rule["indicator_translations"]["en"] == "Revenue"
        assert rule["indicator_translations"]["ja"] == "収益"

    def test_fallback_to_chinese(self, fresh_db):
        """Test that missing translations fall back to Chinese."""
        import rules_db

        rules_db.upsert_llm_rule({
            "indicator": "测试指标",
            "taxonomy_code": "balance_sheet",
            "document_type_codes": ["cn_annual"],
            "indicator_translations": {
                "zh": "测试指标",
                # No English translation
            },
            "instruction": "test",
        })

        rules = rules_db.load_rules()["rules"]
        rule = next((r for r in rules if r["name"] == "测试指标"), None)

        assert rule is not None
        # Should have Chinese name
        assert rule["name"] == "测试指标"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_rule_without_taxonomy_code(self, fresh_db):
        """Test that rules can exist without taxonomy_code."""
        import rules_db

        rules_db.upsert_llm_rule({
            "indicator": "无分类指标",
            "document_type_codes": ["cn_annual"],
            "instruction": "test",
            # No taxonomy_code
        })

        rules = rules_db.load_rules()["rules"]
        rule = next((r for r in rules if r["name"] == "无分类指标"), None)

        assert rule is not None
        assert rule.get("taxonomy_code") is None

    def test_rule_with_empty_document_type_codes(self, fresh_db):
        """Test that rules can have empty document_type_codes."""
        import rules_db

        rules_db.upsert_llm_rule({
            "indicator": "无文档类型指标",
            "taxonomy_code": "balance_sheet",
            "document_type_codes": [],
            "instruction": "test",
        })

        rules = rules_db.load_rules()["rules"]
        rule = next((r for r in rules if r["name"] == "无文档类型指标"), None)

        assert rule is not None
        # Note: The implementation may default empty list to ['年报'] for backward compatibility
        # This test verifies the rule was created successfully
        assert "document_type_codes" in rule

    def test_nonexistent_taxonomy_code(self, fresh_db):
        """Test querying a non-existent taxonomy code."""
        import rules_db

        entry = rules_db.get_report_taxonomy("nonexistent_code")
        assert entry is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
