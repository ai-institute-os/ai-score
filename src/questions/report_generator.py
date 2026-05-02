"""
Generates company-specific AIScore report questions from answered interview + company data.

These questions become the scoring criteria for the final AIScore report — each question
targets a specific AI visibility or readiness dimension relevant to that exact company.

Flow:
  1. Answered interview questions (generated_questions with answer fields) + company data
  2. Optional: Perplexity web research on the company's AI presence
  3. GPT-4o generates 8–12 specific, measurable scoring criteria
  4. Caller persists to DB and triggers downstream report generation
"""
import json
import structlog
from typing import Optional

log = structlog.get_logger()

_SYSTEM_PROMPT = """\
Du er ekspert i AI-synlighed og digital tilstedeværelse for danske virksomheder.
Din opgave er at generere præcise, målbare scoringskriterier til en AIScore-rapport.
Kriterierne bruges til at vurdere, hvor godt virksomheden er synlig og findbar via AI-assistenter
(ChatGPT, Gemini, Perplexity, Claude m.fl.) og moderne søgeteknologi.

Svar KUN med et valid JSON-array — ingen forklaringer, ingen markdown-fences, ingen wrapper-objekt.
"""

_USER_PROMPT_TEMPLATE = """\
Virksomhed: {firmanavn}
Website: {website}
Virksomhedstype: {company_type}
Beskrivelse: {virksomhedsinfo}

Besvaret interview:
{interview_qa}

{web_research_section}

Generer {count} virksomhedsspecifikke scoringskriterier til AIScore-rapporten.
Hvert kriterium skal:
- Være direkte relateret til DENNE specifikke virksomhed (brug firmanavn, branche, produkter fra interviewet)
- Måle et konkret aspekt af AI-synlighed, findbarhed eller AI-parathed
- Have en klar scoring-guide (0–10 skala) med eksempler på hvad 0, 5 og 10 konkret indebærer
- Dække forskellige dimensioner (mix af: synlighed i AI-svar, indholdsstruktur, konkurrenceposition, brandkendskab i AI, lokal/global findbarhed, FAQ-dækning, anmeldelser/autoritet)

VIGTIGT — undgå generiske spørgsmål. Eksempel på et DÅRLIGT spørgsmål:
  "Er {firmanavn} synlig i AI-svar ved relevante søgninger?"
Eksempel på et GODT spørgsmål (brug specifikt produkt/service/marked fra interviewet):
  "Nævner ChatGPT {firmanavn} specifikt, når en potentiel kunde spørger om [specifikt produkt eller problem fra interviewet]?"

Scoring-guide skal følge dette format:
  "0: [Firmanavn] nævnes ikke / [konkret negativ indikator]. 5: Nævnes i generiske sammenhænge uden klar anbefaling. 10: [Firmanavn] fremhæves aktivt og specifikt i relevante AI-svar."

Svar med et JSON-array — ingen wrapper, kun arrayet:
[
  {{
    "id": "rq_1",
    "category": "<kategori-nøgleord>",
    "question": "<specifikt scoringsspørgsmål om DENNE virksomhed og dens konkrete produkter/services>",
    "scoring_guide": "<0: [negativ indikator]. 5: [midterindikator]. 10: [positiv indikator].>"
  }},
  ...
]
"""


def _format_interview_qa(questions: list[dict]) -> str:
    lines = []
    for i, q in enumerate(questions, 1):
        question_text = q.get("question", "")
        answer = q.get("answer", "").strip() if q.get("answer") else "(ikke besvaret)"
        lines.append(f"Q{i}: {question_text}\nA{i}: {answer}")
    return "\n\n".join(lines) if lines else "(Ingen interview-svar tilgængelige)"


async def _research_company_web(
    firmanavn: str,
    website: str,
    perplexity_api_key: str,
) -> str:
    """Query Perplexity for current AI visibility data on the company. Returns summary or empty string."""
    if not perplexity_api_key:
        return ""
    try:
        import httpx
        headers = {
            "Authorization": f"Bearer {perplexity_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "sonar",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Hvad ved du om {firmanavn} ({website})? "
                        "Fokuser på: deres produkter/services, konkurrenter, markedsposition i Danmark, "
                        "og om de nævnes i AI-svar ved relevante søgninger. "
                        "Besvar kort på dansk, max 200 ord."
                    ),
                }
            ],
            "max_tokens": 400,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers=headers,
                json=payload,
            )
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        log.warning("report_generator.perplexity_bad_status", status=resp.status_code)
        return ""
    except Exception as exc:
        log.warning("report_generator.perplexity_failed", error=str(exc))
        return ""


async def generate_report_questions(
    firmanavn: str,
    website: str,
    virksomhedsinfo: str,
    company_type: str,
    answered_questions: list[dict],
    openai_api_key: str,
    perplexity_api_key: str = "",
    question_count: int = 10,
) -> list[dict]:
    """
    Generate company-specific scoring criteria for the AIScore report.

    Returns a list of dicts: [{"id", "category", "question", "scoring_guide"}, ...]
    Raises on unrecoverable errors — caller sets report_questions_status='error'.
    """
    if not openai_api_key:
        raise ValueError("openai_api_key is required")

    import openai as _openai

    interview_qa = _format_interview_qa(answered_questions)

    web_summary = await _research_company_web(firmanavn, website, perplexity_api_key)
    web_research_section = (
        f"Offentlig data om virksomheden (web-research):\n{web_summary}"
        if web_summary
        else ""
    )

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        firmanavn=firmanavn,
        website=website,
        company_type=company_type or "ukendt",
        virksomhedsinfo=virksomhedsinfo,
        interview_qa=interview_qa,
        web_research_section=web_research_section,
        count=question_count,
    )

    client = _openai.AsyncOpenAI(api_key=openai_api_key)
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
    )

    raw = response.choices[0].message.content or "[]"

    # GPT-4o with json_object may wrap array in a key — handle both
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        questions = parsed
    elif isinstance(parsed, dict):
        # Find first list value
        questions = next(
            (v for v in parsed.values() if isinstance(v, list)),
            [],
        )
    else:
        questions = []

    # Normalise: ensure id field is present
    result = []
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        result.append({
            "id": q.get("id") or f"rq_{i + 1}",
            "category": q.get("category", ""),
            "question": q.get("question", ""),
            "scoring_guide": q.get("scoring_guide", ""),
        })

    log.info(
        "report_generator.done",
        firmanavn=firmanavn,
        company_type=company_type,
        question_count=len(result),
        had_web_research=bool(web_summary),
    )
    return result
