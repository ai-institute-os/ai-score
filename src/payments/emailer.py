"""
Async email sender using aiosmtplib.

All outbound emails go through send_email(). Higher-level helpers (e.g.
send_payment_link_email) build the HTML body and delegate here.
"""

import html
import structlog
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from src.config import get_settings

log = structlog.get_logger()


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
) -> None:
    """Send an HTML email. Falls back gracefully when SMTP is not configured."""
    settings = get_settings()

    if not settings.smtp_username or not settings.smtp_password:
        log.warning(
            "email.skipped",
            reason="SMTP credentials not configured",
            to=to,
            subject=subject,
        )
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            start_tls=True,
        )
        log.info("email.sent", to=to, subject=subject)
    except Exception as exc:
        log.error("email.failed", to=to, subject=subject, error=str(exc))
        raise


async def send_payment_link_email(
    customer_email: str,
    customer_name: str,
    company_name: str,
    payment_url: str,
    amount_dkk: int,
) -> None:
    """Send the payment link to the customer so they can pay during the call."""
    subject = f"Betal for din AIScore Rapport — {company_name}"
    safe_customer_name = html.escape(customer_name)
    safe_company_name = html.escape(company_name)
    safe_payment_url = html.escape(payment_url)

    html_body = f"""
<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <h2 style="color:#1d4ed8;">Din AIScore Rapport er klar til betaling</h2>
  <p>Hej {safe_customer_name},</p>
  <p>
    Tak for din interesse i en AIScore Rapport for <strong>{safe_company_name}</strong>.
    Som aftalt kan du gennemføre betalingen direkte via linket nedenfor.
  </p>
  <p style="margin:32px 0;text-align:center;">
    <a href="{safe_payment_url}"
       style="background:#1d4ed8;color:#fff;padding:14px 28px;border-radius:6px;
              text-decoration:none;font-size:16px;font-weight:bold;">
      Betal {amount_dkk:,} kr. nu
    </a>
  </p>
  <p style="color:#6b7280;font-size:13px;">
    Linket er gyldigt i 1 time. Betaling sker sikkert via Stripe.
  </p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:32px 0;">
  <p style="color:#6b7280;font-size:12px;">
    AIScore &bull; aiscore.dk &bull; Har du spørgsmål? Skriv til os på
    <a href="mailto:support@aiscore.dk">support@aiscore.dk</a>
  </p>
</body>
</html>
""".strip()

    text_body = (
        f"Hej {customer_name},\n\n"
        f"Betal for din AIScore Rapport ({company_name}) her:\n{payment_url}\n\n"
        f"Beløb: {amount_dkk:,} kr.  Linket udløber om 1 time.\n\n"
        f"AIScore — support@aiscore.dk"
    )

    await send_email(
        to=customer_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )


async def send_qc_escalation_email(
    company_name: str,
    application_id: str,
    failure_count: int,
    is_final_escalation: bool,
    admin_note: Optional[str] = None,
) -> None:
    """
    Alert research@aiscore.dk (and admin) when QC failures trigger escalation.

    is_final_escalation=True means 3 post-manual failures → Dennis contacts customer → cancel.
    """
    settings = get_settings()
    safe_company_name = html.escape(company_name)
    safe_application_id = html.escape(application_id)

    if is_final_escalation:
        subject = f"[AIScore QC] ENDELIG ESKALERING — {company_name} rapport annulleres"
        headline = "Rapport annulleres efter 3 yderligere QC-fejl"
        body_text = (
            f"Rapporten for <strong>{safe_company_name}</strong> har fejlet QC "
            f"{failure_count} gange efter manuel korrekt. "
            f"Dennis skal kontakte kunden, og rapporten vil blive annulleret."
        )
        action = "Kontakt kunden og annuller rapporten."
    else:
        subject = f"[AIScore QC] Eskalering — {company_name} — {failure_count} QC-fejl"
        headline = f"QC-fejl nr. {failure_count} — Manuel korrekt nødvendig"
        body_text = (
            f"Rapporten for <strong>{safe_company_name}</strong> har automatisk fejlet "
            f"QC {failure_count} gange. "
            f"Dennis skal evaluere manuelt og indlæse den korrigerede version."
        )
        action = "Gennemgå rapporten og foretag manuel korrekt."

    if admin_note:
        body_text += f"<br><br><strong>Seneste QC-note:</strong> {html.escape(admin_note)}"

    html_body = f"""
<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <h2 style="color:#b91c1c;">{headline}</h2>
  <p>{body_text}</p>
  <p><strong>Handling:</strong> {action}</p>
  <p style="color:#6b7280;font-size:13px;">
    Applikations-ID: {safe_application_id}<br>
    AIScore intern system
  </p>
</body>
</html>
""".strip()

    recipients = [settings.qc_alert_email, settings.admin_email]
    for recipient in recipients:
        await send_email(to=recipient, subject=subject, html_body=html_body)


