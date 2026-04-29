"""
Auto-generates company-type-specific pre-qualification questions for AIScore applications.

Flow:
  1. Detect company type from website URL + virksomhedsinfo using OpenAI
  2. Select 3-4 targeted questions from the type-specific framework
  3. Return structured list — caller persists to DB
"""
import json
import structlog
from typing import Optional

log = structlog.get_logger()

COMPANY_TYPES = [
    "webshop",
    "saas",
    "konsulent_bureau",
    "professionel_service_b2c",
    "produktionsvirksomhed_b2b",
    "mediehus_publisher",
    "marketplace_platform",
    "haandvaerk_lokale_serviceerhverv",
    "andet",
]

# Per-type question banks — 3-4 questions per type chosen based on relevance
QUESTION_BANK: dict[str, list[dict]] = {
    "webshop": [
        {"id": "ws_1", "category": "sortiment", "question": "Hvilke produktkategorier sælger I, og hvad er jeres primære prissegment (budget, mid-range, premium)?"},
        {"id": "ws_2", "category": "konkurrence", "question": "Hvem anser I som jeres tre vigtigste konkurrenter online, og hvad adskiller jer fra dem?"},
        {"id": "ws_3", "category": "kanal", "question": "Sælger I udelukkende via egen webshop, eller bruger I også markedspladser som Amazon, Zalando eller lignende?"},
        {"id": "ws_4", "category": "ai_parathed", "question": "Når kunder søger efter produkter som jeres, hvilke søgeord eller beskrivelser forventer I at blive fundet under?"},
    ],
    "saas": [
        {"id": "saas_1", "category": "icp", "question": "Hvem er jeres primære målgruppe (Ideal Customer Profile) — hvilken branche, virksomhedsstørrelse og jobtitel?"},
        {"id": "saas_2", "category": "konkurrence", "question": "Hvilke 2-3 konkurrerende SaaS-produkter møder I oftest i salgsdialogen, og hvad vælger kunderne jer frem for dem for?"},
        {"id": "saas_3", "category": "positionering", "question": "Hvad er det én sætning, I bruger til at forklare værdien af jeres produkt til et nyt lead?"},
        {"id": "saas_4", "category": "ai_parathed", "question": "Bruger jeres potentielle kunder primært Google, LinkedIn eller fagmedier til at finde løsninger som jeres?"},
    ],
    "konsulent_bureau": [
        {"id": "kb_1", "category": "ydelser", "question": "Hvilke konkrete ydelser/specialer leverer I, og inden for hvilke brancher har I flest projekter?"},
        {"id": "kb_2", "category": "konkurrence", "question": "Hvem konkurrerer I typisk med, når I byder på opgaver — andre bureauer, freelancere eller inhouse-teams?"},
        {"id": "kb_3", "category": "positionering", "question": "Hvad er jeres vigtigste differentieringsfaktor — pris, specialisering, hastighed eller noget andet?"},
        {"id": "kb_4", "category": "ai_parathed", "question": "Søger jeres kunder typisk rådgivning via Google, anbefalinger fra netværk eller faglige platforme som LinkedIn?"},
    ],
    "professionel_service_b2c": [
        {"id": "psb2c_1", "category": "ydelser", "question": "Hvilke konkrete services tilbyder I, og hvad er den typiske pris og varighed for en aftale?"},
        {"id": "psb2c_2", "category": "geografi", "question": "Betjener I kunder lokalt, regionalt eller nationalt?"},
        {"id": "psb2c_3", "category": "konkurrence", "question": "Hvem er jeres primære konkurrenter, og hvad gør jer til det bedre valg for kunden?"},
        {"id": "psb2c_4", "category": "ai_parathed", "question": "Bruger jeres kunder primært Google til at finde jer, eller kommer de via anmeldelser, anbefalinger eller sociale medier?"},
    ],
    "produktionsvirksomhed_b2b": [
        {"id": "pv_1", "category": "produkt", "question": "Hvad producerer I konkret, og hvilke industrier/brancher er jeres primære kunder?"},
        {"id": "pv_2", "category": "konkurrence", "question": "Konkurrerer I primært med danske producenter, europæiske eller globale leverandører?"},
        {"id": "pv_3", "category": "differentiering", "question": "Er jeres konkurrencefordel primært pris, kvalitet, leveringstid eller specialisering?"},
        {"id": "pv_4", "category": "ai_parathed", "question": "Indkøbere i jeres målgruppe — søger de aktivt online efter leverandører, eller bygger relationer primært på messer og direkte kontakt?"},
    ],
    "mediehus_publisher": [
        {"id": "mp_1", "category": "indhold", "question": "Hvilke emner/nicher dækker I, og hvem er jeres primære målgruppe (forbrugere, fagfolk, virksomheder)?"},
        {"id": "mp_2", "category": "platform", "question": "Distribuerer I primært via hjemmeside, nyhedsbrev, podcast, sociale medier eller en kombination?"},
        {"id": "mp_3", "category": "konkurrence", "question": "Hvilke andre medier eller platforme konkurrerer I med om jeres målgruppes opmærksomhed?"},
        {"id": "mp_4", "category": "ai_parathed", "question": "Søger jeres målgruppe typisk information via Google, direkte URL-besøg, eller AI-assistenter som ChatGPT og Perplexity?"},
    ],
    "marketplace_platform": [
        {"id": "mktp_1", "category": "model", "question": "Hvem er de to sider af jeres platform (udbydere og efterspørgere), og hvad er jeres primære indtjeningsmodel?"},
        {"id": "mktp_2", "category": "skala", "question": "Hvor mange aktive udbydere og kunder har I, og i hvilke geografier opererer I?"},
        {"id": "mktp_3", "category": "konkurrence", "question": "Hvilke alternative platforme eller metoder bruger kunderne i dag, hvis ikke de bruger jer?"},
        {"id": "mktp_4", "category": "ai_parathed", "question": "Søger jeres slutbrugere typisk via Google eller via søgning direkte på jeres platform?"},
    ],
    "haandvaerk_lokale_serviceerhverv": [
        {"id": "hl_1", "category": "ydelser", "question": "Hvilke håndværksydelser tilbyder I, og er I primært rettet mod private kunder, erhvervskunder eller begge?"},
        {"id": "hl_2", "category": "geografi", "question": "Hvilket geografisk område betjener I, og har I afdelinger eller underentreprenører andre steder?"},
        {"id": "hl_3", "category": "konkurrence", "question": "Konkurrerer I primært med andre lokale håndværksfirmaer, eller oplever I også pres fra større kæder?"},
        {"id": "hl_4", "category": "ai_parathed", "question": "Finder jeres kunder jer primært via Google, anmeldelsesplatforme (Trustpilot, 3byggetilbud) eller direkte anbefalinger?"},
    ],
    "andet": [
        {"id": "gen_1", "category": "forretning", "question": "Hvad er jeres primære produkt eller service, og hvem er jeres vigtigste målgruppe?"},
        {"id": "gen_2", "category": "konkurrence", "question": "Nævn 2-3 af jeres vigtigste konkurrenter og hvad der adskiller jer fra dem."},
        {"id": "gen_3", "category": "salg", "question": "Hvordan finder jeres kunder typisk frem til jer — online søgning, netværk, annoncering eller andet?"},
        {"id": "gen_4", "category": "ai_parathed", "question": "Hvilke søgeord eller spørgsmål forventer I, at potentielle kunder bruger, når de søger efter løsninger som jeres?"},
    ],
}


