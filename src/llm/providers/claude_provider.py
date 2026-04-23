import time
import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from src.llm.providers.base import BaseProvider, ProviderConfig, LLMResult


class ClaudeProvider(BaseProvider):
    """Anthropic Claude provider (claude-sonnet-4-6 by default)."""

    name = "claude"
    default_model = "claude-sonnet-4-6"

    @retry(
        retry=retry_if_exception_type(anthropic.RateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def complete(self, prompt: str, config: ProviderConfig) -> LLMResult:
        model = config.extra.get("model", self.default_model)
        client = anthropic.AsyncAnthropic(api_key=config.api_key)
        t0 = time.monotonic()
        error = None
        response_text = None
        tokens_used = prompt_tokens = completion_tokens = None

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=config.extra.get("max_tokens", 2048),
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = response.content[0].text if response.content else None
            if response.usage:
                prompt_tokens = response.usage.input_tokens
                completion_tokens = response.usage.output_tokens
                tokens_used = prompt_tokens + completion_tokens
        except Exception as exc:
            error = str(exc)
        finally:
            await client.close()

        latency_ms = int((time.monotonic() - t0) * 1000)
        return LLMResult(
            provider=self.name,
            model=model,
            prompt=prompt,
            response_text=response_text,
            error=error,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