async def send_subscription_confirmation_email(
    customer_email: str,
    customer_name: str,
    company_name: str,
    tier: str,
    period_end: Optional[str] = None,
) -> None:
    """Confirm a new AISelect subscription to the customer."""
    subject = f"Velkommen til AISelect {tier.capitalize()} — {company_name}"
    safe_customer_name = html.escape(customer_name)
    safe_company_name = html.escape(company_name)
    safe_tier = html.escape(tier)
    period_line = (
        f"<p>Dit abonnement fornyes automatisk d. <strong>{html.escape(period_end)}</strong>.</p>"
        if period_end else ""
    )

    html_body = f"""
<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <h2 style="color:#1d4ed8;">Tak for dit abonnement på AISelect {safe_tier.capitalize()}</h2>
  <p>Hej {safe_customer_name},</p>
  <p>
    Vi har modtaget din betaling og dit abonnement for <strong>{safe_company_name}</strong>
    er nu aktivt på pakken <strong>{safe_tier.capitalize()}</strong>.
  </p>
  {period_line}
  <p>Log ind på <a href="https://aiselect.dk">aiselect.dk</a> for at komme i gang.</p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:32px 0;">
  <p style="color:#6b7280;font-size:12px;">
    AISelect &bull; aiselect.dk &bull;
    <a href="mailto:support@aiscore.dk">support@aiscore.dk</a>
  </p>
</body>
</html>
""".strip()

    text_body = (
        f"Hej {customer_name},\n\n"
        f"Tak for dit abonnement på AISelect {tier.capitalize()} ({company_name}).\n"
        f"Dit abonnement er nu aktivt.\n\n"
        f"Log ind på https://aiselect.dk\n\n"
        f"AISelect — support@aiscore.dk"
    )

    await send_email(to=customer_email, subject=subject, html_body=html_body, text_body=text_body)


async def send_subscription_updated_email(
    customer_email: str,
    customer_name: str,
    company_name: str,
    old_tier: str,
    new_tier: str,
) -> None:
    """Notify customer when their AISelect subscription tier changes."""
    subject = f"Dit AISelect abonnement er opdateret — {company_name}"
    safe_customer_name = html.escape(customer_name)
    safe_company_name = html.escape(company_name)
    safe_old_tier = html.escape(old_tier)
    safe_new_tier = html.escape(new_tier)

    html_body = f"""
<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <h2 style="color:#1d4ed8;">Dit abonnement er blevet opdateret</h2>
  <p>Hej {safe_customer_name},</p>
  <p>
    Dit AISelect abonnement for <strong>{safe_company_name}</strong> er skiftet
    fra <strong>{safe_old_tier.capitalize()}</strong> til <strong>{safe_new_tier.capitalize()}</strong>.
  </p>
  <p>Ændringen træder i kraft øjeblikkeligt. Log ind på
     <a href="https://aiselect.dk">aiselect.dk</a> for at se din opdaterede adgang.
  </p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:32px 0;">
  <p style="color:#6b7280;font-size:12px;">
    AISelect &bull; aiselect.dk &bull;
    <a href="mailto:support@aiscore.dk">support@aiscore.dk</a>
  </p>
</body>
</html>
""".strip()

    text_body = (
        f"Hej {customer_name},\n\n"
        f"Dit AISelect abonnement ({company_name}) er ændret fra {old_tier} til {new_tier}.\n\n"
        f"Log ind på https://aiselect.dk\n\n"
        f"AISelect — support@aiscore.dk"
    )

    await send_email(to=customer_email, subject=subject, html_body=html_body, text_body=text_body)


