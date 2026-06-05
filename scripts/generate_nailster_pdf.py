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
# Provider-specific breakdown: ChatGPT 6/2, Claude 7/4, Perplexity 7/4, Gemini 8/6
def _prov(mentioned: int, selected: int) -> dict:
    return {
        "mentioned_count": mentioned,
        "selected_count": selected,
        "total_queries": 9,
        "avg_naevnt": 23.7,
        "avg_valgt": 20.4,
        "avg_valgbarhed": 19.25,
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
        "openai":     _prov(6, 2),
        "claude":     _prov(7, 4),
        "perplexity": _prov(7, 4),
        "gemini":     _prov(8, 6),
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
        # ── Page 9: AI-Landskabet ───────────────────────────────────────
        "{{AI_LANDSCAPE_HEADLINE}}": (
            "AI-systemer organiserer gel polish i funktionelle roller "
            "&#8212; Nailster ejer hjemme-professionel-positionen, men endnu ikke entydigt"
        ),
        "{{AI_LANDSCAPE_INTRO}}": (
            "AI-systemer organiserer gel polish-kategorien i funktionelle roller. "
            "Følgende rollestruktur er observeret på tværs af analysens 36 testprompts. "
            "Nailster er aktuelt placeret i positionen som hjemme-professionel standard i Danmark "
            "&#8212; meningsfuld og relativt stabil, men ikke fuldt ejet."
        ),
        "{{CATEGORY_ROLE_ROWS}}": (
            "<tr>"
            "<td>Professionel salonstandard</td>"
            "<td>CND, OPI, The GelBottle</td>"
            "<td>Vælges konsistent i salon- og professionelle sammenligninger</td>"
            "</tr>"
            "<tr style='background:#fef3ec; border-left:3px solid #FF6B35;'>"
            "<td><strong style='color:#FF6B35;'>Hjemme-professionel (DK)</strong></td>"
            "<td><strong>Nailster &#9733;</strong></td>"
            "<td>Stærkeste position for dansk hjemmebrug og begyndere</td>"
            "</tr>"
            "<tr>"
            "<td>International hjemme-standard</td>"
            "<td>Gelish, Luminary</td>"
            "<td>Nævnes på tværs af systemer i generelle prompts</td>"
            "</tr>"
            "<tr>"
            "<td>Pris-orienteret</td>"
            "<td>Generiske brands</td>"
            "<td>Nævnes i budget-prompts, ingen konsistent aktør</td>"
            "</tr>"
            "<tr>"
            "<td>Allergi/sensitiv specialist</td>"
            "<td>Niche-brands</td>"
            "<td>Positioner under dannelse &#8212; endnu ikke ejet</td>"
            "</tr>"
        ),
        "{{AI_LANDSCAPE_KEY_OBS}}": (
            "Nailster er det naturlige svar på &ldquo;bedste gel polish til hjemmebrug i Danmark&rdquo; "
            "&#8212; men er det ikke enerådende. Ingen prompt-type producerer konsistent Nailster "
            "som det eneste relevante svar. Så længe andre brands nævnes i samme svar, "
            "deler Nailster salget med dem."
        ),
        # ── Page 10: Modelanalyse ───────────────────────────────────────
        "{{MODEL_ANALYSIS_HEADLINE}}": (
            "Nailster er stærkest i Gemini og svagst i ChatGPT "
            "&#8212; den systemspecifikke variation er en strukturel risikofaktor"
        ),
        "{{CHATGPT_VERDICT}}": "Svagest system",
        "{{CHATGPT_ANALYSIS}}": (
            "ChatGPT demonstrerer en systematisk global bias &#8212; internationale brands "
            "(CND, OPI, The GelBottle) prioriteres i professionelle og sammenligningsprompts, "
            "selv når danskhed er en eksplicit parameter. Nailsters framing er neutral-positiv, "
            "men ikke dominant. I 7 ud af 9 testede prompts gik anbefalingen et andet sted."
        ),
        "{{CLAUDE_VERDICT}}": "Mest nuanceret framing",
        "{{CLAUDE_ANALYSIS}}": (
            "Claude demonstrerer en stærkere forståelse for lokal kontekst end ChatGPT og "
            "forbinder konsistent Nailster med hjemme-professionel kvalitet i dansk sammenhæng. "
            "I professionelle salonprompts vælger Claude internationale standardbrands "
            "&#8212; Nailster er fraværende i den kontekst."
        ),
        "{{PERPLEXITY_VERDICT}}": "Barometer for synlighed",
        "{{PERPLEXITY_ANALYSIS}}": (
            "Perplexity henter primært information fra online-kilder og nævner Nailster "
            "konsistent &#8212; men vælger ikke brandet i professionelle og sammenligningsprompts. "
            "Nailster er synligt i de kilder Perplexity indekserer. Det konverterer ikke til valg "
            "i de prompts der afgør, hvad kunden køber."
        ),
        "{{GEMINI_VERDICT}}": "Stærkeste system",
        "{{GEMINI_ANALYSIS}}": (
            "Gemini demonstrerer det bredeste kendskab til det danske marked og positionerer "
            "Nailster som det naturlige valg for hjemme-manicure i dansk kontekst. Gemini er "
            "Nailsters stærkeste system &#8212; men skaber dermed også risiko for en misvisende "
            "forestilling om samlet AI-stabilitet."
        ),
        # ── Page 11: Strukturelle huller ───────────────────────────────
        "{{STRUCTURAL_GAPS_HEADLINE}}": (
            "Tre tilbagevendende mønstre blokerer Nailsters konvertering "
            "fra omtale til valg &#8212; på tværs af alle AI-systemer"
        ),
        "{{GAP_1_TITLE}}": "Professionel autoritetskløft",
        "{{GAP_1_BODY}}": (
            "I alle fire systemer falder Nailster konsistent ud af AI's primære valg, "
            "når prompten indeholder professionelle markører: &ldquo;salonstandard&rdquo;. "
            "&ldquo;professionel kvalitet&rdquo;. &ldquo;bruges af nagleteknikere&rdquo;.<br>"
            "<strong>AI forbinder Nailster med hjemmebrug &#8212; ikke med professionelle valg.</strong>"
        ),
        "{{GAP_1_CALLOUT}}": (
            "Det er ikke realistisk at erobre den professionelle position fra CND og OPI "
            "&#8212; den kæmpes der ikke om. Men hjemme-professionel-positionen er heller "
            "ikke fuldt konsolideret endnu. Den kan mistes. Og går den tabt, overtages den "
            "af en konkurrent der endnu ikke har sat sig fast."
        ),
        "{{GAP_2_TITLE}}": "System-afhængig stabilitet",
        "{{GAP_2_BODY}}": (
            "Nailsters stærkeste position &#8212; i Google Gemini &#8212; er reel, men kan "
            "ikke oversættes direkte til samlet AI-styrke. Gemini-brugere finder Nailster; "
            "ChatGPT-brugere gør det markant sjældnere. Brandets samlede AI-eksponering er "
            "uforudsigelig og systemafhængig."
        ),
        "{{GAP_2_CALLOUT}}": (
            "Det er et strukturelt hul med direkte konsekvens for salget: Når Nailster "
            "ikke bliver fundet i ChatGPT, går salget til andre. Det kræver en anden type "
            "autoritetssignal."
        ),
        "{{GAP_3_TITLE}}": "Kategori-ejerskab mangler konsolidering",
        "{{GAP_3_BODY}}": (
            "Nailster er det naturlige svar på &ldquo;bedste gel polish til hjemmebrug "
            "i Danmark&rdquo; &#8212; men er det ikke enerådende. Perplexity og Claude "
            "nævner konkurrerende brands i samme kontekst. Der er ingen prompt-type, der "
            "konsistent producerer Nailster som det eneste relevante svar."
        ),
        "{{GAP_3_CALLOUT}}": (
            "Så længe konkurrerende brands nævnes i samme svar som Nailster, er positionen "
            "ikke enerådende. Det er ikke et fremtidigt problem &#8212; det er den aktuelle "
            "tilstand. Den koster salg nu."
        ),
        # ── Page 12: AIScore-opdeling ───────────────────────────────────
        "{{SCORE_DESCRIPTION}}": (
            "74/100 placerer Nailster i den øverste del af kategorien for danske hjemme-brands. "
            "Scoren afspejler reel synlighed og reel autoritet &#8212; men også en position, "
            "der endnu ikke er konsolideret nok til at drive systematisk valg."
        ),
        "{{SCORE_INSIGHTS_HEADLINE}}": "Ubalancen er vigtigere end gennemsnittet",
        "{{SCORE_INSIGHTS_BODY}}": (
            "Decision Relevance (68/100) er den dimension, der koster mest. "
            "Synlighed er etableret &#8212; men den konverterer endnu ikke til valg i den "
            "grad, der er mulig. Entity &amp; Authority (79/100) og Category Relevance (77/100) "
            "er et stærkt fundament. Men et fundament, der ikke automatisk driver salg."
        ),
        "{{CATEGORY_RELEVANCE_SCORE}}": "77",
        "{{CONTEXT_CONSISTENCY_SCORE}}": "71",
        "{{DIM_ENTITY_DESC}}": "AI-systemerne kender og stoler på Nailster",
        "{{DIM_CATEGORY_DESC}}": "Nailster forbindes konsistent med kategorien",
        "{{DIM_COMPETITIVE_DESC}}": "Nailster differentierer, men ejer ikke kategorien",
        "{{DIM_CONTEXT_DESC}}": "Positionen varierer på tværs af systemer",
        "{{DIM_DECISION_DESC}}": "Nailster nævnes, men vælges ikke altid",
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
