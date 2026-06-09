"""Tests for JSON extraction and the LLM provider factory."""

from __future__ import annotations

import os

import pytest

from reasoning.llm import LLMSettings, create_provider
from reasoning.thesis.generator import _extract_json


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


def test_extract_json_plain_object() -> None:
    text = '{"instrument": "BTC-USD", "direction": "long", "confidence": 0.7}'
    result = _extract_json(text)
    assert result is not None
    assert result["direction"] == "long"


def test_extract_json_strips_code_fence() -> None:
    text = "```json\n{\"direction\": \"short\"}\n```"
    result = _extract_json(text)
    assert result is not None
    assert result["direction"] == "short"


def test_extract_json_embedded_in_prose() -> None:
    text = 'Here is the thesis:\n{"summary": "test", "confidence": 0.5}\nThat\'s it.'
    result = _extract_json(text)
    assert result is not None
    assert result["summary"] == "test"


def test_extract_json_returns_none_for_garbage() -> None:
    assert _extract_json("no json here at all") is None
    assert _extract_json("```\nbroken { json\n```") is None


def test_extract_json_returns_none_for_array() -> None:
    # Top-level arrays are not valid thesis responses
    assert _extract_json("[1, 2, 3]") is None


# ---------------------------------------------------------------------------
# create_provider factory
# ---------------------------------------------------------------------------


def test_create_provider_ollama() -> None:
    settings = LLMSettings(provider="ollama", model="llama3.2")
    from reasoning.llm.providers.ollama import OllamaProvider
    provider = create_provider(settings)
    assert isinstance(provider, OllamaProvider)


def test_create_provider_anthropic() -> None:
    pytest.importorskip("anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    settings = LLMSettings(provider="anthropic", model="claude-haiku-4-5-20251001")
    from reasoning.llm.providers.anthropic import AnthropicProvider
    provider = create_provider(settings)
    assert isinstance(provider, AnthropicProvider)


def test_create_provider_openai() -> None:
    pytest.importorskip("openai")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    settings = LLMSettings(provider="openai", model="gpt-4o-mini")
    from reasoning.llm.providers.openai import OpenAIProvider
    provider = create_provider(settings)
    assert isinstance(provider, OpenAIProvider)


def test_create_provider_groq() -> None:
    pytest.importorskip("openai")
    if not os.environ.get("GROQ_API_KEY"):
        pytest.skip("GROQ_API_KEY not set")
    from reasoning.llm.providers.openai_compatible import OpenAICompatibleProvider
    settings = LLMSettings(provider="groq")
    provider = create_provider(settings)
    assert isinstance(provider, OpenAICompatibleProvider)


def test_create_provider_mistral() -> None:
    pytest.importorskip("openai")
    if not os.environ.get("MISTRAL_API_KEY"):
        pytest.skip("MISTRAL_API_KEY not set")
    from reasoning.llm.providers.openai_compatible import OpenAICompatibleProvider
    settings = LLMSettings(provider="mistral")
    provider = create_provider(settings)
    assert isinstance(provider, OpenAICompatibleProvider)


def test_create_provider_openrouter() -> None:
    pytest.importorskip("openai")
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")
    from reasoning.llm.providers.openai_compatible import OpenAICompatibleProvider
    settings = LLMSettings(provider="openrouter")
    provider = create_provider(settings)
    assert isinstance(provider, OpenAICompatibleProvider)


def test_model_defaults_per_provider() -> None:
    from reasoning.llm.settings import PROVIDER_DEFAULT_MODELS
    # Empty model string → factory uses provider default
    for provider_name, expected_model in PROVIDER_DEFAULT_MODELS.items():
        settings = LLMSettings.model_construct(provider=provider_name, model="")  # type: ignore[call-arg]
        model = settings.model or PROVIDER_DEFAULT_MODELS.get(provider_name, "")
        assert model == expected_model


def test_explicit_model_overrides_default() -> None:
    from reasoning.llm.settings import PROVIDER_DEFAULT_MODELS
    settings = LLMSettings(provider="groq", model="mixtral-8x7b-32768")
    model = settings.model or PROVIDER_DEFAULT_MODELS.get(settings.provider, "")
    assert model == "mixtral-8x7b-32768"


def test_create_provider_unknown_raises() -> None:
    settings = LLMSettings.model_construct(provider="unknown")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_provider(settings)