async def detect_company_type(
    firmanavn: str,
    website: str,
    virksomhedsinfo: str,
    openai_api_key: str,
) -> tuple[str, float]:
    """
    Ask OpenAI to classify the company into one of the defined types.
    Returns (company_type, confidence) — falls back to 'andet' on any error.
    """
    if not openai_api_key:
        return "andet", 0.0

    try:
        import openai as _openai
        client = _openai.AsyncOpenAI(api_key=openai_api_key)

        type_list = "\n".join(f"- {t}" for t in COMPANY_TYPES)
        prompt = f"""Klassificer virksomheden nedenfor i én af disse typer:
{type_list}

Virksomhed: {firmanavn}
Website: {website}
Beskrivelse: {virksomhedsinfo}

Svar KUN med JSON på denne form:
{{"type": "<type>", "confidence": <0.0-1.0>}}

Regler:
- Vælg den type der passer bedst. Brug 'andet' hvis ingen passer godt.
- confidence: 0.9+ = meget sikker, 0.6-0.9 = rimelig sikker, <0.6 = usikker
- Ingen forklaring, kun JSON."""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=100,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        detected_type = data.get("type", "andet")
        confidence = float(data.get("confidence", 0.5))

        if detected_type not in COMPANY_TYPES:
            detected_type = "andet"
        if confidence < 0.55:
            detected_type = "andet"

        return detected_type, confidence

    except Exception as exc:
        log.warning("questions.type_detection_failed", error=str(exc))
        return "andet", 0.0


async def generate_questions(
    firmanavn: str,
    website: str,
    virksomhedsinfo: str,
    openai_api_key: str,
) -> tuple[str, float, list[dict]]:
    """
    Detect company type and return 3-4 targeted pre-qualification questions.

    Returns (detected_type, confidence, questions_list)
    """
    company_type, confidence = await detect_company_type(
        firmanavn=firmanavn,
        website=website,
        virksomhedsinfo=virksomhedsinfo,
        openai_api_key=openai_api_key,
    )

    questions = QUESTION_BANK.get(company_type, QUESTION_BANK["andet"])[:4]

    log.info(
        "questions.generated",
        firmanavn=firmanavn,
        company_type=company_type,
        confidence=confidence,
        question_count=len(questions),
    )

    return company_type, confidence, questions
