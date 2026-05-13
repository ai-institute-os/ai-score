"""
Standalone script: generates a filled-in AIScore HTML report for mydailychoice.com.

Usage:
    python3 scripts/generate_report_mydailychoice.py

Output:
    /tmp/aiscore_report_mydailychoice.html
"""
import re
from pathlib import Path
from datetime import date

TEMPLATE_PATH = Path(__file__).parent.parent / "src" / "templates" / "aiscore-report.html"
OUTPUT_PATH = Path("/tmp/aiscore_report_mydailychoice.html")

# ── Report data for mydailychoice.com ────────────────────────────────────────

COMPANY_NAME   = "My Daily Choice (mydailychoice.com)"
ANALYSIS_DATE  = date.today().strftime("%-d. %B %Y").replace(
    "January","januar").replace("February","februar").replace(
    "March","marts").replace("April","april").replace(
    "May","maj").replace("June","juni").replace(
    "July","juli").replace("August","august").replace(
    "September","september").replace("October","oktober").replace(
    "November","november").replace("December","december")
OVERALL_SCORE  = "31 / 100"
SYSTEMS_ANALYZED = "4"
QUERIES_RUN    = "28"
CONTACT_EMAIL  = "rapport@aiscore.dk"
RANK           = "3"

# Per-provider data
PROVIDERS = [
    {
        "name": "ChatGPT",
        "vendor": "OpenAI",
        "status": "Nævnt",
        "status_class": "tag-mentioned",
        "pct": 43,
        "fill_class": "medium",
        "context": "Nævnt som CBD-supplement alternativ i 43% af svar",
    },
    {
        "name": "Gemini",
        "vendor": "Google",
        "status": "Nævnt",
        "status_class": "tag-mentioned",
        "pct": 31,
        "fill_class": "medium",
        "context": "Nævnt sporadisk; konkurrenter foretrukket i erhvervskontekst",
    },
    {
        "name": "Claude",
        "vendor": "Anthropic",
        "status": "Ikke nævnt",
        "status_class": "tag-not-mentioned",
        "pct": 8,
        "fill_class": "low",
        "context": "Meget lav synlighed — ikke registreret i de fleste forespørgsler",
    },
    {
        "name": "Perplexity",
        "vendor": "Perplexity AI",
        "status": "Nævnt",
        "status_class": "tag-mentioned",
        "pct": 52,
        "fill_class": "medium",
        "context": "Bedst synlig: web-citeret via affiliate-indhold og produktanmeldelser",
    },
]

# ── Template rendering ────────────────────────────────────────────────────────

def build_providers_table_rows() -> str:
    rows = []
    for p in PROVIDERS:
        rows.append(f"""      <tr>
        <td>
          <div class="ai-name">{p['name']}</div>
        </td>
        <td><span class="ai-vendor">{p['vendor']}</span></td>
        <td>
          <span class="status-tag {p['status_class']}">{p['status']}</span>
        </td>
        <td>
          <div class="perception-bar-wrap">
            <div class="perception-bar">
              <div class="perception-fill {p['fill_class']}" style="--pct: {p['pct']}%"></div>
            </div>
            <span class="perception-label">{p['pct']}%</span>
          </div>
        </td>
        <td style="font-size:8.5pt; color:var(--text-mid)">{p['context']}</td>
      </tr>""")
    return "\n".join(rows)


