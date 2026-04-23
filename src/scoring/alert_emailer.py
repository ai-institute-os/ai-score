"""
Renders the InsideAI alert email template with score change data.

Design rule: alerts must NEVER mention raw scores.
They must express business consequence: selection rate change and estimated revenue impact.

Template variables and design are documented in src/templates/insideai-alert-email.html.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "insideai-alert-email.html"

_URGENCY_COLORS = {
    "HOJ": "#b91c1c",
    "MIDDEL": "#b45309",
    "LAV": "#1d4ed8",
}

# Maximum scoring dimension for valgt (selection context), used for rate conversion
_VALGT_MAX = 30.0


def _selection_rate_description(score_before: float, score_after: float) -> str:
    """
    Converts score delta into a plain-language selection rate description.
    Uses the total score as a proxy for selection frequency.

    Avoids mentioning raw numbers — describes relative change in human terms.
    """
    if score_before <= 0:
        return "sjældnere end tidligere"

    ratio = score_after / score_before

    if ratio <= 0.25:
        return "kun en fjerdedel så ofte som tidligere"
    if ratio <= 0.40:
        return "mindre end halvt så ofte som tidligere"
    if ratio <= 0.60:
        return "cirka halvt så ofte som tidligere"
    if ratio <= 0.75:
        return "betydeligt sjældnere end tidligere"
    if ratio <= 0.90:
        return "noget sjældnere end tidligere"
    if ratio <= 1.10:
        return "på nogenlunde samme niveau som tidligere"
    if ratio <= 1.33:
        return "noget hyppigere end tidligere"
    if ratio <= 1.75:
        return "betydeligt hyppigere end tidligere"
    return "langt hyppigere end tidligere"


def _revenue_impact_text(
    score_before: float,
    score_after: float,
    monthly_revenue_estimate: Optional[float],
) -> str:
    """
    Converts score change to estimated monthly revenue impact.
    Returns empty string if no revenue estimate is configured.
    """
    if not monthly_revenue_estimate or monthly_revenue_estimate <= 0 or score_before <= 0:
        return ""

    share_before = score_before / 100.0
    share_after = score_after / 100.0
    delta_share = share_after - share_before
    revenue_delta = delta_share * monthly_revenue_estimate

    if abs(revenue_delta) < 100:
        return ""

    amount = abs(int(round(revenue_delta / 100) * 100))
    if revenue_delta < 0:
        return f" Det estimeres til et potentielt tab på {amount:,} kr. månedligt.".replace(",", ".")
    return f" Det estimeres at svare til {amount:,} kr. i ekstra omsætning månedligt.".replace(",", ".")


def render_alert_email(
    company_name: str,
    provider: str,
    score_before: float,
    score_after: float,
    delta: float,
    triggered_at: datetime,
    monthly_revenue_estimate: Optional[float] = None,
    contact_url: str = "#",
    contact_email: str = "alert@insideai.dk",
    unsubscribe_url: str = "#",
) -> str:
    """
    Returns the rendered HTML string for an InsideAI score-change alert email.

    Consequence formulation (design rule):
      - NEVER mention raw scores
      - Express change as selection rate shift in plain language
      - Include revenue impact estimate when monthly_revenue_estimate is configured

    urgency is derived from abs(delta):
      >= 20  → HOJ   (red)
      >= 10  → MIDDEL (amber)
      < 10   → LAV   (blue)
    """
    abs_delta = abs(delta)
    direction_verb = "faldet" if delta < 0 else "steget"

    if abs_delta >= 20:
        urgency = "HOJ"
    elif abs_delta >= 10:
        urgency = "MIDDEL"
    else:
        urgency = "LAV"

    selection_desc = _selection_rate_description(score_before, score_after)
    revenue_text = _revenue_impact_text(score_before, score_after, monthly_revenue_estimate)

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    # Fix urgency badge color (template defaults to HOJ red — replace only first match)
    color = _URGENCY_COLORS[urgency]
    template = template.replace("background:#b91c1c;", f"background:{color};", 1)

    replacements = {
        "{{COMPANY_NAME}}": company_name,
        "{{ALARM_HEADLINE}}": (
            f"{company_name} vælges nu {selection_desc} hos {provider.title()}"
        ),
        "{{ALARM_CONTEXT}}": (
            f"InsideAI har registreret en ændring i, hvor ofte {company_name} "
            f"vælges og anbefales af {provider.title()}. "
            f"Synligheden er {direction_verb} — I fremstår nu {selection_desc} i AI-svar."
            f"{revenue_text}"
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
