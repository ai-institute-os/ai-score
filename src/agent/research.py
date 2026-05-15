"""
Background agent research task.

Fetches the client website and calls the LLM to produce a structured research
report — company summary, AIScore fit recommendation, interview questions, and
suggested prompt directions. Saves results to the CustomerApplication row.

Triggered from the public /applications endpoint after the application moves to
UNDER_REVIEW. Also callable via the retry endpoint.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select

log = structlog.get_logger()

_RESEARCH_TIMEOUT_S = 30
_WEBSITE_FETCH_TIMEOUT_S = 15
_MAX_WEBSITE_CHARS = 8_000

_SYSTEM_PROMPT = """You are an AI business analyst evaluating whether a company is a good fit for AIScore — an AI-powered brand monitoring and online reputation scoring product. AIScore tracks how AI systems (ChatGPT, Gemini, Claude, Perplexity) mention and recommend a company versus competitors, and provides actionable reports.

Given information about a company (website content + application details), produce a JSON object with EXACTLY the following keys (no extras, no markdown fences):

{
  "website_summary": "2-3 sentence summary of what the company does",
  "business_summary": "2-3 sentence summary focused on their business model, size, and market position",
  "target_audience": "Who their customers are",
  "products_services": "Main products or services offered",
  "market_context": "Industry trends or competitive landscape relevant to them",
  "competitor_notes": "Key competitors mentioned or inferable from context",
  "fit_recommendation": "RECOMMEND_APPROVE | NEEDS_MORE_INFORMATION | RECOMMEND_REJECT",
  "fit_reason": "1-2 sentences explaining the recommendation",
  "missing_information": "What information would help clarify the recommendation (if any, else null)",
  "interview_questions": [
    "Question 1 tailored to this specific company",
    "Question 2",
    "Question 3",
    "Question 4",
    "Question 5",
    "Question 6"
  ],
  "prompt_directions": [
    "Suggested AIScore report prompt direction 1 for this company",
    "Suggested AIScore report prompt direction 2",
    "Suggested AIScore report prompt direction 3"
  ]
}

Rules:
- interview_questions: 5-8 questions, specific to this company and their use case for AIScore
- prompt_directions: 2-4 concrete suggestions for what brand monitoring prompts would be most valuable for this company
- fit_recommendation must be exactly one of: RECOMMEND_APPROVE, NEEDS_MORE_INFORMATION, RECOMMEND_REJECT
- missing_information: string or null
- Output ONLY valid JSON, no prose, no markdown."""


async def _fetch_website(url: str) -> str:
    """Fetch website HTML and return truncated text content."""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    try:
        async with httpx.AsyncClient(
            timeout=_WEBSITE_FETCH_TIMEOUT_S,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AIScoreBot/1.0)"},
        ) as client:
            response = await client.get(url)
            text = response.text
            # Strip obvious HTML tags naively — good enough for LLM context
            import re
            text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:_MAX_WEBSITE_CHARS]
    except Exception as exc:
        log.warning("research.website_fetch_failed", url=url, error=str(exc))
        return ""


async def _call_llm(prompt: str, api_key: str) -> dict:
    """Call Claude and parse JSON response. Returns parsed dict."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text if response.content else ""
        # Strip markdown fences if the model adds them anyway
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()
        return json.loads(raw)
    finally:
        await client.close()


async def run_application_research(application_id: uuid.UUID) -> None:
    """
    Background research task. Fetches website, calls LLM, saves results.
    Must not raise — all errors are caught and stored as FAILED status.
    """
    from src.db.connection import get_session_factory
    from src.db.models import CustomerApplication
    from src.config import get_settings

    settings = get_settings()
    api_key = getattr(settings, "anthropic_api_key", "")

    log.info("research.started", application_id=str(application_id))

    # Mark IN_PROGRESS
    async with get_session_factory()() as session:
        result = await session.execute(
            select(CustomerApplication).where(CustomerApplication.id == application_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            log.error("research.application_not_found", application_id=str(application_id))
            return
        app.agent_research_status = "IN_PROGRESS"
        app.agent_research_error = None
        await session.commit()

    try:
        # Re-fetch app for data we need
        async with get_session_factory()() as session:
            result = await session.execute(
                select(CustomerApplication).where(CustomerApplication.id == application_id)
            )
            app = result.scalar_one_or_none()
            if not app:
                return

            website_text = await _fetch_website(app.website)

            user_prompt = f"""Company name: {app.firmanavn}
Website: {app.website}
Contact: {app.kontaktperson}
Industry: {app.industry or 'Unknown'}
Country: {app.country or 'Unknown'}
Business description (from application): {app.business_description or app.virksomhedsinfo}
Competitors mentioned: {app.competitors or 'None provided'}
Application goal: {app.application_goal or 'Not specified'}

Website content (truncated):
{website_text if website_text else '[Website could not be fetched]'}

Analyse this company and produce the JSON research report."""

            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")

            data = await _call_llm(user_prompt, api_key)

            app.agent_research_status = "COMPLETED"
            app.agent_website_summary = data.get("website_summary")
            app.agent_business_summary = data.get("business_summary")
            app.agent_target_audience = data.get("target_audience")
            app.agent_products_services = data.get("products_services")
            app.agent_market_context = data.get("market_context")
            app.agent_competitor_notes = data.get("competitor_notes")
            app.agent_fit_recommendation = data.get("fit_recommendation")
            app.agent_fit_reason = data.get("fit_reason")
            app.agent_missing_information = data.get("missing_information")
            app.agent_interview_questions = data.get("interview_questions")
            app.agent_prompt_directions = data.get("prompt_directions")
            app.agent_researched_at = datetime.now(timezone.utc)
            app.agent_research_error = None
            await session.commit()

            log.info(
                "research.completed",
                application_id=str(application_id),
                fit=app.agent_fit_recommendation,
            )

    except Exception as exc:
        log.error("research.failed", application_id=str(application_id), error=str(exc))
        try:
            async with get_session_factory()() as session:
                result = await session.execute(
                    select(CustomerApplication).where(CustomerApplication.id == application_id)
                )
                app = result.scalar_one_or_none()
                if app:
                    app.agent_research_status = "FAILED"
                    app.agent_research_error = str(exc)
                    # Still set a safe recommendation so admin knows to check manually
                    if not app.agent_fit_recommendation:
                        app.agent_fit_recommendation = "NEEDS_MORE_INFORMATION"
                    await session.commit()
        except Exception as inner_exc:
            log.error(
                "research.error_save_failed",
                application_id=str(application_id),
                error=str(inner_exc),
            )