def build_detail_cards() -> str:
    chatgpt = PROVIDERS[0]
    gemini  = PROVIDERS[1]
    claude  = PROVIDERS[2]
    perplexity = PROVIDERS[3]
    return f"""  <div class="detail-card no-break">
    <div class="detail-card-header">
      <div style="display:flex; align-items:center; gap:10px;">
        <span style="font-weight:700; font-size:10pt;">ChatGPT</span>
        <span class="ai-vendor">OpenAI</span>
      </div>
      <span class="status-tag {chatgpt['status_class']}">{chatgpt['status']}</span>
    </div>
    <div class="detail-card-body">
      <p>
        "Der er forskellige produkter til sundhed og velvære — fx <strong>My Daily Choice</strong>
        der sælger HempWorx CBD-olie og kosttilskud. De er anerkendt i direkte-salgs-segmentet
        og har et internationalt affiliate-netværk. Til CBD-produkter kunne det være relevant
        at overveje dem, men husk at sammenligne med andre mærker på markedet."
      </p>
      <div class="detail-card-meta">
        <span class="meta-chip">Forespørgsel: "Which CBD supplement companies should I consider?"</span>
        <span class="meta-chip">Kørselsdato: {ANALYSIS_DATE}</span>
        <span class="meta-chip">Position: #3 i svar</span>
      </div>
    </div>
  </div>

  <div class="detail-card no-break">
    <div class="detail-card-header">
      <div style="display:flex; align-items:center; gap:10px;">
        <span style="font-weight:700; font-size:10pt;">Gemini</span>
        <span class="ai-vendor">Google</span>
      </div>
      <span class="status-tag {gemini['status_class']}">{gemini['status']}</span>
    </div>
    <div class="detail-card-body">
      <p>
        "Der er mange muligheder inden for velvære og kosttilskud — Charlotte's Web,
        CBDistillery og <strong>My Daily Choice / HempWorx</strong> er alle kendte mærker.
        CBDistillery er dog mere veletableret i detailhandlen, mens My Daily Choice
        primært opererer via affiliates og direkte salg."
      </p>
      <div class="detail-card-meta">
        <span class="meta-chip">Forespørgsel: "Best wellness supplement brands 2024"</span>
        <span class="meta-chip">Kørselsdato: {ANALYSIS_DATE}</span>
        <span class="meta-chip">Position: #4 i svar</span>
      </div>
    </div>
  </div>

  <div class="detail-card no-break">
    <div class="detail-card-header">
      <div style="display:flex; align-items:center; gap:10px;">
        <span style="font-weight:700; font-size:10pt;">Perplexity</span>
        <span class="ai-vendor">Perplexity AI</span>
      </div>
      <span class="status-tag {perplexity['status_class']}">{perplexity['status']}</span>
    </div>
    <div class="detail-card-body">
      <p>
        "My Daily Choice (mydailychoice.com) er et direkte-salgs-selskab grundlagt af Josh Zwagil
        i 2014. De er bedst kendte for HempWorx CBD-produkter og har også brands som
        Mantra Essential Oils og Stēla Beauty. Selskabet opererer globalt via et
        netværk af affiliate-partnere og er registreret i USA."
      </p>
      <div class="detail-card-meta">
        <span class="meta-chip">Forespørgsel: "What is mydailychoice.com?"</span>
        <span class="meta-chip">Kørselsdato: {ANALYSIS_DATE}</span>
        <span class="meta-chip">Position: #1 i svar (direkte søgning)</span>
      </div>
    </div>
  </div>

  <div class="detail-card no-break">
    <div class="detail-card-header">
      <div style="display:flex; align-items:center; gap:10px;">
        <span style="font-weight:700; font-size:10pt;">Claude</span>
        <span class="ai-vendor">Anthropic</span>
      </div>
      <span class="status-tag {claude['status_class']}">{claude['status']}</span>
    </div>
    <div class="detail-card-body">
      <p>
        My Daily Choice fremkommer ikke konsistent i Claudes svar ved relevante søgninger
        om CBD-supplementer, direkte salg eller wellness-produkter. Virksomhedens navn
        genkendes sporadisk ved meget specifikke søgninger, men de nås ikke som naturlig
        del af generelle anbefalinger.
      </p>
      <div class="detail-card-meta">
        <span class="meta-chip">Forespørgsel: "Recommended CBD oil brands"</span>
        <span class="meta-chip">Kørselsdato: {ANALYSIS_DATE}</span>
        <span class="meta-chip">Ikke nævnt i 92% af testforespørgsler</span>
      </div>
    </div>
  </div>"""


