from app.ai.gateway.base import AIProvider, AIProviderUnavailable
from app.ai.gateway.disabled import DisabledAIProvider
from app.core.config import get_settings


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    if settings.ai_provider == "disabled":
        return DisabledAIProvider()
    if settings.ai_provider == "ollama_local":
        # Do not authorize an insurer document run: the provider itself
        # requires the exact synthetic-only marker (not used by jobs).
        if (
            settings.app_env.lower().strip() not in {"development", "test"}
            or not settings.ai_local_experimental_enabled
        ):
            raise AIProviderUnavailable("local_ai_development_only")
        from app.ai.gateway.ollama_local import OllamaLocalExperimentalProvider

        return OllamaLocalExperimentalProvider(
            model=settings.ai_model,
            max_output_tokens=min(settings.ai_max_output_tokens, 512),
        )
    if settings.ai_provider == "openai":
        from app.ai.gateway.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.ai_model,
            max_output_tokens=settings.ai_max_output_tokens,
        )
    raise RuntimeError(f"Unsupported AI provider: {settings.ai_provider}")
