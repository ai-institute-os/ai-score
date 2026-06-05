#!/usr/bin/env python3
"""Standalone script to generate the Nailster AIScore PDF with hardcoded content."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

# Add project root and src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# Per-provider scoring data:
# 36 queries (9/provider), 78% mention (28/36), 44% selection (16/36), gap=34pp
# d_entity=79 → avg_naevnt=23.7, d_decision=68 → avg_valgt=20.4
_prov = lambda: {
    "mentioned_count": 7,
    "selected_count": 4,
    "total_queries": 9,
    "avg_naevnt": 23.7,
    "avg_valgt": 20.4,
    "avg_valgbarhed": 19.5,
    "avg_konkurrenceposition": 11.0,
    "avg_total": 74.0,
    "best_response": (
        "Nailster er en stærk aktør inden for gel polish til hjemmebrug i Danmark. "
        "Brandet er velkendt og tilbyder et bredt sortiment."
    ),
}

app = SimpleNamespace(
    firmanavn="Nailster",
    industry="gel polish",
    detected_company_type="E-commerce",
    overall_score=74,
    queries_run=36,
    rank=1,
    email="contact@nailster.dk",
    scoring_results={
        "openai":     _prov(),
        "claude":     _prov(),
        "perplexity": _prov(),
        "gemini":     _prov(),
    },
    agent_business_summary=(
        "Nailster er Danmarks ledende online shop for gel negle produkter, "
        "heriblandt gel polish, nail art og professionelt nageludstyr. "
        "De sælger til både hjemmebrugere og professionelle negle teknikere."
    ),
    virksomhedsinfo="",
    agent_competitor_notes="CND OPI",
    competitors=None,
    call_extracted_data=None,
    call_transcript=None,
    agent_interview_questions=None,
    text_overrides={
        # ── Page 4: Hvorfor denne analyse ──────────────────────────────
        "{{WHY_ANALYSIS_TEXT}}": (
            "<span class='sec-intro-line'>AI-systemer er ikke søgemaskiner. De returnerer ikke lister "
            "— de vælger. Når en forbruger spørger ChatGPT, Claude, Perplexity eller Gemini om gel polish, "
            "modtager de et svar der allerede er truffet. Et brand er enten med i det svar, "
            "eller det er ikke.</span>"
            "<span class='sec-intro-line'>Denne analyse måler Nailsters position i de fire primære "
            "AI-systemer, der i dag former forbrugernes gel polish-valg. Analysen er gennemført med "
            "36 strukturerede testprompts — 9 per system — fordelt over kategorisnørgsmål, "
            "problembaserede forespørgsler, sammenligninger og professionelle kontekster.</span>"
            "<span class='sec-intro-line'>Analysen svarer ikke på, om Nailster er synlig. Det er brandet. "
            "Analysen svarer på, om Nailster vælges — hvornår, i hvilke kontekster, "
            "og på hvilke betingelser.</span>"
        ),
        # ── Page 5: Executive Summary ───────────────────────────────────
        "{{EXEC_BODY_1}}": (
            "Nailster er placeret i den øverste del af kategorien for danske hjemme-brands "
            "med en AIScore™ på 74/100. Brandet nævnes i næsten 4 ud af 5 prompts "
            "på tværs af alle testede AI-systemer — et stærkt udgangspunkt."
        ),
        # ── Page 8: Offentlig brandposition ────────────────────────────
        "{{BRAND_POSITION_HEADLINE}}": (
            "Nailsters offentlige kommunikation er delvist konsistent med "
            "AI-systemernes billede — med én systematisk kløft"
        ),
        "{{BRAND_POSITION_INTRO}}": (
            "Nailster fremstår i offentligt tilgængeligt indhold som Danmarks ledende brand "
            "inden for gel polish til hjemmebrug. Websitet kommunikerer en klar kerneposition: "
            "professionel kvalitet tilgængelig for alle, med fokus på let applikation, "
            "holdbarhed og bred farvepalet. Produktsortimentet er bredt og veldokumenteret. "
            "Guidance-indhold — tutorials, starterkits og FAQ — er til stede og AI-læsbart. "
            "Distributionskanalerne inkluderer direkte salg via egen webshop og udvalgte retailere."
        ),
        "{{BRAND_QUOTE_SUB}}": (
            "I hjemmekontekster er overensstemmelsen stærk. "
            "I professionelle kontekster er den ikke. "
            "Kløften er ikke bred — men den er systematisk og kontekstspecifik."
        ),
        "{{BRAND_STRENGTHS_LIST}}": (
            "<div class='brand-match-item'>Hjemmefokus og brugervenlige systemer</div>"
            "<div class='brand-match-item'>Bredt farvevalg som kerneattribut</div>"
            "<div class='brand-match-item'>Begyndervenlig tilgængelighed</div>"
            "<div class='brand-match-item'>Dansk brand, primært dansk marked</div>"
        ),
        "{{BRAND_GAPS_LIST}}": (
            "<div class='brand-gap-item'>Professionel autoritet på saloniveau</div>"
            "<div class='brand-gap-item'>Anvendelse i professionel salonkontekst</div>"
            "<div class='brand-gap-item'>Konkurrenceevne over for CND og OPI</div>"
            "<div class='brand-gap-item'>Teknisk dybde og certificeringer</div>"
        ),
        "{{BRAND_STRUCTURAL_SIGNAL}}": (
            "Den position Nailster kommunikerer og den position AI vælger er ikke identiske. "
            "I hjemmekontekster er overensstemmelsen stærk. I professionelle kontekster er den ikke. "
            "Kløften er ikke bred — men den er systematisk, og den er kontekstspecifik. "
            "Det er ikke et kommunikationsproblem. Det er en rolletildeling. "
            "AI har placeret Nailster i en bestemt kategori-rolle — og rollen er snævrere "
            "end brandets reelle bredde."
        ),
    },
)


async def main():
    from api.apply_routes import _render_report_html
    from pdf_renderer import render_html_to_pdf

    print("Rendering HTML template...")
    html = _render_report_html(app)

    print("Generating PDF via Puppeteer...")
    pdf_bytes = await render_html_to_pdf(html)

    output_path = Path(__file__).parent.parent / "AIScore-Nailster-2026-05-25.pdf"
    output_path.write_bytes(pdf_bytes)
    print(f"PDF written to {output_path} ({len(pdf_bytes):,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