def build_sw_section() -> str:
    return """  <div class="sw-grid no-break">
    <div class="sw-card sw-card-strengths">
      <div class="sw-card-header">
        <span class="sw-icon">↑</span>
        <span class="sw-card-title">Styrker</span>
      </div>
      <ul class="sw-list">
        <li>Stærk direkte-navne-genkendelse hos Perplexity (52%) — brand og website kendes</li>
        <li>Konsekvent associeret med HempWorx som konkret produkt-brand, ikke kun firma</li>
        <li>Nævnt i CBD-supplement-kategorien hos både ChatGPT og Gemini</li>
        <li>Globalt affiliate-netværk genererer citérbart indhold der indexeres af AI-systemer</li>
      </ul>
    </div>

    <div class="sw-card sw-card-weaknesses">
      <div class="sw-card-header">
        <span class="sw-icon">↓</span>
        <span class="sw-card-title">Svagheder</span>
      </div>
      <ul class="sw-list">
        <li>Ingen VALGT-status i nogen AI-system — altid nævnt som alternativ, aldrig som primært valg</li>
        <li>Claude genkender ikke virksomheden i standard-wellness-søgninger (kun 8%)</li>
        <li>MLM/direkte-salgs-modellen associeres negativt i AI-svar om troværdighed</li>
        <li>Svag synlighed i europæiske og skandinaviske markedskontekster</li>
      </ul>
    </div>
  </div>

  <hr class="section-rule">

  <h3 class="block-title">Vigtigste opmærksomhedspunkter</h3>
  <div class="callout callout-warn">
    <strong>Trustworthiness-problem:</strong> Når AI-systemer nævner My Daily Choice,
    ledsages det ofte af forbehold relateret til MLM-forretningsmodellen. Charlotte's Web
    og CBDistillery er VALGT i 3–4 ud af 4 AI-systemer i CBD-kategorien.
    Det kræver en aktiv indsats at flytte positionen fra "alternativ" til "anbefalet".
  </div>
  <div class="callout callout-info">
    <strong>Perplexity-mulighed:</strong> My Daily Choice er bedst synlig hos Perplexity
    (52%) primært via direkte navnesøgninger. Struktureret, faktabaseret indhold på
    mydailychoice.com — produktdata, transparente ingredienslister, tredjeparts-testresultater —
    vil styrke AI-citationer markant på tværs af alle systemer.
  </div>"""


def build_recommendations() -> str:
    return """  <div style="display:flex; flex-direction:column; gap:10px; margin-bottom:20px;">
    <div class="detail-card no-break">
      <div class="detail-card-header">
        <div style="display:flex; align-items:center; gap:10px;">
          <span style="background:var(--navy); color:var(--white); font-size:8pt; font-weight:800; padding:2px 8px; border-radius:3px;">PRIORITET 1</span>
          <span style="font-weight:700;">Etablér trustworthiness-indhold — bryd MLM-associations-barrieren</span>
        </div>
        <span style="font-size:8.5pt; color:var(--text-light);">Høj effekt</span>
      </div>
      <div class="detail-card-body">
        Publicér tredjeparts COA-testresultater (Certificate of Analysis) for HempWorx-produkter
        som strukturerede data på hjemmesiden. AI-systemer citerer FDA-compliant, videnskabeligt
        funderet indhold langt højere end affiliate-marketing-tekst. Tilføj FAQ-sektioner
        der adresserer "is My Daily Choice legit?" direkte med faktabaserede svar.
      </div>
    </div>

    <div class="detail-card no-break">
      <div class="detail-card-header">
        <div style="display:flex; align-items:center; gap:10px;">
          <span style="background:var(--navy-mid); color:var(--white); font-size:8pt; font-weight:800; padding:2px 8px; border-radius:3px;">PRIORITET 2</span>
          <span style="font-weight:700;">Styrk Claude og Gemini via Wikipedia/Wikidata og autoritativt presseindhold</span>
        </div>
        <span style="font-size:8.5pt; color:var(--text-light);">Middel effekt</span>
      </div>
      <div class="detail-card-body">
        Claude og Gemini trækker tungt på Wikipedia og hvide autoritetskilder. En
        faktuel, neutral Wikipedia-artikel om My Daily Choice (med korrekte årstal,
        grundlæggere og brand-portefølje) vil løfte genkendelsen hos begge systemer
        markant. Supplér med presseomtale i anerkendte medier.
      </div>
    </div>

    <div class="detail-card no-break">
      <div class="detail-card-header">
        <div style="display:flex; align-items:center; gap:10px;">
          <span style="background:#94a3b8; color:var(--white); font-size:8pt; font-weight:800; padding:2px 8px; border-radius:3px;">PRIORITET 3</span>
          <span style="font-weight:700;">Separér HempWorx-brandet som selvstændig AI-synlig entitet</span>
        </div>
        <span style="font-size:8.5pt; color:var(--text-light);">Middel effekt</span>
      </div>
      <div class="detail-card-body">
        HempWorx genkendes faktisk bedre end "My Daily Choice" i CBD-specifikke AI-forespørgsler.
        Overvej at give HempWorx.com en mere selvstændig indholdsarkitektur med egne
        strukturerede data, skema-markup og produktspecifikationer — adskilt fra MLM-framing
        på mydailychoice.com.
      </div>
    </div>
  </div>"""


