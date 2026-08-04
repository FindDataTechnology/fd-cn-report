"""Unit tests for dedup-llm-rules-entity-industry migration.

Tests the new document_types JSON array schema and entity-based industry filtering.
"""
import pytest
import rules_db
from indicators_client import applicable_rules, _form_compatible, profile_company


class TestDocumentTypesSchema:
    """Test the new document_types JSON array schema."""

    def test_load_rules_returns_document_types_array(self):
        """Verify rules have document_types as a list."""
        rules = rules_db.load_rules()["rules"]
        assert len(rules) > 0

        # Check first rule has document_types array
        rule = rules[0]
        assert "document_types" in rule
        assert isinstance(rule["document_types"], list)
        assert len(rule["document_types"]) > 0

    def test_backward_compatibility_document_type(self):
        """Verify backward compatibility: document_type field still exists."""
        rules = rules_db.load_rules()["rules"]
        rule = rules[0]

        # Should have both document_types (new) and document_type (old, first element)
        assert "document_types" in rule
        assert "document_type" in rule
        assert rule["document_type"] == rule["document_types"][0]

    def test_rule_count_reduced(self):
        """Verify rule count is significantly reduced after dedup."""
        rules = rules_db.load_rules()["rules"]
        # Before: 26970 rules, After: ~3389 rules (87% reduction)
        assert len(rules) < 5000
        assert len(rules) > 2000


class TestFormCompatibility:
    """Test form compatibility with new schema."""

    def test_annual_report_compatibility(self):
        """Test annual report form compatibility."""
        rules = rules_db.load_rules()["rules"]

        # Find a rule with annual-report in document_types
        annual_rule = None
        for r in rules:
            if any("annual-report" in dt for dt in r.get("document_types", [])):
                annual_rule = r
                break

        assert annual_rule is not None
        assert _form_compatible(annual_rule, "年度报告") is True
        assert _form_compatible(annual_rule, "半年度报告") is False

    def test_interim_report_compatibility(self):
        """Test interim report form compatibility."""
        rules = rules_db.load_rules()["rules"]

        # Find a rule with ONLY interim-report (not annual-report)
        interim_rule = None
        for r in rules:
            doc_types = r.get("document_types", [])
            has_interim = any("interim-report" in dt for dt in doc_types)
            has_annual = any("annual-report" in dt for dt in doc_types)
            if has_interim and not has_annual:
                interim_rule = r
                break

        if interim_rule:
            assert _form_compatible(interim_rule, "半年度报告") is True
            assert _form_compatible(interim_rule, "年度报告") is False

    def test_multiple_document_types(self):
        """Test rule with multiple document_types."""
        rules = rules_db.load_rules()["rules"]

        # Find a rule with multiple document_types
        multi_rule = None
        for r in rules:
            if len(r.get("document_types", [])) > 3:
                multi_rule = r
                break

        if multi_rule:
            # Should be compatible with all forms in its document_types
            doc_types = multi_rule["document_types"]
            if any("annual-report" in dt for dt in doc_types):
                assert _form_compatible(multi_rule, "年度报告") is True
            if any("interim-report" in dt for dt in doc_types):
                assert _form_compatible(multi_rule, "半年度报告") is True


class TestEntityBasedIndustryFiltering:
    """Test entity-based industry filtering."""

    def test_bank_stock_profile(self):
        """Test bank stock industry classification."""
        profile = profile_company("601398", "工商银行")
        assert profile["industry"] == "bank"
        assert profile["sub_type"] == "国有大行"

    def test_applicable_rules_for_bank(self):
        """Test applicable rules for bank stock."""
        profile, rules = applicable_rules("601398", "工商银行")

        assert profile["industry"] == "bank"
        assert len(rules) > 0

        # Should include bank-specific rules
        bank_rules = [r for r in rules if (r.get("applies_to") or {}).get("industry") == "bank"]
        assert len(bank_rules) > 0

    def test_applicable_rules_for_non_bank(self):
        """Test applicable rules for non-bank stock."""
        profile, rules = applicable_rules("000002", "万科A")

        # Should not include bank-specific rules
        bank_rules = [r for r in rules if (r.get("applies_to") or {}).get("industry") == "bank"]
        assert len(bank_rules) == 0


class TestPerformance:
    """Test performance characteristics."""

    def test_rule_loading_performance(self):
        """Test rule loading is fast."""
        import time
        start = time.time()
        rules = rules_db.load_rules()
        elapsed = time.time() - start

        # Should load in under 1 second
        assert elapsed < 1.0
        assert len(rules["rules"]) > 0

    def test_filtering_performance(self):
        """Test applicable_rules filtering is fast."""
        import time
        start = time.time()
        for _ in range(10):
            profile, rules = applicable_rules("601398", "工商银行")
        elapsed = (time.time() - start) / 10

        # Should filter in under 10ms on average
        assert elapsed < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