async def send_subscription_cancelled_email(
    customer_email: str,
    customer_name: str,
    company_name: str,
    tier: str,
    period_end: Optional[str] = None,
) -> None:
    """Notify customer that their AISelect subscription has been cancelled."""
    subject = f"Dit AISelect abonnement er annulleret — {company_name}"
    safe_customer_name = html.escape(customer_name)
    safe_company_name = html.escape(company_name)
    safe_tier = html.escape(tier)
    access_line = (
        f"<p>Du har adgang til <strong>{safe_tier.capitalize()}</strong>-funktioner frem til <strong>{html.escape(period_end)}</strong>.</p>"
        if period_end else ""
    )

    html_body = f"""
<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <h2 style="color:#b91c1c;">Dit abonnement er annulleret</h2>
  <p>Hej {safe_customer_name},</p>
  <p>
    Dit AISelect abonnement (<strong>{safe_tier.capitalize()}</strong>) for
    <strong>{safe_company_name}</strong> er blevet annulleret.
  </p>
  {access_line}
  <p>
    Har du annulleret ved en fejl? Skriv til
    <a href="mailto:support@aiscore.dk">support@aiscore.dk</a> — vi hjælper gerne.
  </p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:32px 0;">
  <p style="color:#6b7280;font-size:12px;">
    AISelect &bull; aiselect.dk
  </p>
</body>
</html>
""".strip()

    text_body = (
        f"Hej {customer_name},\n\n"
        f"Dit AISelect abonnement ({tier}, {company_name}) er annulleret.\n"
        + (f"Adgang til {period_end}.\n\n" if period_end else "\n")
        + f"Spørgsmål? support@aiscore.dk\n\n"
        f"AISelect"
    )

    await send_email(to=customer_email, subject=subject, html_body=html_body, text_body=text_body)


async def send_payment_failed_email(
    customer_email: str,
    customer_name: str,
    company_name: str,
    tier: str,
    amount_dkk: Optional[int] = None,
) -> None:
    """Notify customer when an AISelect invoice payment fails."""
    subject = f"Betaling mislykkedes for dit AISelect abonnement — {company_name}"
    safe_customer_name = html.escape(customer_name)
    safe_company_name = html.escape(company_name)
    safe_tier = html.escape(tier)
    amount_line = (
        f"<p>Beløb: <strong>{amount_dkk:,} kr.</strong></p>" if amount_dkk else ""
    )

    html_body = f"""
<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <h2 style="color:#b91c1c;">Betaling mislykkedes</h2>
  <p>Hej {safe_customer_name},</p>
  <p>
    Vi kunne ikke trække betalingen for dit AISelect abonnement
    (<strong>{safe_tier.capitalize()}</strong>) for <strong>{safe_company_name}</strong>.
  </p>
  {amount_line}
  <p>
    Opdater din betalingsmetode via
    <a href="https://aiselect.dk/billing">aiselect.dk/billing</a>
    for at undgå afbrydelse af din adgang.
  </p>
  <p style="color:#6b7280;font-size:13px;">
    Stripe vil automatisk forsøge igen inden for de næste par dage.
  </p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:32px 0;">
  <p style="color:#6b7280;font-size:12px;">
    AISelect &bull; aiselect.dk &bull;
    <a href="mailto:support@aiscore.dk">support@aiscore.dk</a>
  </p>
</body>
</html>
""".strip()

    text_body = (
        f"Hej {customer_name},\n\n"
        f"Vi kunne ikke trække betalingen for dit AISelect abonnement ({tier}, {company_name}).\n"
        + (f"Beløb: {amount_dkk:,} kr.\n" if amount_dkk else "")
        + f"\nOpdater din betalingsmetode: https://aiselect.dk/billing\n\n"
        f"AISelect — support@aiscore.dk"
    )

    await send_email(to=customer_email, subject=subject, html_body=html_body, text_body=text_body)


