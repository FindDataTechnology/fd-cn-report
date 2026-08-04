"""LLM adapter supporting multiple providers via LiteLLM.

This module provides a unified interface for LLM calls, supporting:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- DeepSeek
- Azure OpenAI
- Local models (Ollama, vLLM)
- Any OpenAI-compatible API

Usage:
    from llm_adapter import call_llm_json
    
    result = call_llm_json(
        system="You are a helpful assistant.",
        user="Extract financial data from this report...",
        model="deepseek-v4-flash"  # or any supported model
    )
"""
from __future__ import annotations

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _get_config() -> dict:
    """Get LLM configuration from environment variables."""
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "").rstrip("/"),
        "api_key": os.environ.get("LLM_API_KEY", "") or os.environ.get("OPENAI_API_KEY", ""),
        "model": os.environ.get("LLM_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o")),
        "pdf_process_model": os.environ.get("PDF_PROCESS_MODEL", ""),
    }


def call_llm_json(
    system: str,
    user: str,
    model: Optional[str] = None,
    max_retries: int = 3,
    temperature: float = 0,
    max_tokens: int = 32000,
) -> str:
    """Call LLM with JSON response format.
    
    Supports multiple providers via LiteLLM:
    - OpenAI: "gpt-4o", "gpt-3.5-turbo"
    - Anthropic: "claude-3-opus", "claude-3-sonnet"
    - DeepSeek: "deepseek-v4-flash", "deepseek-chat"
    - Azure: "azure/gpt-4o"
    - Local: "ollama/llama3.1", "huggingface/..."
    
    Args:
        system: System prompt
        user: User prompt
        model: Model name (overrides LLM_MODEL env var)
        max_retries: Number of retry attempts
        temperature: Sampling temperature (0 = deterministic)
        max_tokens: Maximum tokens in response
        
    Returns:
        LLM response content as string
        
    Raises:
        RuntimeError: If LLM is not configured or call fails
    """
    cfg = _get_config()
    
    # Use provided model or fall back to config
    model_to_use = model or cfg["pdf_process_model"] or cfg["model"]
    api_key = cfg["api_key"]
    base_url = cfg["base_url"]
    
    if not api_key:
        raise RuntimeError("LLM_API_KEY is not configured")
    
    # Try LiteLLM first (supports multiple providers)
    try:
        from litellm import completion
        
        logger.info(f"Calling LLM via LiteLLM: {model_to_use}")
        
        response = completion(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            api_base=base_url if base_url else None,
            response_format={"type": "json_object"},
            num_retries=max_retries,
        )
        
        content = response.choices[0].message.content
        logger.info(f"LLM response received: {len(content)} chars")
        return content
        
    except ImportError:
        logger.warning("LiteLLM not installed, falling back to direct OpenAI API")
        # Fall back to direct httpx call
        return _call_openai_compatible(
            system=system,
            user=user,
            model=model_to_use,
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.error(f"LiteLLM call failed: {e}")
        raise RuntimeError(f"LLM call failed: {e}") from e


def _call_openai_compatible(
    system: str,
    user: str,
    model: str,
    api_key: str,
    base_url: str,
    max_retries: int = 3,
    temperature: float = 0,
    max_tokens: int = 32000,
) -> str:
    """Fallback: Direct OpenAI-compatible API call via httpx."""
    import httpx
    import time
    
    if not base_url:
        raise RuntimeError("LLM_BASE_URL is required for direct API calls")
    
    url = base_url + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                logger.info(f"OpenAI-compatible response: {len(content)} chars")
                return content
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = 2 ** attempt
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay}s: {e}")
            time.sleep(delay)
    
    raise RuntimeError("All retry attempts failed")


def list_supported_providers() -> list[str]:
    """List all supported LLM providers."""
    return [
        "openai",           # GPT-4, GPT-3.5
        "anthropic",        # Claude 3, Claude 2
        "deepseek",         # DeepSeek Chat, DeepSeek Coder
        "azure",            # Azure OpenAI
        "ollama",           # Local models
        "huggingface",      # Hugging Face models
        "together_ai",      # Together AI
        "perplexity",       # Perplexity AI
        "groq",             # Groq Cloud
        "mistral",          # Mistral AI
        "custom",           # Any OpenAI-compatible API
    ]


def get_model_examples(provider: str) -> list[str]:
    """Get example model names for a provider."""
    examples = {
        "openai": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
        "anthropic": ["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
        "deepseek": ["deepseek-v4-flash", "deepseek-chat", "deepseek-coder"],
        "azure": ["azure/gpt-4o", "azure/gpt-35-turbo"],
        "ollama": ["ollama/llama3.1", "ollama/mistral"],
        "huggingface": ["huggingface/meta-llama/Llama-3-70b-chat-hf"],
        "together_ai": ["together_ai/meta-llama/Llama-3-70b-chat-hf"],
        "perplexity": ["perplexity/pplx-70b-online"],
        "groq": ["groq/llama3-70b-8192", "groq/mixtral-8x7b-32768"],
        "mistral": ["mistral/mistral-large-latest", "mistral/mistral-medium-latest"],
        "custom": ["custom-model-name"],
    }
    return examples.get(provider, [])
