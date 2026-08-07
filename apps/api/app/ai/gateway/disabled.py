from app.ai.gateway.base import AIProviderUnavailable, AIRequest, AIResponse


class DisabledAIProvider:
    name = "disabled"

    def generate(self, request: AIRequest) -> AIResponse:
        del request
        raise AIProviderUnavailable(
            "AI provider is disabled. Configure AI_PROVIDER before enabling document intelligence."
        )