async def send_password_reset_email(
    customer_email: str,
    reset_url: str,
) -> None:
    """Send a branded AISelect password reset email with a one-hour token link."""
    subject = "Nulstil din AISelect adgangskode"
    safe_reset_url = html.escape(reset_url)

    html_body = f"""
<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1a1a1a;background:#f9fafb;">
  <div style="background:#fff;border-radius:8px;padding:32px;border:1px solid #e5e7eb;">
    <div style="text-align:center;margin-bottom:24px;">
      <span style="font-size:22px;font-weight:bold;color:#1d4ed8;">AISelect</span>
    </div>
    <h2 style="color:#1a1a1a;font-size:20px;margin-top:0;">Nulstil din adgangskode</h2>
    <p style="color:#374151;">
      Vi har modtaget en anmodning om at nulstille adgangskoden til din AISelect-konto.
      Klik på knappen nedenfor for at vælge en ny adgangskode.
    </p>
    <p style="margin:32px 0;text-align:center;">
      <a href="{safe_reset_url}"
         style="background:#1d4ed8;color:#fff;padding:14px 28px;border-radius:6px;
                text-decoration:none;font-size:16px;font-weight:bold;display:inline-block;">
        Nulstil adgangskode
      </a>
    </p>
    <p style="color:#6b7280;font-size:13px;">
      Linket er gyldigt i <strong>1 time</strong>.
      Hvis du ikke har anmodet om en nulstilling, kan du se bort fra denne e-mail —
      din adgangskode forbliver uændret.
    </p>
    <p style="color:#9ca3af;font-size:12px;word-break:break-all;">
      Kan knappen ikke klikkes? Kopiér dette link til din browser:<br>
      {safe_reset_url}
    </p>
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:32px 0;">
    <p style="color:#6b7280;font-size:12px;text-align:center;">
      AISelect &bull; <a href="https://aiselect.dk" style="color:#1d4ed8;">aiselect.dk</a>
      &bull; <a href="mailto:support@aiscore.dk" style="color:#1d4ed8;">support@aiscore.dk</a>
    </p>
  </div>
</body>
</html>
""".strip()

    text_body = (
        "Nulstil din AISelect adgangskode\n\n"
        "Vi har modtaget en anmodning om at nulstille adgangskoden til din konto.\n\n"
        f"Klik her for at vælge en ny adgangskode:\n{reset_url}\n\n"
        "Linket er gyldigt i 1 time.\n\n"
        "Hvis du ikke har anmodet om en nulstilling, kan du se bort fra denne e-mail.\n\n"
        "AISelect — support@aiscore.dk"
    )

    await send_email(to=customer_email, subject=subject, html_body=html_body, text_body=text_body)


async def send_calendly_booking_email(
    company_name: str,
    kontaktperson: str,
    customer_email: str,
    event_uri: str,
    scheduled_at: Optional[str],
    canceled: bool = False,
) -> None:
    """Notify admin when a Calendly meeting is booked or cancelled."""
    settings = get_settings()
    safe_kontaktperson = html.escape(kontaktperson)
    safe_company_name = html.escape(company_name)
    safe_customer_email = html.escape(customer_email)
    safe_event_uri = html.escape(event_uri)

    if canceled:
        subject = f"[AIScore Calendly] Møde aflyst — {company_name}"
        headline = "Møde aflyst"
        body_text = (
            f"<strong>{safe_kontaktperson}</strong> ({safe_company_name}, {safe_customer_email}) "
            f"har aflyst deres Calendly-møde."
        )
    else:
        subject = f"[AIScore Calendly] Nyt møde booket — {company_name}"
        headline = "Nyt møde booket"
        when_line = f"<br><strong>Tidspunkt:</strong> {html.escape(scheduled_at)}" if scheduled_at else ""
        body_text = (
            f"<strong>{safe_kontaktperson}</strong> ({safe_company_name}, {safe_customer_email}) "
            f"har booket et Calendly-møde.{when_line}"
        )

    html_body = f"""
<!DOCTYPE html>
<html lang="da">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <h2 style="color:#1d4ed8;">{headline}</h2>
  <p>{body_text}</p>
  <p style="color:#6b7280;font-size:13px;">
    Calendly event URI: {safe_event_uri}<br>
    AIScore intern system
  </p>
</body>
</html>
""".strip()

    await send_email(to=settings.admin_email, subject=subject, html_body=html_body)
