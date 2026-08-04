#!/usr/bin/env python3
"""Phase 2: Migrate rules data from old schema to new taxonomy-based schema.

This script:
1. Reads all rules from llm_rules (old schema with module/subgroup/document_type)
2. Maps old values to new taxonomy_code and document_type_code
3. Writes to llm_rules_v2 (new schema)
4. Generates migration report

Usage:
    cd fd-cn-report
    python scripts/migrate_rules_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

import cnreport_database
from sqlalchemy import text


# Mapping from old module to new taxonomy_code
MODULE_TO_TAXONOMY = {
    # Financial statements (English)
    "balance_sheet": "balance_sheet",
    "income_statement": "income_statement",
    "cashflow": "cashflow_statement",
    "cashflow_statement": "cashflow_statement",
    "financial_ratio": "financial_ratios",
    "financial_ratios": "financial_ratios",
    "market_data": "market_data",
    "comprehensive_income": "comprehensive_income",
    "equity_changes": "equity_changes",

    # Financial statements (Chinese)
    "资产负债表": "balance_sheet",
    "利润表": "income_statement",
    "现金流量表": "cashflow_statement",
    "现金流": "cashflow_statement",
    "权益变动表": "equity_changes",
    "财务指标": "financial_ratios",
    "财务报表": "financial_statements",
    "利润表及现金流量表": "income_statement",
    "主要财务指标": "key_financials",
    "财务摘要": "financial_summary",

    # Report sections (Chinese)
    "report_section": "report_sections",
    "成本分析": "cost_analysis",
    "主营业务分析": "business_analysis",
    "风险因素": "risk_factors",
    "股东信息": "shareholder_info",
    "股东情况": "shareholder_info",
    "研发人员": "rd_personnel",
    "研发投入": "rd_investment",
    "产销量": "production_sales",
    "供应商": "supplier_info",
    "销售客户": "customer_info",
    "报告期内股利分配": "dividend_distribution",
    "利润分配": "profit_distribution",
    "排污信息": "pollution_info",
    "运营指标": "operations_info",
    "公司治理": "corporate_governance",
    "股东及实际控制人": "actual_controller",
    "股本情况": "share_capital",
    "关联交易": "related_party_transactions",
    "环境信息情况": "environmental_info",
    "经营业绩": "operating_performance",
    "股东回报": "shareholder_return",
    "投资": "investment_info",
    "存货": "inventory_info",
    "每股收益": "eps_info",
    "盈利能力分析": "profitability_analysis",
    "营业收入": "revenue_breakdown",
    "营业收入占比": "revenue_ratio",
    "分季度主要财务数据": "quarterly_financials",
    "报告期内发行融资": "financing_history",

    # Prospectus sections
    "募集资金运用": "use_of_proceeds",
    "发行人基本信息": "issuer_info",
    "挂牌期间基本情况": "listing_info",
    "发行概况": "emission_overview",
    "每股指标": "per_share_metrics",

    # English report sections (HK reports)
    "Cash Flow Statement": "cashflow_statement",
    "Share Repurchase": "share_repurchase",
    "Dividends": "dividends",
    "Donations": "donations",
    "Reserves": "reserves",
    "Target": "target_info",
    "Corporate Info": "corporate_governance",
    "revenue_details": "revenue_breakdown",
    "revenue_breakdown": "revenue_breakdown",
    "cost_of_revenues_breakdown": "cost_analysis",

    # Mixed/other
    "非国际财务报告准则调整": "non_ifrs_adjustment",
    "非国际财务报告准则每股收益": "eps_info",
    "非IFRS调整后利润": "non_ifrs_adjustment",
    "股息": "dividends",
    "市场价格": "market_price",
    "环保投资": "environmental_investment",
    "环保费用": "environmental_cost",
    "环保费用及投资合计": "environmental_investment",
    "碳排放": "carbon_emission",
    "行业信息": "industry_info",
    "资产负债表/利润表": "balance_sheet",
    "固定资产折旧": "fixed_asset_depreciation",
    "N/A": None,
}

# Mapping from old document_type to new document_type_code
def map_document_type(old_dt: str) -> list[str]:
    """Map old document_type to new document_type_codes."""
    if not old_dt:
        return []

    # New format: cn/801xxx/listed/annual-report
    if old_dt.startswith("cn/801"):
        if "annual" in old_dt:
            return ["cn_annual"]
        elif "interim" in old_dt:
            return ["cn_interim"]
        elif "quarterly" in old_dt:
            return ["cn_quarterly"]
        return ["cn_annual"]

    # New format: hk/801xxx/listed/annual-report
    if old_dt.startswith("hk/801"):
        if "annual" in old_dt:
            return ["hk_annual"]
        elif "interim" in old_dt:
            return ["hk_interim"]
        elif "quarterly" in old_dt:
            return ["hk_interim"]  # HK doesn't have quarterly
        return ["hk_annual"]

    # Old format mappings
    mapping = {
        "年报/半年报/季报": ["cn_annual", "cn_interim", "cn_quarterly"],
        "年报/半年报": ["cn_annual", "cn_interim"],
        "年报": ["cn_annual"],
        "实时": [],  # Real-time data, no specific document type
        "季报/半年报": ["cn_interim", "cn_quarterly"],
        "annual_report": ["cn_annual"],
        "listed/annual-report": ["cn_annual"],
        "招股说明书": ["cn_prospectus"],
        "港股年度报告": ["hk_annual_report"],
    }

    return mapping.get(old_dt, ["cn_annual"])


def migrate_rules(session):
    """Migrate rules from llm_rules to llm_rules_v2."""
    print("\nMigrating rules...")

    # Read all rules from old table
    rows = session.execute(text("SELECT * FROM llm_rules")).fetchall()
    print(f"  Read {len(rows)} rules from llm_rules")

    # Statistics
    mapped_count = 0
    unmapped_modules = Counter()
    unmapped_doc_types = Counter()

    for row in rows:
        old_module = row.module
        old_subgroup = row.subgroup
        old_doc_types = row.document_types  # This is a JSON array from dedup migration

        # Map module to taxonomy_code
        taxonomy_code = MODULE_TO_TAXONOMY.get(old_module)
        if taxonomy_code is None and old_module:
            unmapped_modules[old_module] += 1
            # Try to use module as-is if it looks like a taxonomy code
            if "." in old_module or old_module in ["financial_statements", "report_sections", "prospectus_sections"]:
                taxonomy_code = old_module

        # Map document_types array to new document_type_codes
        doc_type_codes = []
        if old_doc_types:
            try:
                old_list = json.loads(old_doc_types) if isinstance(old_doc_types, str) else old_doc_types
                for old_dt in old_list:
                    mapped = map_document_type(old_dt)
                    doc_type_codes.extend(mapped)
                doc_type_codes = list(set(doc_type_codes))  # Deduplicate
            except:
                doc_type_codes = ["cn_annual"]  # Fallback

        if not doc_type_codes and old_doc_types:
            unmapped_doc_types[str(old_doc_types)] += 1

        # Prepare new row
        session.execute(text("""
            INSERT INTO llm_rules_v2
            (indicator, taxonomy_code, document_type_codes,
             indicator_zh, indicator_en, indicator_ja, indicator_ko,
             applies_to, extractor, source_type, unit, period_type,
             value_range, source, aliases, note, direction, instruction, position)
            VALUES
            (:indicator, :taxonomy_code, :doc_type_codes,
             :indicator_zh, :indicator_en, :indicator_ja, :indicator_ko,
             :applies_to, :extractor, :source_type, :unit, :period_type,
             :value_range, :source, :aliases, :note, :direction, :instruction, :position)
        """), {
            "indicator": row.indicator,
            "taxonomy_code": taxonomy_code,
            "doc_type_codes": json.dumps(doc_type_codes, ensure_ascii=False),
            "indicator_zh": row.indicator,  # Default to Chinese
            "indicator_en": None,  # Will be filled later
            "indicator_ja": None,
            "indicator_ko": None,
            "applies_to": json.dumps(row.applies_to, ensure_ascii=False) if row.applies_to else None,
            "extractor": row.extractor,
            "source_type": row.source_type,
            "unit": row.unit,
            "period_type": row.period_type,
            "value_range": json.dumps(row.value_range, ensure_ascii=False) if row.value_range else None,
            "source": json.dumps(row.source, ensure_ascii=False) if row.source else None,
            "aliases": json.dumps(row.aliases, ensure_ascii=False) if row.aliases else None,
            "note": row.note,
            "direction": row.direction,
            "instruction": row.instruction,
            "position": row.position,
        })

        if taxonomy_code:
            mapped_count += 1

    session.commit()
    print(f"  Migrated {len(rows)} rules to llm_rules_v2")
    print(f"  Mapped taxonomy_code: {mapped_count}/{len(rows)}")

    # Report unmapped values
    if unmapped_modules:
        print(f"\n  Unmapped modules ({len(unmapped_modules)}):")
        for mod, count in unmapped_modules.most_common(10):
            print(f"    {mod}: {count}")

    if unmapped_doc_types:
        print(f"\n  Unmapped document_types ({len(unmapped_doc_types)}):")
        for dt, count in unmapped_doc_types.most_common(10):
            print(f"    {dt}: {count}")

    return len(rows), mapped_count


def verify_migration(session):
    """Verify migration results."""
    print("\nVerifying migration...")

    # Count rules
    old_count = session.execute(text("SELECT count(*) FROM llm_rules")).fetchone()[0]
    new_count = session.execute(text("SELECT count(*) FROM llm_rules_v2")).fetchone()[0]
    print(f"  Rule count: {old_count} → {new_count}")

    # Check taxonomy coverage
    with_taxonomy = session.execute(text(
        "SELECT count(*) FROM llm_rules_v2 WHERE taxonomy_code IS NOT NULL"
    )).fetchone()[0]
    print(f"  Rules with taxonomy_code: {with_taxonomy}/{new_count}")

    # Check document_type_codes coverage
    with_doc_types = session.execute(text(
        "SELECT count(*) FROM llm_rules_v2 WHERE document_type_codes IS NOT NULL AND document_type_codes != '[]'"
    )).fetchone()[0]
    print(f"  Rules with document_type_codes: {with_doc_types}/{new_count}")

    # Sample some rules
    print("\n  Sample rules:")
    samples = session.execute(text("""
        SELECT indicator, taxonomy_code, document_type_codes
        FROM llm_rules_v2
        WHERE taxonomy_code IS NOT NULL
        LIMIT 5
    """)).fetchall()
    for s in samples:
        print(f"    {s.indicator}: {s.taxonomy_code} → {s.document_type_codes}")

    return old_count == new_count


def main():
    """Run Phase 2: Migrate rules data."""
    print("=" * 60)
    print("Phase 2: Migrate Rules Data")
    print("=" * 60)

    db = cnreport_database.get_db()
    session = db.get_session()

    try:
        total, mapped = migrate_rules(session)
        success = verify_migration(session)

        print("\n" + "=" * 60)
        if success:
            print("Phase 2 Complete!")
        else:
            print("Phase 2 Complete (with warnings)")
        print("=" * 60)

    except Exception as e:
        session.rollback()
        print(f"\n✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
