#!/usr/bin/env python3
"""Integration tests for taxonomy-based extraction flow."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    """Run integration tests."""
    print("=" * 60)
    print("Running Taxonomy Integration Tests")
    print("=" * 60)

    # Test 1: Load rules and verify new structure
    print("\n[1/4] Testing rule loading...")
    import rules_db
    rules_data = rules_db.load_rules()
    rules = rules_data["rules"]

    assert len(rules) > 0, "Should have rules loaded"
    print(f"  ✓ Loaded {len(rules)} rules")

    sample_rule = rules[0]
    assert "taxonomy_code" in sample_rule or sample_rule.get("document_types"), "Rules should have new structure"
    print(f"  ✓ Rules have new taxonomy structure")

    # Test 2: Filter by taxonomy
    print("\n[2/4] Testing taxonomy filtering...")
    balance_sheet_rules = [r for r in rules if r.get("taxonomy_code") and r["taxonomy_code"].startswith("balance_sheet")]
    print(f"  ✓ Found {len(balance_sheet_rules)} balance_sheet rules")

    cn_annual_rules = [r for r in rules if "cn_annual" in (r.get("document_type_codes") or r.get("document_types", []))]
    print(f"  ✓ Found {len(cn_annual_rules)} cn_annual rules")

    # Test 3: Browse taxonomy
    print("\n[3/4] Testing taxonomy browsing...")
    top_level = rules_db.list_report_taxonomy(parent_code=None)
    print(f"  ✓ Listed {len(top_level)} top-level report taxonomy entries")

    balance_sheet = rules_db.get_report_taxonomy("balance_sheet")
    assert balance_sheet is not None, "Should find balance_sheet"
    assert balance_sheet["label_zh"] == "资产负债表"
    print(f"  ✓ Retrieved balance_sheet with multi-language labels")

    children = rules_db.get_report_taxonomy_children("financial_statements")
    print(f"  ✓ Retrieved {len(children)} children of financial_statements")

    doc_types = rules_db.list_document_taxonomy()
    print(f"  ✓ Listed {len(doc_types)} document types")

    cn_types = rules_db.list_document_taxonomy(country="cn")
    print(f"  ✓ Found {len(cn_types)} CN document types")

    # Test 4: Multi-language support
    print("\n[4/4] Testing multi-language support...")
    balance_sheet_en = balance_sheet["label_en"]
    assert balance_sheet_en == "Balance Sheet"
    print(f"  ✓ English label: {balance_sheet_en}")

    cn_annual = rules_db.get_document_taxonomy("cn_annual")
    assert cn_annual["label_zh"] == "A股年报"
    assert cn_annual["label_en"] == "CN Annual Report"
    print(f"  ✓ Document type labels work correctly")

    print("\n" + "=" * 60)
    print("✅ All integration tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