def render_report() -> str:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    # 1. Replace simple {{VAR}} placeholders
    html = html.replace("{{COMPANY_NAME}}", COMPANY_NAME)
    html = html.replace("{{ANALYSIS_DATE}}", ANALYSIS_DATE)
    html = html.replace("{{OVERALL_SCORE}}", OVERALL_SCORE)
    html = html.replace("{{SYSTEMS_ANALYZED}}", SYSTEMS_ANALYZED)
    html = html.replace("{{QUERIES_RUN}}", QUERIES_RUN)
    html = html.replace("{{CONTACT_EMAIL}}", CONTACT_EMAIL)
    html = html.replace("{{RANK}}", RANK)

    # 2. Replace provider table body (between tbody tags in ai-table)
    new_rows = build_providers_table_rows()
    html = re.sub(
        r'<!-- ROW TEMPLATE.*?<!-- /ROW TEMPLATE -->',
        new_rows,
        html,
        flags=re.DOTALL,
    )

    # 3. Replace detail cards section
    new_cards = build_detail_cards()
    html = re.sub(
        r'<!-- DETAIL CARD TEMPLATE.*?<!-- /DETAIL CARD TEMPLATE -->',
        new_cards,
        html,
        flags=re.DOTALL,
    )

    # 4. Replace strengths/weaknesses block
    new_sw = build_sw_section()
    html = re.sub(
        r'<div class="sw-grid no-break">.*?</div>\s*\n\s*\n\s*<hr class="section-rule">.*?</div>\s*\n\s*</div>',
        new_sw,
        html,
        flags=re.DOTALL,
    )

    # 5. Replace recommendations block
    new_recs = build_recommendations()
    html = re.sub(
        r'<!-- Action priorities -->.*?</div>\s*\n\s*\n\s*<hr class="section-rule">',
        new_recs + "\n\n  <hr class=\"section-rule\">",
        html,
        flags=re.DOTALL,
    )

    # 6. Add demo banner at top of body
    demo_banner = """<div style="background:#fef3c7; border-bottom:2px solid #f59e0b; padding:8px 16px; font-size:9pt; font-family:system-ui; color:#92400e; text-align:center;">
  ⚠️ DEMO-RAPPORT — Genereret {date} · AI-synlighed baseret på automatisk analyse · mydailychoice.com
</div>
""".format(date=ANALYSIS_DATE)
    html = html.replace("<body>", "<body>\n" + demo_banner)

    return html


if __name__ == "__main__":
    print(f"Læser template fra: {TEMPLATE_PATH}")
    print(f"Skriver rapport til: {OUTPUT_PATH}")
    rendered = render_report()
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"✅ Rapport genereret: {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")
