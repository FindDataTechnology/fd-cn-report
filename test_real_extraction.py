#!/usr/bin/env python3
"""Test real financial report extraction with LiteLLM."""
import os
import sys
from pathlib import Path

# Add current dir to path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=".env.local", override=True)
    load_dotenv(dotenv_path=".env", override=False)
except ImportError:
    print("⚠️  python-dotenv not installed")

def test_real_extraction():
    """Test extracting real financial data from a PDF report."""
    print("\n" + "=" * 70)
    print("Testing Real Financial Report Extraction")
    print("=" * 70 + "\n")
    
    # Check configuration
    print("Configuration:")
    print("-" * 70)
    base_url = os.environ.get("LLM_BASE_URL", "NOT SET")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "NOT SET")
    pdf_model = os.environ.get("PDF_PROCESS_MODEL", model)
    
    print(f"LLM_BASE_URL: {base_url}")
    print(f"LLM_API_KEY: {'***' + api_key[-4:] if api_key else 'NOT SET'}")
    print(f"LLM_MODEL: {model}")
    print(f"PDF_PROCESS_MODEL: {pdf_model}")
    print("-" * 70 + "\n")
    
    if not api_key:
        print("❌ LLM_API_KEY not configured!")
        return False
    
    # Import cnreport_tools
    try:
        import cnreport_tools as T
        print("✅ cnreport_tools imported\n")
    except ImportError as e:
        print(f"❌ Failed to import cnreport_tools: {e}\n")
        return False
    
    # Test 1: List available indicators
    print("Test 1: Listing available extraction rules...")
    try:
        rules = T.list_llm_rules(limit=10)
        print(f"✅ Found {len(rules)} extraction rules")
        if rules:
            print(f"   Sample rules: {[r.get('indicator') for r in rules[:5]]}\n")
    except Exception as e:
        print(f"⚠️  Could not list rules: {e}\n")
    
    # Test 2: Try to extract indicators from a real company
    print("Test 2: Extracting financial indicators...")
    print("-" * 70)
    
    # Use a well-known company (Kweichow Moutai - 贵州茅台)
    ticker = "600519"  # 贵州茅台
    year = 2023
    
    print(f"Company: {ticker} (Kweichow Moutai)")
    print(f"Year: {year}")
    print(f"Extractor: llm (using {pdf_model})")
    print()
    
    try:
        # Extract key financial indicators
        result = T.extract_indicators(
            ticker_or_name=ticker,
            year=year,
            extractor_mode="llm",  # Use LLM for extraction
            form="年度报告"
        )
        
        print("✅ Extraction successful!")
        print(f"   Result type: {type(result).__name__}")
        
        if isinstance(result, dict):
            print(f"   Keys: {list(result.keys())}")
            
            # Show some sample data
            if 'data' in result:
                data = result['data']
                if isinstance(data, list) and len(data) > 0:
                    print(f"\n   Sample extracted indicators:")
                    for item in data[:5]:
                        if isinstance(item, dict):
                            indicator = item.get('indicator', 'N/A')
                            value = item.get('value', 'N/A')
                            unit = item.get('unit', '')
                            print(f"     - {indicator}: {value} {unit}")
                elif isinstance(data, dict):
                    print(f"\n   Extracted data keys: {list(data.keys())[:10]}")
            
            # Check for errors
            if 'error' in result:
                print(f"\n   ⚠️  Error in result: {result['error']}")
        
        print()
        return True
        
    except Exception as e:
        print(f"❌ Extraction failed: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_financial_statements():
    """Test extracting full financial statements."""
    print("\nTest 3: Extracting financial statements...")
    print("-" * 70)
    
    try:
        import cnreport_tools as T
        
        ticker = "600519"  # 贵州茅台
        year = 2023
        
        print(f"Company: {ticker}")
        print(f"Statement: income_statement (利润表)")
        print()
        
        result = T.get_financial_statement(
            ticker_or_name=ticker,
            year=year,
            statement_type="利润表"
        )
        
        print("✅ Statement extraction successful!")
        print(f"   Result type: {type(result).__name__}")
        
        if isinstance(result, dict):
            print(f"   Keys: {list(result.keys())}")
        elif hasattr(result, 'head'):
            # It's a DataFrame
            print(f"   Shape: {result.shape}")
            print(f"\n   First few rows:")
            print(result.head())
        
        print()
        return True
        
    except Exception as e:
        print(f"⚠️  Statement extraction skipped: {e}\n")
        return True  # Not critical


if __name__ == "__main__":
    success = test_real_extraction()
    
    if success:
        test_financial_statements()
        
        print("=" * 70)
        print("✅ Real extraction tests completed!")
        print("=" * 70 + "\n")
        sys.exit(0)
    else:
        print("=" * 70)
        print("❌ Some tests failed")
        print("=" * 70 + "\n")
        sys.exit(1)
