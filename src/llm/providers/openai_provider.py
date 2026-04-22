import time
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import RateLimitError, APIStatusError
from src.llm.providers.base import BaseProvider, ProviderConfig, LLMResult


class OpenAIProvider(BaseProvider):
    name = "openai"
    default_model = "gpt-4o"

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def complete(self, prompt: str, config: ProviderConfig) -> LLMResult:
        model = config.extra.get("model", self.default_model)
        client = AsyncOpenAI(api_key=config.api_key)
        t0 = time.monotonic()
        error = None
        response_text = None
        tokens_used = prompt_tokens = completion_tokens = None

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=config.extra.get("temperature", 0.7),
                max_tokens=config.extra.get("max_tokens", 2048),
            )
            response_text = response.choices[0].message.content
            if response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                tokens_used = response.usage.total_tokens
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
