"""
Microsoft Copilot proxy via Azure OpenAI + Bing Search grounding.

Design decision (documented for Dennis/customer):
  We proxy Microsoft Copilot via Azure OpenAI (GPT-4o deployment) combined
  with Bing Search API. On each request we:
    1. Call Bing Search with the user prompt to retrieve top-5 web snippets.
    2. Inject those snippets as a system context message.
    3. Forward the enriched prompt to the Azure OpenAI chat completions endpoint.

  This gives the same "web-grounded" behaviour as Microsoft Copilot without
  requiring a direct Copilot API (which has no public programmatic access).
  The tenant must supply: azure_api_key, azure_endpoint, azure_deployment,
  azure_api_version, and bing_search_api_key in their provider config.
"""

import time
import httpx
from openai import AsyncAzureOpenAI
from openai import RateLimitError, APIStatusError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from src.llm.providers.base import BaseProvider, ProviderConfig, LLMResult

BING_SEARCH_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"


async def _bing_snippets(query: str, api_key: str, count: int = 5) -> str:
    """Fetch Bing Search snippets and format as context."""
    if not api_key:
        return ""
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"q": query, "count": count, "mkt": "en-US", "responseFilter": "Webpages"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(BING_SEARCH_ENDPOINT, headers=headers, params=params)
            r.raise_for_status()
            data = r.json()
        pages = data.get("webPages", {}).get("value", [])
        snippets = "\n".join(
            f"[{i+1}] {p['name']}: {p['snippet']}" for i, p in enumerate(pages)
        )
        return f"[Web search results for: {query}]\n{snippets}" if snippets else ""
    except Exception:
        return ""


class CopilotProvider(BaseProvider):
    """Azure OpenAI + Bing web grounding as Microsoft Copilot proxy."""

    name = "copilot"
    default_model = "gpt-4o"

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def complete(self, prompt: str, config: ProviderConfig) -> LLMResult:
        extra = config.extra
        deployment = extra.get("azure_deployment", "gpt-4o")
        api_version = extra.get("azure_api_version", "2024-05-01-preview")
        endpoint = extra.get("azure_endpoint", "")
        bing_key = extra.get("bing_search_api_key", "")

        # Fetch web grounding context from Bing
        web_context = await _bing_snippets(prompt, bing_key)

        messages = []
        if web_context:
            messages.append({"role": "system", "content": web_context})
        messages.append({"role": "user", "content": prompt})

        client = AsyncAzureOpenAI(
            api_key=config.api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )

        t0 = time.monotonic()
        error = None
        response_text = None
        tokens_used = prompt_tokens = completion_tokens = None

        try:
            response = await client.chat.completions.create(
                model=deployment,
                messages=messages,
                temperature=extra.get("temperature", 0.7),
                max_tokens=extra.get("max_tokens", 2048),
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
            model=deployment,
            prompt=prompt,
            response_text=response_text,
            error=error,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
