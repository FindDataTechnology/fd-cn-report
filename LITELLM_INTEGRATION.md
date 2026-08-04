# LiteLLM Integration Guide

fd-cn-report now supports multiple LLM providers via LiteLLM, enabling flexible model selection for different tasks.

## ✅ What's New

### Multi-Provider Support

Instead of being locked to a single API, you can now use:
- **OpenAI** (GPT-4o, GPT-3.5)
- **Anthropic** (Claude 3.5, Claude 3)
- **DeepSeek** (DeepSeek Chat, DeepSeek Coder)
- **Azure OpenAI**
- **Local models** (Ollama, vLLM)
- **Any OpenAI-compatible API** (like linjie.love)

### Configuration

All configuration is done via environment variables in `.env.local`:

```bash
# Base URL for your LLM provider
LLM_BASE_URL=https://www.linjie.love/v1

# API Key
LLM_API_KEY=sk-your-api-key-here

# Model selection (LiteLLM format: provider/model-name)
LLM_MODEL=openai/deepseek-v4-flash

# PDF-specific model (optional, falls back to LLM_MODEL)
PDF_PROCESS_MODEL=openai/deepseek-v4-flash
```

### Model Name Format

LiteLLM uses a `provider/model-name` format:

| Provider | Format | Example |
|----------|--------|---------|
| OpenAI | `openai/` | `openai/gpt-4o` |
| Anthropic | `anthropic/` | `anthropic/claude-3-5-sonnet-20241022` |
| DeepSeek | `deepseek/` | `deepseek/deepseek-chat` |
| Azure | `azure/` | `azure/gpt-4o` |
| Ollama | `ollama/` | `ollama/llama3.1` |
| OpenAI-compatible | `openai/` | `openai/deepseek-v4-flash` (with custom base_url) |

## 🚀 Quick Start

### 1. Configure Your Provider

Edit `.env.local`:

```bash
# Example: Using linjie.love (OpenAI-compatible)
LLM_BASE_URL=https://www.linjie.love/v1
LLM_API_KEY=sk-EjZ35p9zLeE9_7Bz7oaw-x1ZFv_opHQHAQGAwgU1izg
LLM_MODEL=openai/deepseek-v4-flash
PDF_PROCESS_MODEL=openai/deepseek-v4-flash
```

### 2. Test the Integration

```bash
cd /Users/chengsishi/finddata/fd-cn-report
uv run python test_litellm_integration.py
```

Expected output:
```
✅ LLM call successful!
   Response length: 12 chars
✅ cnreport_tools.call_llm_json uses LiteLLM adapter
✅ All tests passed!
```

### 3. Use in Production

The integration is transparent - just use `cnreport_tools` as before:

```python
import cnreport_tools as T

# This now uses LiteLLM under the hood
result = T.extract_indicators(
    ticker_or_name="000000",
    year=2024,
    extractor="llm"
)
```

## 📊 Supported Providers

### OpenAI

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-openai-key
LLM_MODEL=openai/gpt-4o
```

### Anthropic Claude

```bash
LLM_BASE_URL=https://api.anthropic.com
LLM_API_KEY=sk-ant-your-key
LLM_MODEL=anthropic/claude-3-5-sonnet-20241022
```

### DeepSeek

```bash
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-your-deepseek-key
LLM_MODEL=deepseek/deepseek-chat
```

### Azure OpenAI

```bash
LLM_BASE_URL=https://YOUR_RESOURCE.openai.azure.com
LLM_API_KEY=your-azure-key
LLM_MODEL=azure/gpt-4o
```

### Local Ollama

```bash
LLM_BASE_URL=http://localhost:11434
LLM_API_KEY=ollama  # any value works
LLM_MODEL=ollama/llama3.1
```

### Custom OpenAI-Compatible API

```bash
LLM_BASE_URL=https://your-custom-api.com/v1
LLM_API_KEY=your-key
LLM_MODEL=openai/your-model-name  # use "openai/" prefix
```

## 🔧 Advanced Configuration

### Different Models for Different Tasks

```bash
# General tasks (high quality)
LLM_MODEL=openai/gpt-4o

# PDF extraction (fast & cheap)
PDF_PROCESS_MODEL=openai/deepseek-v4-flash
```

### Fallback Behavior

If LiteLLM is not available, the system automatically falls back to direct HTTP calls:

```python
# In llm_adapter.py
try:
    from litellm import completion
    # Use LiteLLM
except ImportError:
    # Fall back to httpx
    return _call_openai_compatible(...)
```

### Retry Configuration

LiteLLM handles retries automatically:

```python
response = completion(
    model=model_to_use,
    messages=[...],
    num_retries=3,  # Configurable
)
```

## 🧪 Testing

### Unit Tests

```bash
# Test basic LLM call
uv run python test_litellm_integration.py

# Test with specific model
LLM_MODEL=anthropic/claude-3-haiku uv run python test_litellm_integration.py
```

### Integration Tests

```bash
# Test PDF extraction with new model
uv run python -m pytest test_llm_indicator_extract.py -v
```

## 📈 Benefits

1. **Flexibility**: Switch providers without code changes
2. **Cost Optimization**: Use cheaper models for simple tasks
3. **Redundancy**: Fall back to alternative providers if one fails
4. **Local Development**: Test with local models before deploying
5. **Future-Proof**: Easy to add new providers as they emerge

## 🐛 Troubleshooting

### Issue: "LLM Provider NOT provided"

**Solution**: Use the correct model format with provider prefix:
```bash
# ❌ Wrong
LLM_MODEL=deepseek-v4-flash

# ✅ Correct
LLM_MODEL=openai/deepseek-v4-flash
```

### Issue: "tenacity import failed"

**Solution**: Install tenacity:
```bash
uv pip install tenacity
```

### Issue: "LLM_API_KEY is not configured"

**Solution**: Set the environment variable:
```bash
echo 'LLM_API_KEY=your-key' >> .env.local
```

### Issue: Model not responding with JSON

**Solution**: Ensure your prompt explicitly requests JSON:
```python
system = "You are a helpful assistant. Always respond with valid JSON."
```

## 📚 References

- [LiteLLM Documentation](https://docs.litellm.ai/)
- [Supported Providers](https://docs.litellm.ai/docs/providers)
- [Model Format Guide](https://docs.litellm.ai/docs/completion/input)

## 🔐 Security Note

Never commit `.env.local` to version control! It's already in `.gitignore`.

---

Last updated: $(date +"%Y-%m-%d %H:%M:%S")
