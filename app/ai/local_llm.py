"""Local Ollama LLM calls."""

import logging

from app.config import settings
from app.ai.model_runtime import generate_ollama

logger = logging.getLogger(__name__)


def generate_text(
    prompt: str,
    max_tokens: int = 200,
    timeout: int = 180,
    fallback: str = "",
) -> tuple[str, str | None]:
    """
    Call the Ollama generate API.
    Return (text, error_message). error is None when the call succeeds.
    """
    if not settings.enable_ollama:
        return (
            fallback or "Local LLM is disabled. Using fallback message.",
            "Ollama integration disabled by ENABLE_OLLAMA=false",
        )

    result = generate_ollama(prompt, max_tokens=max_tokens, timeout=timeout)
    if result.ok and result.text:
        return result.text, None
    return (
        fallback or "LLM request failed. Using fallback message.",
        result.error or "Empty LLM response",
    )
