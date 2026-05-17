"""
Application Verification Agent.

Performs per-field AI verification of a customer application before the
Generate Questions phase. Each application field (website, industry,
business_description, competitors, application_goal) is verified
individually, and results are stored as a JSONB object.

Field status values: OK | WARNING | ERROR
Overall verification_status:
  - COMPLETED  when no field has ERROR status (warnings are acceptable)
  - FAILED     when one or more fields have ERROR status

Triggered via POST /api/v1/admin/applications/{id}/verify (admin-only).
"""

import json
import uuid
from datetime import datetime, timezone

import structlog

log = structlog.get_logger()

_SYSTEM_PROMPT = """You are a data quality analyst verifying the fields of a company's AIScore application.

AIScore is an AI-powered brand monitoring product that tracks how AI systems (ChatGPT, Gemini, Claude, Perplexity) mention and recommend a company versus its competitors.

For each application field listed, assess whether the information is credible, internally consistent, and sufficient. Return a JSON object with exactly these top-level keys:

{
  "website": {
    "status": "OK | WARNING | ERROR",
    "message": "One sentence explaining the assessment"
  },
  "industry": {
    "status": "OK | WARNING | ERROR",
    "message": "One sentence explaining the assessment"
  },
  "business_description": {
    "status": "OK | WARNING | ERROR",
    "message": "One sentence explaining the assessment"
  },
  "competitors": {
    "status": "OK | WARNING | ERROR",
    "message": "One sentence explaining the assessment"
  },
  "application_goal": {
    "status": "OK | WARNING | ERROR",
    "message": "One sentence explaining the assessment"
  }
}

Status guidance:
- OK: Field is credible, complete, and consistent with other fields
- WARNING: Field is acceptable but has minor issues — vague, unusual, slightly inconsistent, website may be temporarily unreachable, phone number format looks off, domain looks new or redirecting, description is short but plausible. A human should review but the application can proceed.
- ERROR: Field is fundamentally broken and blocks review — no website URL provided at all, business description is blank or gibberish, competitors listed are entirely unrelated to the stated industry, or the application appears fraudulent. Reserve ERROR only for cases where a human reviewer cannot make sense of the field at all.

When in doubt between WARNING and ERROR, choose WARNING. Unreachable websites, unverifiable phone numbers, and minor inconsistencies are WARNING, not ERROR.

Output ONLY valid JSON — no prose, no markdown fences."""


def _clean_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    return json.loads(raw)


async def _call_openai(prompt: str, api_key: str) -> dict:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key)
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1024,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return _clean_json(response.choices[0].message.content or "")
    finally:
        await client.close()


async def _call_gemini(prompt: str, api_key: str) -> dict:
    import httpx
    combined = f"{_SYSTEM_PROMPT}\n\n{prompt}"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-flash:generateContent?key={api_key}"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json={
            "contents": [{"parts": [{"text": combined}]}],
            "generationConfig": {"maxOutputTokens": 1024},
        })
        resp.raise_for_status()
        data = resp.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        return _clean_json(raw)


async def _call_anthropic(prompt: str, api_key: str) -> dict:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return _clean_json(response.content[0].text if response.content else "")
    finally:
        await client.close()


async def _call_llm(prompt: str, settings) -> dict:
    """Try LLM providers in order: OpenAI → Gemini → Anthropic."""
    providers = [
        ("openai",    settings.openai_api_key,    _call_openai),
        ("gemini",    settings.google_api_key,     _call_gemini),
        ("anthropic", settings.anthropic_api_key,  _call_anthropic),
    ]
    last_error: Exception = ValueError("No LLM provider configured")
    for name, key, fn in providers:
        if not key:
            continue
        try:
            log.info("verification.llm_attempt", provider=name)
            return await fn(prompt, key)
        except Exception as exc:
            log.warning("verification.llm_provider_failed", provider=name, error=str(exc))
            last_error = exc
    raise last_error


def _derive_overall_status(results: dict) -> str:
    """COMPLETED if no field has ERROR, else FAILED."""
    for field_data in results.values():
        if isinstance(field_data, dict) and field_data.get("status") == "ERROR":
            return "FAILED"
    return "COMPLETED"


async def run_application_verification(application_id: uuid.UUID) -> None:
    """
    Background verification task. Calls Claude to verify each application
    field individually, then persists per-field results and overall status.
    Must not raise — all errors are caught and stored as FAILED status.
    """
    from src.db.connection import get_session_factory
    from src.db.models import CustomerApplication
    from src.config import get_settings
    from sqlalchemy import select

    settings = get_settings()

    log.info("verification.started", application_id=str(application_id))

    # Mark IN_PROGRESS
    async with get_session_factory()() as session:
        result = await session.execute(
            select(CustomerApplication).where(CustomerApplication.id == application_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            log.error("verification.application_not_found", application_id=str(application_id))
            return
        app.agent_verification_status = "IN_PROGRESS"
        await session.commit()

    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(CustomerApplication).where(CustomerApplication.id == application_id)
            )
            app = result.scalar_one_or_none()
            if not app:
                return

            user_prompt = f"""Please verify each field of the following AIScore application:

Company name: {app.firmanavn}
Website: {app.website}
Industry: {app.industry or 'Not provided'}
Business description: {app.business_description or app.virksomhedsinfo}
Competitors: {app.competitors or 'Not provided'}
Application goal: {app.application_goal or 'Not provided'}
Country: {app.country or 'Not provided'}

Verify the following fields and return the JSON verification report."""

            data = await _call_llm(user_prompt, settings)

            overall_status = _derive_overall_status(data)
            app.agent_verification_status = overall_status
            app.agent_verification_results = data
            app.agent_verified_at = datetime.now(timezone.utc)
            await session.commit()

            log.info(
                "verification.completed",
                application_id=str(application_id),
                overall_status=overall_status,
            )

    except Exception as exc:
        log.error("verification.failed", application_id=str(application_id), error=str(exc))
        try:
            from src.db.connection import get_session_factory as _gsf
            from sqlalchemy import select as _select

            async with _gsf()() as session:
                result = await session.execute(
                    _select(CustomerApplication).where(CustomerApplication.id == application_id)
                )
                app = result.scalar_one_or_none()
                if app:
                    app.agent_verification_status = "FAILED"
                    app.agent_verification_results = {"error": str(exc)}
                    await session.commit()
        except Exception as inner_exc:
            log.error(
                "verification.error_save_failed",
                application_id=str(application_id),
                error=str(inner_exc),
            )
