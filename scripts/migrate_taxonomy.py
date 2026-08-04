#!/usr/bin/env python3
"""Phase 1: Create taxonomy tables for standardized rule classification.

Creates:
- report_taxonomy: hierarchical classification of report content (zh/en/ja/ko)
- document_taxonomy: hierarchical classification of document types
- llm_rules_v2: new rule table with taxonomy_code + document_type_codes
- taxonomy_mapping: mapping from old module/subgroup/document_type to new codes

Usage:
    cd fd-cn-report
    python scripts/migrate_taxonomy.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cnreport_database
from sqlalchemy import text


def create_tables(session):
    """Create all new tables."""
    print("[1/4] Creating report_taxonomy table...")
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS report_taxonomy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code VARCHAR(100) UNIQUE NOT NULL,
            parent_code VARCHAR(100),
            level INTEGER NOT NULL DEFAULT 1,
            label_zh TEXT NOT NULL,
            label_en TEXT NOT NULL,
            label_ja TEXT,
            label_ko TEXT,
            description TEXT,
            sort_order INTEGER DEFAULT 0
        )
    """))

    print("[2/4] Creating document_taxonomy table...")
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS document_taxonomy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code VARCHAR(100) UNIQUE NOT NULL,
            parent_code VARCHAR(100),
            level INTEGER NOT NULL DEFAULT 1,
            label_zh TEXT NOT NULL,
            label_en TEXT NOT NULL,
            label_ja TEXT,
            label_ko TEXT,
            country VARCHAR(10),
            exchange VARCHAR(20),
            report_kind VARCHAR(50),
            description TEXT,
            sort_order INTEGER DEFAULT 0
        )
    """))

    print("[3/4] Creating llm_rules_v2 table...")
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS llm_rules_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indicator VARCHAR(255) NOT NULL,
            taxonomy_code VARCHAR(100),
            document_type_codes TEXT,
            indicator_zh TEXT,
            indicator_en TEXT,
            indicator_ja TEXT,
            indicator_ko TEXT,
            applies_to TEXT,
            extractor VARCHAR(64),
            source_type VARCHAR(32),
            unit VARCHAR(32),
            period_type VARCHAR(32),
            value_range TEXT,
            source TEXT,
            aliases TEXT,
            note TEXT,
            direction VARCHAR(32),
            instruction TEXT,
            position TEXT
        )
    """))

    print("[4/4] Creating taxonomy_mapping table...")
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS taxonomy_mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            old_module VARCHAR(100),
            old_subgroup VARCHAR(255),
            old_document_type VARCHAR(100),
            new_taxonomy_code VARCHAR(100),
            new_document_type_code VARCHAR(100),
            confidence REAL DEFAULT 1.0,
            note TEXT
        )
    """))

    # Create indexes
    print("Creating indexes...")
    session.execute(text("CREATE INDEX IF NOT EXISTS idx_report_taxonomy_code ON report_taxonomy(code)"))
    session.execute(text("CREATE INDEX IF NOT EXISTS idx_report_taxonomy_parent ON report_taxonomy(parent_code)"))
    session.execute(text("CREATE INDEX IF NOT EXISTS idx_document_taxonomy_code ON document_taxonomy(code)"))
    session.execute(text("CREATE INDEX IF NOT EXISTS idx_document_taxonomy_country ON document_taxonomy(country)"))
    session.execute(text("CREATE INDEX IF NOT EXISTS idx_llm_rules_v2_indicator ON llm_rules_v2(indicator)"))
    session.execute(text("CREATE INDEX IF NOT EXISTS idx_llm_rules_v2_taxonomy ON llm_rules_v2(taxonomy_code)"))
    session.execute(text("CREATE INDEX IF NOT EXISTS idx_taxonomy_mapping_old ON taxonomy_mapping(old_module, old_subgroup, old_document_type)"))


def seed_report_taxonomy(session):
    """Seed report_taxonomy with standard financial report sections."""
    print("\nSeeding report_taxonomy...")

    entries = [
        # Level 1: Top-level categories
        ("financial_statements", None, 1, "财务报表", "Financial Statements", "財務諸表", "재무제표", 1),
        ("report_sections", None, 1, "报告章节", "Report Sections", "報告セクション", "보고서 섹션", 2),
        ("prospectus_sections", None, 1, "招股书章节", "Prospectus Sections", "目論見書セクション", "모집설명서 섹션", 3),

        # Level 2: Financial statements
        ("balance_sheet", "financial_statements", 2, "资产负债表", "Balance Sheet", "貸借対照表", "대차대조표", 10),
        ("income_statement", "financial_statements", 2, "利润表", "Income Statement", "損益計算書", "손익계산서", 11),
        ("cashflow_statement", "financial_statements", 2, "现金流量表", "Cash Flow Statement", "キャッシュフロー計算書", "현금흐름표", 12),
        ("equity_changes", "financial_statements", 2, "所有者权益变动表", "Statement of Changes in Equity", "資本変動表", "자본변동표", 13),
        ("comprehensive_income", "financial_statements", 2, "综合收益表", "Statement of Comprehensive Income", "包括利益計算書", "포괄이익표", 14),
        ("financial_notes", "financial_statements", 2, "财务报表附注", "Notes to Financial Statements", "財務諸表注記", "재무제표 주석", 15),
        ("financial_ratios", "financial_statements", 2, "财务比率", "Financial Ratios", "財務比率", "재무비율", 16),
        ("market_data", "financial_statements", 2, "市场数据", "Market Data", "市場データ", "시장 데이터", 17),

        # Level 3: Balance sheet sub-items
        ("balance_sheet.current_assets", "balance_sheet", 3, "流动资产", "Current Assets", "流動資産", "유동자산", 100),
        ("balance_sheet.non_current_assets", "balance_sheet", 3, "非流动资产", "Non-current Assets", "固定資産", "비유동자산", 101),
        ("balance_sheet.current_liabilities", "balance_sheet", 3, "流动负债", "Current Liabilities", "流動負債", "유동부채", 102),
        ("balance_sheet.non_current_liabilities", "balance_sheet", 3, "非流动负债", "Non-current Liabilities", "固定負債", "비유동부채", 103),
        ("balance_sheet.equity", "balance_sheet", 3, "所有者权益", "Owners' Equity", "株主資本", "자본", 104),

        # Level 3: Income statement sub-items
        ("income_statement.revenue", "income_statement", 3, "营业收入", "Revenue", "収益", "매출액", 110),
        ("income_statement.operating_costs", "income_statement", 3, "营业成本", "Operating Costs", "営業費用", "매출원가", 111),
        ("income_statement.operating_profit", "income_statement", 3, "营业利润", "Operating Profit", "営業利益", "영업이익", 112),
        ("income_statement.total_profit", "income_statement", 3, "利润总额", "Total Profit", "利益総額", "총이익", 113),
        ("income_statement.net_profit", "income_statement", 3, "净利润", "Net Profit", "純利益", "순이익", 114),
        ("income_statement.period_expenses", "income_statement", 3, "期间费用", "Period Expenses", "期間費用", "기간비용", 115),
        ("income_statement.non_recurring", "income_statement", 3, "非经常性损益", "Non-recurring Gains/Losses", "非経常的損益", "비경상적 손익", 116),

        # Level 3: Cashflow sub-items
        ("cashflow_statement.operating_activities", "cashflow_statement", 3, "经营活动", "Operating Activities", "営業活動", "영업활동", 120),
        ("cashflow_statement.investing_activities", "cashflow_statement", 3, "投资活动", "Investing Activities", "投資活動", "투자활동", 121),
        ("cashflow_statement.financing_activities", "cashflow_statement", 3, "筹资活动", "Financing Activities", "財務活動", "재무활동", 122),

        # Level 2: Report sections
        ("risk_factors", "report_sections", 2, "风险因素", "Risk Factors", "リスク要因", "위험요인", 200),
        ("corporate_governance", "report_sections", 2, "公司治理", "Corporate Governance", "企業統治", "지배구조", 201),
        ("shareholder_info", "report_sections", 2, "股东信息", "Shareholder Info", "株主情報", "주주 정보", 202),
        ("employee_info", "report_sections", 2, "员工情况", "Employee Info", "従業員情報", "직원 정보", 203),
        ("related_party_transactions", "report_sections", 2, "关联交易", "Related Party Transactions", "関連取引", "관계거래", 204),
        ("cost_analysis", "report_sections", 2, "成本分析", "Cost Analysis", "コスト分析", "비용 분석", 205),
        ("business_analysis", "report_sections", 2, "主营业务分析", "Business Analysis", "事業分析", "사업 분석", 206),
        ("rd_investment", "report_sections", 2, "研发投入", "R&D Investment", "研究開発投資", "연구개발 투자", 207),
        ("rd_personnel", "report_sections", 2, "研发人员", "R&D Personnel", "研究開発要員", "연구개발 인력", 208),
        ("production_sales", "report_sections", 2, "产销量", "Production & Sales", "生産販売", "생산 판매", 209),
        ("supplier_info", "report_sections", 2, "供应商", "Supplier Info", "サプライヤー情報", "공급자 정보", 210),
        ("customer_info", "report_sections", 2, "销售客户", "Customer Info", "顧客情報", "고객 정보", 211),
        ("dividend_distribution", "report_sections", 2, "股利分配", "Dividend Distribution", "配当分配", "배당 분배", 212),
        ("environmental_info", "report_sections", 2, "环境信息", "Environmental Info", "環境情報", "환경 정보", 213),
        ("financial_summary", "report_sections", 2, "财务摘要", "Financial Summary", "財務要旨", "재무 요약", 214),
        ("key_financials", "report_sections", 2, "主要财务指标", "Key Financials", "主要財務指標", "주요 재무지표", 215),
        ("operating_performance", "report_sections", 2, "经营业绩", "Operating Performance", "経営業績", "경영 실적", 216),
        ("shareholder_return", "report_sections", 2, "股东回报", "Shareholder Return", "株主還元", "주주 환원", 217),
        ("investment_info", "report_sections", 2, "投资", "Investment", "投資", "투자", 218),
        ("inventory_info", "report_sections", 2, "存货", "Inventory", "在庫", "재고", 219),
        ("eps_info", "report_sections", 2, "每股收益", "EPS", "一株当たり利益", "주당이익", 220),
        ("profitability_analysis", "report_sections", 2, "盈利能力分析", "Profitability Analysis", "収益性分析", "수익성 분석", 221),
        ("revenue_breakdown", "report_sections", 2, "营业收入构成", "Revenue Breakdown", "収益構成", "매출 구성", 222),

        # Level 2: Prospectus sections
        ("use_of_proceeds", "prospectus_sections", 2, "募集资金运用", "Use of Proceeds", "資金使途", "자금 용도", 300),
        ("issuer_info", "prospectus_sections", 2, "发行人基本信息", "Issuer Info", "発行情報", "발행 정보", 301),
        ("share_capital", "prospectus_sections", 2, "股本情况", "Share Capital", "株式状況", "자본금", 302),
        ("listing_info", "prospectus_sections", 2, "挂牌期间基本情况", "Listing Info", "上場状況", "상장 현황", 303),
        ("profit_distribution", "prospectus_sections", 2, "利润分配", "Profit Distribution", "利益配分", "이익 배분", 304),
        ("actual_controller", "prospectus_sections", 2, "股东及实际控制人", "Controlling Shareholder", "支配株主", "지배주주", 305),
        ("emission_overview", "prospectus_sections", 2, "发行概况", "Emission Overview", "発行概要", "발행 개요", 306),
        ("pollution_info", "prospectus_sections", 2, "排污信息", "Pollution Info", "排出情報", "배출 정보", 307),
        ("operations_info", "prospectus_sections", 2, "运营指标", "Operations Info", "運営指標", "운영 지표", 308),
        ("product_info", "prospectus_sections", 2, "产品信息", "Product Info", "製品情報", "제품 정보", 309),
        ("industry_info", "prospectus_sections", 2, "行业信息", "Industry Info", "業界情報", "업계 정보", 310),
        ("per_share_metrics", "prospectus_sections", 2, "每股指标", "Per-share Metrics", "株式指標", "주당 지표", 311),
        ("quarterly_financials", "prospectus_sections", 2, "分季度主要财务数据", "Quarterly Financials", "四半期財務データ", "분기 재무", 312),
        ("financing_history", "prospectus_sections", 2, "报告期内发行融资", "Financing History", "資金調達履歴", "자금 조달 이력", 313),
        ("revenue_ratio", "prospectus_sections", 2, "营业收入占比", "Revenue Ratio", "収益比率", "매출 비중", 314),
        ("fixed_asset_depreciation", "prospectus_sections", 2, "固定资产折旧", "Fixed Asset Depreciation", "固定資産減価償却", "고정자산 감가상각", 315),
        ("market_price", "prospectus_sections", 2, "市场价格", "Market Price", "市場価格", "시장 가격", 316),
        ("environmental_investment", "prospectus_sections", 2, "环保投资", "Environmental Investment", "環境投資", "환경 투자", 317),
        ("environmental_cost", "prospectus_sections", 2, "环保费用", "Environmental Cost", "環境費用", "환경 비용", 318),
        ("carbon_emission", "prospectus_sections", 2, "碳排放", "Carbon Emission", "炭素排出", "탄소 배출", 319),
        ("share_repurchase", "prospectus_sections", 2, "股份回购", "Share Repurchase", "自社株買い", "자사주 매입", 320),
        ("non_ifrs_adjustment", "prospectus_sections", 2, "非IFRS调整", "Non-IFRS Adjustment", "非IFRS調整", "비IFRS 조정", 321),
        ("dividends", "prospectus_sections", 2, "股息", "Dividends", "配当", "배당", 322),
        ("reserves", "prospectus_sections", 2, "储备", "Reserves", "準備金", "준비금", 323),
        ("donations", "prospectus_sections", 2, "捐赠", "Donations", "寄付", "기부", 324),
        ("target_info", "prospectus_sections", 2, "目标", "Target", "目標", "목표", 325),
    ]

    for code, parent, level, zh, en, ja, ko, order in entries:
        session.execute(text("""
            INSERT OR IGNORE INTO report_taxonomy
            (code, parent_code, level, label_zh, label_en, label_ja, label_ko, sort_order)
            VALUES (:code, :parent, :level, :zh, :en, :ja, :ko, :order)
        """), {"code": code, "parent": parent, "level": level, "zh": zh, "en": en, "ja": ja, "ko": ko, "order": order})

    print(f"  Inserted {len(entries)} report_taxonomy entries")


def seed_document_taxonomy(session):
    """Seed document_taxonomy with standard document types."""
    print("\nSeeding document_taxonomy...")

    entries = [
        # Level 1: Market categories
        ("cn_periodic", None, 1, "A股定期报告", "CN Periodic Reports", "CN定期報告", "CN 정기보고서", "cn", None, None, 1),
        ("hk_periodic", None, 1, "港股定期报告", "HK Periodic Reports", "HK定期報告", "HK 정기보고서", "hk", None, None, 2),
        ("prospectus", None, 1, "招股说明书", "Prospectus", "目論見書", "모집설명서", None, None, None, 3),
        ("hk_report", None, 1, "港股报告", "HK Reports", "HK報告書", "HK 보고서", "hk", None, None, 4),
        ("realtime", None, 1, "实时数据", "Real-time Data", "リアルタイムデータ", "실시간 데이터", None, None, None, 5),

        # Level 2: CN periodic
        ("cn_annual", "cn_periodic", 2, "A股年报", "CN Annual Report", "CN年次報告書", "CN 연차보고서", "cn", "sse/szse", "annual", 10),
        ("cn_interim", "cn_periodic", 2, "A股半年报", "CN Interim Report", "CN中間報告書", "CN 중간보고서", "cn", "sse/szse", "interim", 11),
        ("cn_quarterly", "cn_periodic", 2, "A股季报", "CN Quarterly Report", "CN四半期報告書", "CN 분기보고서", "cn", "sse/szse", "quarterly", 12),

        # Level 2: HK periodic
        ("hk_annual", "hk_periodic", 2, "港股年报", "HK Annual Report", "HK年次報告書", "HK 연차보고서", "hk", "hkex", "annual", 20),
        ("hk_interim", "hk_periodic", 2, "港股半年报", "HK Interim Report", "HK中間報告書", "HK 중간보고서", "hk", "hkex", "interim", 21),

        # Level 2: Prospectus
        ("cn_prospectus", "prospectus", 2, "A股招股说明书", "CN Prospectus", "CN目論見書", "CN 모집설명서", "cn", "sse/szse", "prospectus", 30),
        ("hk_prospectus", "prospectus", 2, "港股招股说明书", "HK Prospectus", "HK目論見書", "HK 모집설명서", "hk", "hkex", "prospectus", 31),

        # Level 2: HK reports (legacy)
        ("hk_annual_report", "hk_report", 2, "港股年度报告", "HK Annual Report", "HK年次報告", "HK 연차보고", "hk", "hkex", "annual", 40),
    ]

    for code, parent, level, zh, en, ja, ko, country, exchange, kind, order in entries:
        session.execute(text("""
            INSERT OR IGNORE INTO document_taxonomy
            (code, parent_code, level, label_zh, label_en, label_ja, label_ko,
             country, exchange, report_kind, sort_order)
            VALUES (:code, :parent, :level, :zh, :en, :ja, :ko, :country, :exchange, :kind, :order)
        """), {
            "code": code, "parent": parent, "level": level,
            "zh": zh, "en": en, "ja": ja, "ko": ko,
            "country": country, "exchange": exchange, "kind": kind, "order": order
        })

    print(f"  Inserted {len(entries)} document_taxonomy entries")


def main():
    """Run Phase 1: Create and seed taxonomy tables."""
    print("=" * 60)
    print("Phase 1: Create Taxonomy Tables")
    print("=" * 60)

    db = cnreport_database.get_db()
    session = db.get_session()

    try:
        create_tables(session)
        session.commit()
        print("\n✓ Tables created")

        seed_report_taxonomy(session)
        session.commit()
        print("✓ report_taxonomy seeded")

        seed_document_taxonomy(session)
        session.commit()
        print("✓ document_taxonomy seeded")

        # Verify
        rt_count = session.execute(text("SELECT count(*) FROM report_taxonomy")).fetchone()[0]
        dt_count = session.execute(text("SELECT count(*) FROM document_taxonomy")).fetchone()[0]
        print(f"\nVerification:")
        print(f"  report_taxonomy: {rt_count} entries")
        print(f"  document_taxonomy: {dt_count} entries")

    except Exception as e:
        session.rollback()
        print(f"\n✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        session.close()

    print("\n" + "=" * 60)
    print("Phase 1 Complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
