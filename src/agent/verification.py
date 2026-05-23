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

Auto-rejection: if overall status is FAILED due to website ERROR (unreachable
website), the application is automatically set to REJECTED.

Email: after verification completes, an email is sent to
amministrazionemfce@gmail.com with the result.

Triggered via POST /api/v1/admin/applications/{id}/verify (admin-only).
"""

import html
import json
import uuid
from datetime import datetime, timezone

import httpx
import structlog

log = structlog.get_logger()

_VERIFICATION_NOTIFY_EMAIL = "amministrazionemfce@gmail.com"

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


async def _check_website_http(url: str) -> tuple[bool, str]:
    """
    Perform an HTTP HEAD/GET request to check if the website is reachable.
    Returns (is_reachable, status_message).
    A 2xx or 3xx response counts as reachable.
    """
    if not url or not url.strip():
        return False, "No website URL provided"

    normalized = url.strip()
    if not normalized.startswith(("http://", "https://")):
        normalized = "https://" + normalized

    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 AIScore-Verification/1.0"},
        ) as client:
            try:
                resp = await client.head(normalized)
            except Exception:
                # Some servers reject HEAD — fall back to GET with streaming
                resp = await client.get(normalized)

            if resp.status_code < 400:
                return True, f"Website reachable (HTTP {resp.status_code})"
            return False, f"Website returned HTTP {resp.status_code}"

    except httpx.ConnectError:
        return False, "Website unreachable — connection refused or DNS failure"
    except httpx.TimeoutException:
        return False, "Website unreachable — request timed out"
    except Exception as exc:
        return False, f"Website check failed: {exc}"


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


async def _send_verification_email(
    company_name: str,
    website: str,
    overall_status: str,
    results: dict,
    application_id: str,
    auto_rejected: bool,
) -> None:
    """Send verification result email to the notification address."""
    try:
        from src.payments.emailer import send_email

        safe_company = html.escape(company_name or "Ukendt virksomhed")
        safe_website = html.escape(website or "—")
        safe_app_id = html.escape(application_id)

        status_color = "#16a34a" if overall_status == "COMPLETED" else "#dc2626"
        status_label = "COMPLETED ✓" if overall_status == "COMPLETED" else "FAILED ✗"

        rejection_notice = ""
        if auto_rejected:
            rejection_notice = """
  <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:6px;padding:12px 16px;margin:16px 0;">
    <strong style="color:#dc2626;">⚠ Ansøgningen er automatisk afvist</strong><br>
    <span style="color:#7f1d1d;font-size:13px;">Website kunne ikke verificeres — status sat til REJECTED.</span>
  </div>"""

        field_rows = ""
        field_labels = {
            "website": "Website",
            "industry": "Branche",
            "business_description": "Virksomhedsbeskrivelse",
            "competitors": "Konkurrenter",
            "application_goal": "Ansøgningsmål",
        }
        status_colors = {"OK": "#16a34a", "WARNING": "#d97706", "ERROR": "#dc2626"}
        for key, label in field_labels.items():
            field = results.get(key, {})
            if not isinstance(field, dict):
                continue
            fstatus = field.get("status", "—")
            fmsg = html.escape(field.get("message", ""))
            fcolor = status_colors.get(fstatus, "#6b7280")
            field_rows += f"""
    <tr>
      <td style="padding:8px 12px;font-weight:600;font-size:13px;white-space:nowrap;">{html.escape(label)}</td>
      <td style="padding:8px 12px;"><span style="color:{fcolor};font-weight:700;">{html.escape(fstatus)}</span></td>
      <td style="padding:8px 12px;font-size:13px;color:#374151;">{fmsg}</td>
    </tr>"""

        html_body = f"""<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <h2 style="margin-bottom:4px;">AIScore — Verifikationsresultat</h2>
  <p style="color:#6b7280;font-size:13px;margin-top:0;">Automatisk verifikation afsluttet</p>

  <table style="width:100%;border-collapse:collapse;background:#f9fafb;border-radius:6px;margin:16px 0;">
    <tr>
      <td style="padding:8px 12px;font-weight:600;font-size:13px;">Virksomhed</td>
      <td style="padding:8px 12px;font-size:13px;">{safe_company}</td>
    </tr>
    <tr>
      <td style="padding:8px 12px;font-weight:600;font-size:13px;">Website</td>
      <td style="padding:8px 12px;font-size:13px;">{safe_website}</td>
    </tr>
    <tr>
      <td style="padding:8px 12px;font-weight:600;font-size:13px;">Status</td>
      <td style="padding:8px 12px;font-size:13px;font-weight:700;color:{status_color};">{status_label}</td>
    </tr>
  </table>

  {rejection_notice}

  <h3 style="font-size:14px;margin-bottom:8px;">Feltresultater</h3>
  <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:6px;overflow:hidden;">
    <thead>
      <tr style="background:#f3f4f6;">
        <th style="padding:8px 12px;text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;">Felt</th>
        <th style="padding:8px 12px;text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;">Status</th>
        <th style="padding:8px 12px;text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;">Besked</th>
      </tr>
    </thead>
    <tbody>{field_rows}
    </tbody>
  </table>

  <p style="color:#6b7280;font-size:12px;margin-top:24px;">
    Applikations-ID: {safe_app_id}<br>
    AIScore intern system &bull; aiscore.dk
  </p>
