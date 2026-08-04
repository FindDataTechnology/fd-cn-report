#!/usr/bin/env python3
"""Simple test of LLM call with real financial data."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=".env.local", override=True)
except ImportError:
    pass

def main():
    print("\n" + "=" * 70)
    print("Testing LLM Call with Financial Data")
    print("=" * 70 + "\n")
    
    # Check config
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL", "gpt-4o")
    
    print(f"Model: {model}")
    print(f"Base URL: {base_url}")
    print(f"API Key: {'***' + api_key[-4:] if api_key else 'NOT SET'}\n")
    
    if not api_key:
        print("❌ LLM_API_KEY not set!")
        return False
    
    # Import cnreport_tools
    import cnreport_tools as T
    
    # Test call_llm_json with a simple financial extraction
    system = """You are a financial data extraction assistant. 
Extract the requested financial metric from the text and respond in JSON format.
Example: {"value": 1234.56, "unit": "亿元", "year": 2023}"""
    
    user = """From this text, extract the revenue (营业收入):

"2023 年，贵州茅台实现营业收入 1,505.60 亿元，同比增长 18.04%。"

Return JSON format: {"revenue": <value>, "unit": "<unit>", "year": <year>}"""
    
    print("Calling LLM...")
    print("-" * 70)
    
    try:
        result = T.call_llm_json(system=system, user=user)
        
        print("✅ LLM call successful!")
        print(f"\nResponse:\n{result}\n")
        
        # Try to parse as JSON
        try:
            import json
            data = json.loads(result)
            print("✅ Valid JSON!")
            print(f"   Parsed data: {data}\n")
        except json.JSONDecodeError as e:
            print(f"⚠️  Not valid JSON: {e}\n")
        
        return True
        
    except Exception as e:
        print(f"❌ LLM call failed: {e}\n")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    
    print("=" * 70)
    if success:
        print("✅ Test passed!")
    else:
        print("❌ Test failed")
    print("=" * 70 + "\n")
    
    sys.exit(0 if success else 1)
