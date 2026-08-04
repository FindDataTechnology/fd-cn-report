"""fd-cn-report datasource manifest conforming to fd-open-data-protocol.

This module exposes a DatasourceManifest-compatible CATALOG for Chinese
financial report extraction (CSRC, SSE, SZSE, BSE listed companies).
Loadable via: load_catalog("catalog:CATALOG")
"""
from __future__ import annotations

CATALOG = {
    "version": "1",
    "name": "fd-cn-report",
    "label": "Chinese Financial Report Extractor",
    "source_url": "https://github.com/FindDataTechnology/finddata/tree/main/fd-cn-report",
    "ranking_seed": [0.9, 0.8],
    "scanner_mode": "full",
    "functions": [
        # Outline extraction
        {
            "command": "cninfo_annual_report_outline",
            "category": "outline_extraction",
            "description": "Extract table of contents from CNInfo annual reports",
            "frequency": "on_demand",
            "parameters": [
                {"name": "company", "type": "str", "required": True, "description": "Company name"},
                {"name": "year", "type": "int", "required": True, "description": "Report year"},
                {"name": "stock_code", "type": "str", "required": False, "description": "Stock code"},
            ],
            "columns": [
                {"name": "section_title", "type": "str", "description": "Section title"},
                {"name": "section_level", "type": "int", "description": "Heading level"},
                {"name": "page_number", "type": "int", "description": "Starting page"},
                {"name": "selector", "type": "str", "description": "Selection path"},
            ],
        },
        # Section extraction
        {
            "command": "cninfo_section_extract",
            "category": "section_extraction",
            "description": "Extract full text content from a specific section",
            "frequency": "on_demand",
            "parameters": [
                {"name": "source", "type": "str", "required": True, "description": "Report URL or file path"},
                {"name": "selector", "type": "str", "required": True, "description": "Section selector"},
                {"name": "max_chars", "type": "int", "required": False, "description": "Max characters"},
            ],
            "columns": [
                {"name": "section_title", "type": "str", "description": "Section title"},
                {"name": "content", "type": "str", "description": "Full section text"},
                {"name": "char_count", "type": "int", "description": "Character count"},
            ],
        },
        # LLM extraction
        {
            "command": "llm_indicator_extract",
            "category": "structured_extraction",
            "description": "LLM-powered structured extraction of financial indicators",
            "frequency": "on_demand",
            "parameters": [
                {"name": "indicator", "type": "str", "required": True, "description": "Target indicator code"},
                {"name": "section_text", "type": "str", "required": True, "description": "Section content"},
                {"name": "document_type", "type": "str", "required": False, "description": "Report type"},
            ],
            "columns": [
                {"name": "indicator_code", "type": "str", "description": "Indicator identifier"},
                {"name": "value", "type": "str", "description": "Extracted value"},
                {"name": "unit", "type": "str", "description": "Value unit"},
                {"name": "confidence", "type": "float", "description": "Extraction confidence"},
                {"name": "location", "type": "str", "description": "Text location span"},
            ],
        },
        # Shenwan industry rules
        {
            "command": "shenwan_industry_rules",
            "category": "industry_classification",
            "description": "Shenwan industry classification rules dashboard",
            "frequency": "quarterly",
            "parameters": [],
            "columns": [
                {"name": "industry_code", "type": "str", "description": "Industry code"},
                {"name": "industry_name", "type": "str", "description": "Industry name"},
                {"name": "rule_count", "type": "int", "description": "Number of extraction rules"},
                {"name": "coverage_ratio", "type": "float", "description": "Rule coverage percentage"},
            ],
        },
        # CSRC official statistics
        {
            "command": "csrc_official_stats",
            "category": "official_statistics",
            "description": "CSRC official market statistics data",
            "frequency": "monthly",
            "parameters": [
                {"name": "stat_type", "type": "str", "required": False, "description": "Statistic type"},
                {"name": "year", "type": "int", "required": False, "description": "Year filter"},
            ],
            "columns": [
                {"name": "stat_date", "type": "date", "description": "Statistics date"},
                {"name": "statistic_name", "type": "str", "description": "Metric name"},
                {"name": "value", "type": "float", "description": "Statistical value"},
                {"name": "unit", "type": "str", "description": "Unit of measurement"},
            ],
        },
        # SSE/SZSE/BSE data
        {
            "command": "sse_trading_data",
            "category": "exchange_data",
            "description": "Shanghai Stock Exchange trading data",
            "frequency": "daily",
            "parameters": [],
            "columns": [
                {"name": "trade_date", "type": "date", "description": "Trading date"},
                {"name": "volume", "type": "float", "description": "Trading volume"},
                {"name": "turnover", "type": "float", "description": "Trading turnover"},
                {"name": "avg_price", "type": "float", "description": "Average price"},
            ],
        },
        {
            "command": "szse_trading_data",
            "category": "exchange_data",
            "description": "Shenzhen Stock Exchange trading data",
            "frequency": "daily",
            "parameters": [],
            "columns": [
                {"name": "trade_date", "type": "date", "description": "Trading date"},
                {"name": "volume", "type": "float", "description": "Trading volume"},
                {"name": "turnover", "type": "float", "description": "Trading turnover"},
            ],
        },
        {
            "command": "bse_trading_data",
            "category": "exchange_data",
            "description": "Beijing Stock Exchange trading data",
            "frequency": "daily",
            "parameters": [],
            "columns": [
                {"name": "trade_date", "type": "date", "description": "Trading date"},
                {"name": "volume", "type": "float", "description": "Trading volume"},
                {"name": "turnover", "type": "float", "description": "Trading turnover"},
            ],
        },
        # ESG and sustainability
        {
            "command": "esg_disclosure",
            "category": "esg_data",
            "description": "ESG disclosure data from annual reports",
            "frequency": "yearly",
            "parameters": [
                {"name": "company", "type": "str", "required": True, "description": "Company name"},
                {"name": "year", "type": "int", "required": True, "description": "Report year"},
            ],
            "columns": [
                {"name": "company", "type": "str", "description": "Company name"},
                {"name": "year", "type": "int", "description": "Report year"},
                {"name": "environment_score", "type": "float", "description": "Environmental score"},
                {"name": "social_score", "type": "float", "description": "Social score"},
                {"name": "governance_score", "type": "float", "description": "Governance score"},
                {"name": "total_esg_score", "type": "float", "description": "Total ESG score"},
            ],
        },
    ],
    "concepts": [
        # Financial statement concepts
        {"column": "value", "concept": "financial.revenue", "entity_type": "company", "measure": "operating_revenue", "unit": "currency_cny_thousand", "frequency": "yearly"},
        {"column": "value", "concept": "financial.net_profit", "entity_type": "company", "measure": "net_profit", "unit": "currency_cny_thousand", "frequency": "yearly"},
        {"column": "value", "concept": "financial.total_assets", "entity_type": "company", "measure": "total_assets", "unit": "currency_cny_thousand", "frequency": "yearly"},
        {"column": "value", "concept": "financial.total_liabilities", "entity_type": "company", "measure": "total_liabilities", "unit": "currency_cny_thousand", "frequency": "yearly"},
        # Indicator extraction concepts
        {"column": "indicator_code", "concept": "extraction.indicator", "entity_type": "company", "measure": "indicator_identifier", "unit": "string", "frequency": "variable"},
        {"column": "confidence", "concept": "extraction.confidence", "entity_type": "company", "measure": "extraction_confidence", "unit": "probability", "frequency": "variable"},
        # ESG concepts
        {"column": "environment_score", "concept": "esg.environment", "entity_type": "company", "measure": "environmental_score", "unit": "point_100", "frequency": "yearly"},
        {"column": "social_score", "concept": "esg.social", "entity_type": "company", "measure": "social_score", "unit": "point_100", "frequency": "yearly"},
        {"column": "governance_score", "concept": "esg.governance", "entity_type": "company", "measure": "governance_score", "unit": "point_100", "frequency": "yearly"},
        # Trading concepts
        {"column": "volume", "concept": "trading_volume", "entity_type": "index", "measure": "daily_volume", "unit": "shares_million", "frequency": "daily"},
        {"column": "turnover", "concept": "trading_turnover", "entity_type": "index", "measure": "daily_turnover", "unit": "currency_cny_million", "frequency": "daily"},
        # Taxonomy concepts
        {"column": "taxonomy_code", "concept": "taxonomy.report_section", "entity_type": "industry", "measure": "report_section_classification", "unit": "string", "frequency": "static"},
        {"column": "document_type_codes", "concept": "taxonomy.document_type", "entity_type": "organization", "measure": "document_type_classification", "unit": "array", "frequency": "static"},
        {"column": "indicator_translations", "concept": "taxonomy.indicator_multilang", "entity_type": "company", "measure": "indicator_name_multilang", "unit": "json", "frequency": "static"},
    ],
    "entities": [
        {"entity_type": "company", "coverage": "explicit", "codes": ["600000.SH", "000001.SZ", "601318.SH"]},
        {"entity_type": "index", "coverage": "universe"},
        {"entity_type": "industry", "coverage": "explicit", "codes": ["shenwan_1_01", "shenwan_2_01", "shenwan_3_01"]},
    ],
    "fetch": {"runner": "fd-cn-report"},
}


class FDcnReportProvider:
    """DataProvider class for fd-open-data-protocol compatibility."""

    name = "fd-cn-report"

    def registry(self) -> dict:
        """Return the CATALOG."""
        return CATALOG

    def run(self, command: str, params: dict):
        """Execute a command via the MCP server dispatcher."""
        from cnreport_tools import dispatch as server_dispatch
        return server_dispatch(command, params)
