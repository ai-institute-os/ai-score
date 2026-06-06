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
            "<td>Konsistent valg i professionelle prompts</td>"
            "</tr>"
            "<tr style='background:#f1f5f9; border-left:3px solid #FF6B35;'>"
            "<td><strong style='color:#FF6B35;'>Hjemme-professionel std. (DK)</strong></td>"
            "<td><strong>Nailster &#9733;</strong></td>"
            "<td>St&#230;rkeste position i dansk hjemmebrug</td>"
            "</tr>"
            "<tr>"
            "<td>International hjemme-standard</td>"
            "<td>Gelish, Luminary</td>"
            "<td>N&#230;vnes i generelle prompts</td>"
            "</tr>"
            "<tr>"
            "<td>Pris-orienteret</td>"
            "<td>Generiske brands</td>"
            "<td>N&#230;vnes i budget-prompts</td>"
            "</tr>"
            "<tr>"
            "<td>Allergi/sensitiv specialist</td>"
            "<td>Niche-brands</td>"
            "<td>Position under dannelse, ikke ejet</td>"
            "</tr>"
        ),
        "{{AI_LANDSCAPE_KEY_OBS_TITLE}}": "NAILSTERS ROLLE I AI-KATEGORISERINGEN",
        "{{AI_LANDSCAPE_KEY_OBS}}": (
            "Nailsters position som hjemme-professionel standard i Danmark er meningsfuld. "
            "Den er delvist anerkendt. Den er endnu ikke fuldt ejet &#8212; ingen prompt producerer "
            "konsistent Nailster som det eneste relevante svar i kategorien. "
            "De internationale professionelle akt&#248;rer &#8212; CND, OPI, The GelBottle &#8212; "
            "ejer et andet segment. Problemet er ikke, at Nailster mister til dem. "
            "Problemet er, at overgangen fra hjemme-professionel til professionel i AI&apos;s "
            "kategorisering er skarpere end Nailsters kommunikation antyder."
        ),
        # ── Page 10: Modelanalyse ───────────────────────────────────────
        "{{MODEL_ANALYSIS_HEADLINE}}": (
            "Nailster er stærkest i Gemini og svagst i ChatGPT "
            "&#8212; den systemspecifikke variation er en strukturel risikofaktor"
        ),
        "{{CHATGPT_VERDICT}}": "Svagest system",
        "{{CHATGPT_ANALYSIS}}": (
            "ChatGPT demonstrerer en systematisk global bias: internationale brands prioriteres "
            "i professionelle og sammenligningsprompts, selv n&#229;r danskhed er en eksplicit "
            "parameter i foresp&#248;rgslen. Nailsters framing er neutral-positiv, men ikke dominant. "
            "ChatGPT er det system, hvor Nailsters position er svagest og mest ustabil."
        ),
        "{{CLAUDE_VERDICT}}": "Mest nuanceret framing",
        "{{CLAUDE_ANALYSIS}}": (
            "Claude demonstrerer st&#230;rkere forst&#229;else for lokal kontekst end ChatGPT. "
            "I hjemme- og begynderprompts v&#230;lges Nailster konsistent. "
            "I professionelle salonprompts falder Nailster ud &#8212; Claude er pr&#230;cis "
            "i sin vurdering af, hvad professionelle faktisk bruger."
        ),
        "{{PERPLEXITY_VERDICT}}": "Barometer for synlighed",
        "{{PERPLEXITY_ANALYSIS}}": (
            "Perplexity henter prim&#230;rt information fra online-kilder og n&#230;vner Nailster "
            "konsistent &#8212; men v&#230;lger ikke brandet i professionelle sammenligninger. "
            "Perplexity er et godt barometer for online-synlighed: Nailster er synligt, "
            "men positionen er ikke st&#230;rk nok til at drive aktiv udv&#230;lgelse i alle kontekster."
        ),
        "{{GEMINI_VERDICT}}": "St&#230;rkeste system",
        "{{GEMINI_ANALYSIS}}": (
            "St&#230;rkeste Nailster-position. Gemini demonstrerer det bredeste kendskab til "
            "det danske marked og positionerer Nailster som det naturlige valg for hjemme-manicure "
            "i dansk kontekst. Gemini er Nailsters st&#230;rkeste system &#8212; og er dermed "
            "ogs&#229; det system, der kan skabe en overdreven forestilling om, at AI-positionen "
            "er mere stabil end den reelt er."
        ),
        "{{MODEL_SUMMARY}}": (
            "Nailster er st&#230;rkest positioneret i Gemini, solidt placeret i Claude og Perplexity, "
            "og svagest i ChatGPT. Den systemspecifikke variation er en strukturel risikofaktor: "
            "en st&#230;rk position i &#233;t system maskerer svaghederne i de &#248;vrige "
            "&#8212; og forbrugere er spredt p&#229; alle fire platforme."
        ),
        # ── Page 11: Strukturelle huller ───────────────────────────────
        "{{STRUCTURAL_GAPS_HEADLINE}}": (
            "Tre tilbagevendende mønstre blokerer Nailsters konvertering "
            "fra omtale til valg &#8212; på tværs af alle AI-systemer"
        ),
        "{{GAP_1_TITLE}}": "Professionel autoritetskl&#248;ft",
        "{{GAP_1_BODY}}": (
            "I alle fire systemer falder Nailster ud af AI&#39;s prim&#230;re valg, n&#229;r prompten "
            "indeholder professionelle mark&#248;rer: &ldquo;salonstandard&rdquo;, "
            "&ldquo;professionel kvalitet&rdquo;, &ldquo;bruges af negleteknikere&rdquo;. "
            "Positionen hjemme-professionel aktiverer ikke den dimension, AI knytter til "
            "professionel autoritet."
        ),
        "{{GAP_1_CALLOUT}}": (
            "Det er ikke en fejl i Nailsters kommunikation. Det er en rollebegr&#230;nsning. "
            "AI har placeret Nailster i hjemmekategorien med en pr&#230;cision, der er "
            "sv&#230;rere at flytte end en marketingmessage."
        ),
        "{{GAP_2_TITLE}}": "System-afh&#230;ngig stabilitet",
        "{{GAP_2_BODY}}": (
            "Nailsters st&#230;rkeste position &#8212; i Google Gemini &#8212; er reel, men kan "
            "ikke overs&#230;ttes direkte til samlet AI-styrke. Gemini-brugere finder Nailster "
            "konsistent; ChatGPT-brugere g&#248;r det markant sj&#230;ldnere. "
            "Fordi Nailster ikke har en konsistent position p&#229; tv&#230;rs af alle fire "
            "systemer, er brandets samlede AI-eksponering uforudsigelig."
        ),
        "{{GAP_2_CALLOUT}}": (
            "Det l&#248;ses ikke ved at opdatere websites eller sociale medier. "
            "De to typer systemer v&#230;gter forskellige signaler."
        ),
        "{{GAP_3_TITLE}}": "Kategori-ejerskab ikke konsolideret",
        "{{GAP_3_BODY}}": (
            "Nailster er det naturlige svar p&#229; &ldquo;bedste gel polish til hjemmebrug "
            "i Danmark&rdquo; &#8212; men er det ikke ener&#229;dende. Perplexity og Claude "
            "n&#230;vner konkurrerende brands i den samme kontekst. "
            "Der er ingen prompttype der konsistent producerer Nailster som det eneste "
            "relevante svar."
        ),
        "{{GAP_3_CALLOUT}}": (
            "Kategori-ejerskab kr&#230;ver, at AI-systemerne ikke blot kender brandet &#8212; "
            "de skal forbinde det med kategorien p&#229; en m&#229;de, der g&#248;r andre "
            "akt&#248;rer sekund&#230;re. Den forbindelse er endnu ikke fuldt etableret."
        ),
        # ── Page 12: AIScore-opdeling ───────────────────────────────────
        "{{SCORE_DESCRIPTION}}": (
            "74/100 placerer Nailster i den øverste del af kategorien for danske hjemme-brands. "
            "Scoren afspejler reel synlighed og reel autoritet &#8212; men også en position, "
            "der endnu ikke er konsolideret nok til at drive systematisk valg."
        ),
        "{{SCORE_INSIGHTS_HEADLINE}}": "Ubalancen er vigtigere end gennemsnittet",
        "{{SCORE_INSIGHTS_BODY}}": (
            "Decision Relevance p&#229; 68/100 &#8212; analysens laveste dimension &#8212; "
            "fort&#230;ller, at synlighed ikke har konverteret til valg i den grad, der er mulig. "
            "Entity &amp; Authority p&#229; 79/100 fort&#230;ller, at fundamentet er til stede. "
            "Kl&#248;ften mellem disse to tal er analysens operationelle sp&#230;nding."
        ),
        "{{CATEGORY_RELEVANCE_SCORE}}": "77",
        "{{CONTEXT_CONSISTENCY_SCORE}}": "71",
        "{{DIM_ENTITY_DESC}}": "AI-systemerne kender og stoler på Nailster",
        "{{DIM_CATEGORY_DESC}}": "Nailster forbindes konsistent med kategorien",
        "{{DIM_COMPETITIVE_DESC}}": "Nailster differentierer, men ejer ikke kategorien",
        "{{DIM_CONTEXT_DESC}}": "Positionen varierer på tværs af systemer",
        "{{DIM_DECISION_DESC}}": "Nailster nævnes, men vælges ikke altid",
        # ── Page 9: Observerede AI-beskrivelser ────────────────────────
        "{{AI_DESCRIPTIONS_INTRO}}": (
            "Nedenst&#229;ende er repr&#230;sentative direkte beskrivelser fra de fire testede AI-systemer. "
            "De er ikke redigerede. "
            "Framing-m&#248;nsteret er konsistent: hjemme, begynder, dansk, tilg&#230;ngeligt."
        ),
        "{{AI_DESCRIPTIONS_HEADLINE}}": (
            "Alle fire AI-systemer beskriver Nailster positivt "
            "&#8212; ingen forbinder brandet med professionel autoritet p&#229; saloniveau"
        ),
        "{{CHATGPT_QUOTE}}": (
            "Nailster er et popul&#230;rt dansk brand for gel polish til hjemmebrug. "
            "De tilbyder et bredt udvalg af farver og er kendt for brugervenlige starterkits "
            "til dem, der &#248;nsker at lave gel manicure derhjemme. "
            "Brandet er veletableret p&#229; det danske marked."
        ),
        "{{CLAUDE_QUOTE}}": (
            "Til hjemme-manicure i Danmark er Nailster et af de mest kendte valg "
            "&#8212; de fokuserer specifikt p&#229; at g&#248;re gel-teknologi tilg&#230;ngelig "
            "for ikke-professionelle med komplette startkits og et bredt farveudvalg. "
            "Internationalt er der ogs&#229; brands som CND, OPI og Gelish der bruges meget."
        ),
        "{{GEMINI_QUOTE}}": (
            "For hjemme gel polish i Danmark anbefales Nailster som et solidt dansk valg "
            "&#8212; s&#230;rligt for begyndere og dem der &#248;nsker et professionelt resultat derhjemme. "
            "Nailster har et bredt produktsortiment og er let tilg&#230;ngeligt via webshop "
            "og udvalgte forhandlere."
        ),
        "{{PERPLEXITY_QUOTE}}": (
            "Nailster er et etableret dansk brand inden for gel polish. "
            "Brandet n&#230;vnes konsistent i forbindelse med hjemme-manicure "
            "og er velkendt for kvalitet, farveudvalg og begyndervenlige systemer."
        ),
        "{{AI_DESCRIPTIONS_INTERPRETATION_TITLE}}": "M&#248;nsteret er konsistent",
        "{{AI_DESCRIPTIONS_INTERPRETATION}}": (
            "Alle fire systemer forbinder Nailster med hjemmebrug, begyndervenlighed og det danske marked. "
            "Professionel autoritet er frav&#230;rende i alle fire svar. "
            "Det er ikke et kommunikationsproblem &#8212; det er en rolletildeling. "
            "AI har placeret Nailster i en bestemt kategori-rolle, "
            "og rollen er sn&#230;vrere end brandets reelle bredde."
        ),
        # ── AI-synlighedsmatrix ─────────────────────────────────────────
        "{{MATRIX_HEADLINE}}": (
            "Nailster n&#230;vnes i 78% af alle prompts &#8212; men v&#230;lges kun i 44%. "
            "Den 34-procentpoint kl&#248;ft er analysens mest handlingsrelevante tal"
        ),
        "{{MATRIX_CALLOUT}}": (
            "<strong>Synlighed er ikke det samme som udv&#230;lgelse</strong><br>"
            "Nailster n&#230;vnes i n&#230;sten 4 ud af 5 foresp&#248;rgsler p&#229; tv&#230;rs af alle systemer. "
            "Med en samlet konverteringsrate p&#229; 44% efterlader Nailster mere end halvdelen af sine "
            "synlighedsmomenter uden aktiv udv&#230;lgelse. Kl&#248;ften p&#229; 34 procentpoint er analysens "
            "mest handlingsrelevante tal &#8212; ikke fordi det er det laveste, men fordi det "
            "repr&#230;senterer den mest direkte vej til forbedret AI-position."
        ),
        # ── Page 4: Hvorfor denne analyse ──────────────────────────────
        "{{WHY_ANALYSIS_TEXT}}": (
            "<span class='sec-intro-line'>AI-systemer er ikke søgemaskiner. De returnerer ikke lister "
            "— de vælger. Når en forbruger spørger ChatGPT, Claude, Perplexity eller Gemini om gel polish, "
            "modtager de et svar der allerede er truffet. Et brand er enten med i det svar, "
            "eller det er ikke.</span>"
            "<span class='sec-intro-line'>Denne analyse måler Nailsters position i de fire primære "
            "AI-systemer, der i dag former forbrugernes gel polish-valg. Analysen er gennemført med "
            "36 strukturerede testprompts — 9 per system — fordelt over kategorispørgsmål, "
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
