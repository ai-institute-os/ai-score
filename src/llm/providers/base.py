from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import uuid


@dataclass
class ProviderConfig:
    """Runtime config resolved for a specific tenant + provider."""
    api_key: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class LLMResult:
    provider: str
    model: str
    prompt: str
    response_text: Optional[str]
    error: Optional[str]
    latency_ms: int
    tokens_used: Optional[int]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    request_id: uuid.UUID = field(default_factory=uuid.uuid4)
    cached: bool = False


class BaseProvider(ABC):
    name: str = ""
    default_model: str = ""

    @abstractmethod
    async def complete(self, prompt: str, config: ProviderConfig) -> LLMResult:
        """Send prompt to provider and return a normalised result."""
        ...
