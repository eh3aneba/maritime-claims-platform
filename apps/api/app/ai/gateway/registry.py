from app.ai.gateway.base import AIProvider
from app.ai.gateway.disabled import DisabledAIProvider
from app.core.config import get_settings


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    if settings.ai_provider == "disabled":
        return DisabledAIProvider()
    if settings.ai_provider == "openai":
        from app.ai.gateway.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.ai_model,
            max_output_tokens=settings.ai_max_output_tokens,
        )
    raise RuntimeError(f"Unsupported AI provider: {settings.ai_provider}")
