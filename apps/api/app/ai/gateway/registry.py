from app.ai.gateway.base import AIProvider
from app.ai.gateway.disabled import DisabledAIProvider
from app.core.config import get_settings


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    if settings.ai_provider == "disabled":
        return DisabledAIProvider()
    raise RuntimeError(f"Unsupported AI provider: {settings.ai_provider}")