</body>
</html>"""

        subject = f"[AIScore Verifikation] {overall_status} — {company_name}"
        if auto_rejected:
            subject = f"[AIScore Verifikation] AFVIST — {company_name}"

        await send_email(
            to=_VERIFICATION_NOTIFY_EMAIL,
            subject=subject,
            html_body=html_body,
        )
        log.info("verification.email_sent", to=_VERIFICATION_NOTIFY_EMAIL, company=company_name)
    except Exception as exc:
        log.error("verification.email_failed", error=str(exc))


async def run_application_verification(application_id: uuid.UUID) -> None:
    """
    Background verification task. Performs HTTP website check, then calls
    an LLM to verify each application field. Persists per-field results and
    overall status. Auto-rejects the application if the website is completely
    unreachable (website field = ERROR). Sends email notification on completion.
    Must not raise — all errors are caught and stored as FAILED status.
    """
    from src.db.connection import get_session_factory
    from src.db.models import CustomerApplication, CustomerApplicationStateLog, CustomerApplicationStatus
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

            # --- Step 1: HTTP website check ---
            website_reachable, website_check_msg = await _check_website_http(app.website or "")
            log.info(
                "verification.website_check",
                application_id=str(application_id),
                reachable=website_reachable,
                message=website_check_msg,
            )

            website_check_note = (
                f"\n\nNote: An automated HTTP check was performed on the website URL before this analysis."
                f" Result: {website_check_msg}."
                + (" The website responded successfully." if website_reachable
                   else " The website did NOT respond — treat the website field as ERROR.")
            )

            user_prompt = f"""Please verify each field of the following AIScore application:

Company name: {app.firmanavn}
Website: {app.website}
Industry: {app.industry or 'Not provided'}
Business description: {app.business_description or app.virksomhedsinfo}
Competitors: {app.competitors or 'Not provided'}
Application goal: {app.application_goal or 'Not provided'}
Country: {app.country or 'Not provided'}
{website_check_note}

Verify the following fields and return the JSON verification report."""

            data = await _call_llm(user_prompt, settings)

            # --- Step 2: If website unreachable, force website field to ERROR ---
            if not website_reachable:
                data["website"] = {
                    "status": "ERROR",
                    "message": website_check_msg,
                }

            overall_status = _derive_overall_status(data)
            now = datetime.now(timezone.utc)
            app.agent_verification_status = overall_status
            app.agent_verification_results = data
            app.agent_verified_at = now
            # Set verification substage based on outcome
            if overall_status == "FAILED":
                app.verification_substage = "FAILED"
                app.verification_failed_at = now
            elif overall_status in ("COMPLETED", "VERIFIED", "PASSED"):
                app.verification_substage = "VERIFIED"

            # --- Step 3: Auto-reject if FAILED due to website ERROR ---
            auto_rejected = False
            website_field = data.get("website", {})
            website_is_error = isinstance(website_field, dict) and website_field.get("status") == "ERROR"

            if overall_status == "FAILED" and website_is_error:
                allowed_from = {
                    CustomerApplicationStatus.APPLIED,
                    CustomerApplicationStatus.UNDER_REVIEW,
                }
                if app.status in allowed_from:
                    prev_status = app.status
                    rejection_reason = (
                        f"Automatisk afvisning: website ikke tilgængeligt. {website_check_msg}"
                    )
                    app.status = CustomerApplicationStatus.REJECTED
                    app.rejected_at = now
                    app.rejected_by = "verification-agent"
                    app.rejection_reason = rejection_reason
                    session.add(CustomerApplicationStateLog(
                        application_id=app.id,
                        from_status=prev_status,
                        to_status=CustomerApplicationStatus.REJECTED,
                        changed_by="verification-agent",
                        note=rejection_reason,
                    ))
                    auto_rejected = True
                    log.info(
                        "verification.auto_rejected",
                        application_id=str(application_id),
                        website=app.website,
                        reason=website_check_msg,
                    )

            await session.commit()

            log.info(
                "verification.completed",
                application_id=str(application_id),
                overall_status=overall_status,
                auto_rejected=auto_rejected,
            )

            # --- Step 4: Send email notification ---
            await _send_verification_email(
                company_name=app.firmanavn or "",
                website=app.website or "",
                overall_status=overall_status,
                results=data,
                application_id=str(application_id),
                auto_rejected=auto_rejected,
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
