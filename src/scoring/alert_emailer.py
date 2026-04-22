"""
Renders the InsideAI alert email template with score change data.
Template variables and design are documented in src/templates/insideai-alert-email.html.
"""

from datetime import datetime
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "insideai-alert-email.html"

_URGENCY_COLORS = {
    "HOJ": "#b91c1c",
    "MIDDEL": "#b45309",
    "LAV": "#1d4ed8",
}


def render_alert_email(
    company_name: str,
    provider: str,
    score_before: float,
    score_after: float,
    delta: float,
    triggered_at: datetime,
    contact_url: str = "#",
    contact_email: str = "alert@insideai.dk",
    unsubscribe_url: str = "#",
) -> str:
    """
    Returns the rendered HTML string for an InsideAI score-change alert email.

    urgency is derived from abs(delta):
      >= 20  → HOJ   (red)
      >= 10  → MIDDEL (amber)
      < 10   → LAV   (blue)
    """
    abs_delta = abs(delta)
    direction = "faldet" if delta < 0 else "steget"

    if abs_delta >= 20:
        urgency = "HOJ"
    elif abs_delta >= 10:
        urgency = "MIDDEL"
    else:
        urgency = "LAV"

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    # Fix urgency badge color (template defaults to HOJ red — replace only first match)
    color = _URGENCY_COLORS[urgency]
    template = template.replace("background:#b91c1c;", f"background:{color};", 1)

    replacements = {
        "{{COMPANY_NAME}}": company_name,
        "{{ALARM_HEADLINE}}": (
            f"Jeres AI-score hos {provider.title()} er {direction} med {abs_delta:.1f} point"
        ),
        "{{ALARM_CONTEXT}}": (
            f"InsideAI har registreret en statistisk signifikant ændring i "
            f"{company_name}s synlighed hos {provider.title()}. "
            f"Scoren er {direction} fra {score_before:.1f} til {score_after:.1f} — "
            f"en ændring på {delta:+.1f} point ift. det rullende 7-dages gennemsnit."
        ),
        "{{ALARM_ACTION}}": (
            "Overvej at analysere de seneste AI-svar og justere jeres content-strategi. "
            "Se den fulde rapport for detaljer om, hvad der har ændret sig i jeres AI-positionering."
        ),
        "{{ALARM_URGENCY}}": urgency,
        "{{ALARM_DATE}}": triggered_at.strftime("%-d. %B %Y, %H:%M"),
        "{{AI_SYSTEM}}": provider.title(),
        "{{CONTACT_URL}}": contact_url,
        "{{CONTACT_EMAIL}}": contact_email,
        "{{UNSUBSCRIBE_URL}}": unsubscribe_url,
    }

    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)

    return template
