from dataclasses import dataclass
from functools import lru_cache
import logging
import re

import httpx
from fastapi import HTTPException, status

from app.ai.gemini_response import extract_gemini_text
from app.core.config import get_settings

logger = logging.getLogger(__name__)

GROQ_PRODUCTION_MODELS = (
    "qwen/qwen3.6-27b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
)
GROQ_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

GROQ_MISSING_KEY_MESSAGE = (
    "Groq is not configured. Set GROQ_API_KEY in the backend environment and restart the backend."
)
GROQ_AUTH_MESSAGE = "Groq authentication failed. Verify GROQ_API_KEY in the backend environment."
GROQ_MODEL_MESSAGE = "The configured Groq model is unavailable. Verify GROQ_DEFAULT_MODEL and restart the backend."
GROQ_RATE_LIMIT_MESSAGE = "Groq rate limit reached. Please try again later."
GROQ_NETWORK_MESSAGE = "Groq is temporarily unreachable. Please try again later."
GROQ_API_MESSAGE = "Groq request failed. Please try again later."


def validate_model_for_provider(provider_name: str, model_name: str | None) -> str:
    if not model_name:
        return get_settings().groq_default_model if provider_name == "groq" else get_settings().gemini_default_model
    normalized = str(model_name).strip()
    if provider_name == "groq" and not GROQ_MODEL_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=GROQ_MODEL_MESSAGE,
        )
    return normalized


def _safe_groq_error(exc: Exception) -> HTTPException:
    """Map provider failures to stable messages without returning provider payloads."""
    exception_name = type(exc).__name__
    provider_status = getattr(exc, "status_code", None)
    body = str(getattr(exc, "body", "")).lower()

    if exception_name in {"AuthenticationError", "PermissionDeniedError"} or provider_status in {401, 403}:
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=GROQ_AUTH_MESSAGE)
    if exception_name == "RateLimitError" or provider_status == 429:
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=GROQ_RATE_LIMIT_MESSAGE)
    model_markers = ("model", "decommission", "not_found", "not found", "permission")
    if exception_name == "NotFoundError" or provider_status == 404 or (
        provider_status == 400 and any(marker in body for marker in model_markers)
    ):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=GROQ_MODEL_MESSAGE)
    if exception_name == "APITimeoutError":
        return HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=GROQ_NETWORK_MESSAGE)
    if exception_name == "APIConnectionError":
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=GROQ_NETWORK_MESSAGE)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=GROQ_API_MESSAGE)


@lru_cache(maxsize=1)
def _available_groq_models() -> frozenset[str]:
    settings = get_settings()
    if not settings.groq_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=GROQ_MISSING_KEY_MESSAGE)

    try:
        from groq import Groq

        with httpx.Client(timeout=10.0, trust_env=False) as http_client:
            client = Groq(api_key=settings.groq_api_key, http_client=http_client, max_retries=1)
            response = client.models.list()
        return frozenset(item.id for item in getattr(response, "data", []) if getattr(item, "id", None))
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "Groq model discovery failed (error_type=%s, status=%s).",
            type(exc).__name__,
            getattr(exc, "status_code", None),
        )
        raise _safe_groq_error(exc) from None


def resolve_available_groq_model(preferred_model: str | None = None) -> str:
    settings = get_settings()
    configured = validate_model_for_provider("groq", preferred_model or settings.groq_default_model)
    if configured not in _available_groq_models():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=GROQ_MODEL_MESSAGE)
    return configured


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
        LLMProvider(
            "groq",
            "Groq",
            groq_default,
            bool(settings.groq_api_key),
            list(dict.fromkeys([groq_default, *GROQ_PRODUCTION_MODELS])),
        ),
        LLMProvider("gemini", "Gemini", gemini_default, bool(settings.gemini_api_key), [gemini_default]),
    ]


def require_provider(provider_name: str) -> LLMProvider:
    for provider in available_providers():
        if provider.name == provider_name:
            if not provider.configured:
                if provider.name == "groq":
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=GROQ_MISSING_KEY_MESSAGE,
                    )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"{provider.display_name} is not configured.",
                )
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


def _strip_hidden_reasoning(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()


def generate_text(
    provider_name: str,
    prompt: str,
    model: str | None = None,
    max_tokens: int = 1200,
) -> tuple[str, str]:
    settings = get_settings()
    provider = require_provider(provider_name)

    model_name = (
        resolve_available_groq_model(model or provider.default_model)
        if provider.name == "groq"
        else validate_model_for_provider(
            provider.name,
            model or provider.default_model,
        )
    )

    # Prevent invalid or unexpectedly large values from reaching providers.
    max_tokens = max(256, min(max_tokens, 16_384))

    try:
        # ---------------------------------------------------------
        # GROQ
        # ---------------------------------------------------------
        if provider.name == "groq":
            from groq import Groq

            with httpx.Client(
                timeout=60.0,
                trust_env=False,
            ) as http_client:
                client = Groq(
                    api_key=settings.groq_api_key,
                    http_client=http_client,
                    max_retries=2,
                )

                response = client.chat.completions.create(
                    model=model_name,
                    messages=_messages(prompt),
                    temperature=0.2,
                    max_tokens=max_tokens,
                )

            content = ""

            if response.choices:
                message = response.choices[0].message
                content = message.content or ""

            content = _strip_hidden_reasoning(content)

            if not content.strip():
                logger.warning(
                    "LLM provider returned empty response "
                    "(provider=%s, model=%s).",
                    provider.name,
                    model_name,
                )

                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        f"{provider.display_name} returned an empty response. "
                        "Please try again."
                    ),
                )

            return content, model_name

        # ---------------------------------------------------------
        # GEMINI
        # ---------------------------------------------------------
        if provider.name == "gemini":
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=settings.gemini_api_key,
                http_options=types.HttpOptions(
                    timeout=60_000,
                ),
            )

            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=max_tokens,
                ),
            )

            content = _strip_hidden_reasoning(
                extract_gemini_text(response)
            )

            if not content.strip():
                logger.warning(
                    "LLM provider returned empty response "
                    "(provider=%s, model=%s).",
                    provider.name,
                    model_name,
                )

                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        f"{provider.display_name} returned an empty response. "
                        "Please try again."
                    ),
                )

            return content, model_name

    except HTTPException:
        raise

    except Exception as exc:
        logger.warning(
            "LLM provider call failed "
            "(provider=%s, model=%s, max_tokens=%s, "
            "error_type=%s, status=%s).",
            provider.name,
            model_name,
            max_tokens,
            type(exc).__name__,
            getattr(exc, "status_code", None),
        )

        if provider.name == "groq":
            raise _safe_groq_error(exc) from None

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"{provider.display_name} generation failed. "
                "Please try again later."
            ),
        ) from None

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported LLM provider",
    )