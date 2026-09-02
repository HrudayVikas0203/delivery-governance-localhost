from dataclasses import dataclass
import logging

import httpx
from fastapi import HTTPException, status

from app.ai.gemini_response import extract_gemini_text
from app.core.config import get_settings

logger = logging.getLogger(__name__)

GROQ_MODEL_ALLOWLIST = {
    "qwen/qwen3.6-27b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
}


def validate_model_for_provider(provider_name: str, model_name: str | None) -> str:
    if not model_name:
        return get_settings().groq_default_model if provider_name == "groq" else get_settings().gemini_default_model
    normalized = str(model_name).strip()
    if provider_name == "groq":
        if normalized in GROQ_MODEL_ALLOWLIST:
            return normalized
        if normalized.startswith("llama-") or normalized.startswith("qwen/") or normalized.startswith("openai/"):
            return normalized
        logger.warning("Unexpected Groq model %s is not in the supported allowlist; using default model instead.", normalized)
        return get_settings().groq_default_model
    return normalized


@dataclass(frozen=True)
class LLMProvider:
    name: str
    display_name: str
    default_model: str
    configured: bool
    models: list[str]


def available_providers() -> list[LLMProvider]:
    settings = get_settings()
    groq_default = validate_model_for_provider("groq", settings.groq_default_model)
    gemini_default = settings.gemini_default_model or "gemini-2.0-flash"
    return [
        LLMProvider("groq", "Groq", groq_default, bool(settings.groq_api_key), [groq_default, "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "qwen/qwen3-32b"]),
        LLMProvider("gemini", "Gemini", gemini_default, bool(settings.gemini_api_key), [gemini_default]),
    ]


def require_provider(provider_name: str) -> LLMProvider:
    for provider in available_providers():
        if provider.name == provider_name:
            if not provider.configured:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{provider.display_name} API key is not configured")
            return provider
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported LLM provider")


def _messages(prompt: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a senior delivery governance analyst. Write concise, executive-ready "
                "content for delivery status reports. Use professional language, avoid filler, "
                "and make risks, recommendations, dependencies, and decisions clear."
            ),
        },
        {"role": "user", "content": prompt},
    ]


def generate_text(provider_name: str, prompt: str, model: str | None = None) -> tuple[str, str]:
    settings = get_settings()
    provider = require_provider(provider_name)
    model_name = validate_model_for_provider(provider.name, model or provider.default_model)

    try:
        if provider.name == "groq":
            from groq import Groq

            client = Groq(api_key=settings.groq_api_key, http_client=httpx.Client(timeout=25.0, trust_env=False), max_retries=2)
            response = client.chat.completions.create(model=model_name, messages=_messages(prompt), temperature=0.2, max_tokens=1200)
            return response.choices[0].message.content or "", model_name
        if provider.name == "gemini":
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=settings.gemini_api_key,
                http_options=types.HttpOptions(timeout=25_000),
            )
            response = client.models.generate_content(model=model_name, contents=prompt)
            return extract_gemini_text(response), model_name
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("LLM provider call failed for %s/%s", provider.name, model_name)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider.display_name} generation failed. Check API key, model name, network access, and provider limits.",
        ) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported LLM provider")
