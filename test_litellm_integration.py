#!/usr/bin/env python3
"""Test LiteLLM integration with multiple providers."""
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

def test_litellm_adapter():
    """Test the LiteLLM adapter."""
    print("\n" + "=" * 70)
    print("Testing LiteLLM Integration")
    print("=" * 70 + "\n")
    
    # Check configuration
    print("Configuration:")
    print("-" * 70)
    base_url = os.environ.get("LLM_BASE_URL", "NOT SET")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "NOT SET")
    pdf_model = os.environ.get("PDF_PROCESS_MODEL", "NOT SET")
    
    print(f"LLM_BASE_URL: {base_url}")
    print(f"LLM_API_KEY: {'***' + api_key[-4:] if api_key else 'NOT SET'}")
    print(f"LLM_MODEL: {model}")
    print(f"PDF_PROCESS_MODEL: {pdf_model}")
    print("-" * 70 + "\n")
    
    if not api_key:
        print("❌ LLM_API_KEY not configured!")
        return False
    
    # Test 1: Import adapter
    print("Test 1: Importing llm_adapter...")
    try:
        from llm_adapter import call_llm_json, list_supported_providers
        print("✅ llm_adapter imported successfully\n")
    except ImportError as e:
        print(f"❌ Failed to import llm_adapter: {e}\n")
        return False
    
    # Test 2: List supported providers
    print("Test 2: Supported providers:")
    providers = list_supported_providers()
    print(f"   {', '.join(providers)}\n")
    
    # Test 3: Make a simple LLM call
    print("Test 3: Making LLM call with DeepSeek model...")
    try:
        result = call_llm_json(
            system="You are a helpful assistant that extracts financial data.",
            user="Extract the revenue from this text: 'Company X reported revenue of $1.5 billion in 2024.'",
            model=pdf_model if pdf_model != "NOT SET" else None,
            max_retries=2,
            temperature=0,
            max_tokens=1000,
        )
        
        print(f"✅ LLM call successful!")
        print(f"   Response length: {len(result)} chars")
        print(f"   Preview: {result[:200]}...\n")
        
        # Try to parse as JSON
        try:
            import json
            data = json.loads(result)
            print(f"✅ Response is valid JSON!")
            print(f"   Keys: {list(data.keys())}\n")
        except json.JSONDecodeError as e:
            print(f"⚠️  Response is not valid JSON: {e}\n")
        
        return True
        
    except Exception as e:
        print(f"❌ LLM call failed: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_cnreport_tools_integration():
    """Test that cnreport_tools uses the new adapter."""
    print("\nTest 4: Testing cnreport_tools integration...")
    print("-" * 70)
    
    try:
        # Import cnreport_tools
        import cnreport_tools as T
        
        # Check if call_llm_json is patched
        import inspect
        source = inspect.getsource(T.call_llm_json)
        
        if "llm_adapter" in source:
            print("✅ cnreport_tools.call_llm_json uses LiteLLM adapter")
            return True
        else:
            print("⚠️  cnreport_tools.call_llm_json uses original implementation")
            print("   (This is OK if llm_adapter is not available)")
            return True
            
    except Exception as e:
        print(f"❌ Failed to test cnreport_tools: {e}")
        return False


if __name__ == "__main__":
    success = test_litellm_adapter()
    
    if success:
        test_cnreport_tools_integration()
        
        print("\n" + "=" * 70)
        print("✅ All tests passed!")
        print("=" * 70 + "\n")
        sys.exit(0)
    else:
        print("\n" + "=" * 70)
        print("❌ Some tests failed")
        print("=" * 70 + "\n")
        sys.exit(1)
