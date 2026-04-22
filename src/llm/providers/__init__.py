from src.llm.providers.base import BaseProvider, ProviderConfig, LLMResult
from src.llm.providers.openai_provider import OpenAIProvider
from src.llm.providers.gemini_provider import GeminiProvider
from src.llm.providers.perplexity_provider import PerplexityProvider
from src.llm.providers.copilot_provider import CopilotProvider

REGISTRY: dict[str, BaseProvider] = {
    "openai": OpenAIProvider(),
    "gemini": GeminiProvider(),
    "perplexity": PerplexityProvider(),
    "copilot": CopilotProvider(),
}

__all__ = [
    "BaseProvider", "ProviderConfig", "LLMResult",
    "OpenAIProvider", "GeminiProvider", "PerplexityProvider", "CopilotProvider",
    "REGISTRY",
]
