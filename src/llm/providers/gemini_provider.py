import time
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from src.llm.providers.base import BaseProvider, ProviderConfig, LLMResult

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(BaseProvider):
    name = "gemini"
    default_model = "gemini-2.0-flash"

    @retry(
        retry=retry_if_exception_type(httpx.HTTPStatusError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def complete(self, prompt: str, config: ProviderConfig) -> LLMResult:
        model = config.extra.get("model", self.default_model)
        url = f"{GEMINI_API_BASE}/{model}:generateContent?key={config.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": config.extra.get("temperature", 0.7),
                "maxOutputTokens": config.extra.get("max_tokens", 2048),
            },
        }

        t0 = time.monotonic()
        error = None
        response_text = None
        tokens_used = prompt_tokens = completion_tokens = None

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                data = r.json()

            candidate = data["candidates"][0]["content"]["parts"][0]["text"]
            response_text = candidate

            usage = data.get("usageMetadata", {})
            prompt_tokens = usage.get("promptTokenCount")
            completion_tokens = usage.get("candidatesTokenCount")
            if prompt_tokens and completion_tokens:
                tokens_used = prompt_tokens + completion_tokens
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
