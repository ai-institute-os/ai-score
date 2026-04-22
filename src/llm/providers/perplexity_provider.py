import time
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from src.llm.providers.base import BaseProvider, ProviderConfig, LLMResult

PERPLEXITY_API_BASE = "https://api.perplexity.ai"


class PerplexityProvider(BaseProvider):
    name = "perplexity"
    default_model = "sonar-pro"

    @retry(
        retry=retry_if_exception_type(httpx.HTTPStatusError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def complete(self, prompt: str, config: ProviderConfig) -> LLMResult:
        model = config.extra.get("model", self.default_model)
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": config.extra.get("max_tokens", 2048),
            "temperature": config.extra.get("temperature", 0.7),
            # Enable web search (Perplexity default)
            "return_citations": True,
        }

        t0 = time.monotonic()
        error = None
        response_text = None
        tokens_used = prompt_tokens = completion_tokens = None

        try:
            async with httpx.AsyncClient(timeout=90) as client:
                r = await client.post(
                    f"{PERPLEXITY_API_BASE}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                r.raise_for_status()
                data = r.json()

            response_text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            tokens_used = usage.get("total_tokens")
        except Exception as exc:
            error = str(exc)

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
