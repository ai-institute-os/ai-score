"""
Generates an AIScore PDF report for mydailychoice.com using fpdf2.
Uses LiberationSans (Unicode-capable) for proper Danish character support.
"""
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from datetime import date
from pathlib import Path

OUTPUT_PATH = Path("/tmp/aiscore_report_mydailychoice.pdf")
FONT_DIR = Path("/tmp/pdf_work/node_modules/pdfjs-dist/standard_fonts")

# Colors (R, G, B)
NAVY        = (15, 31, 61)
ACCENT      = (37, 99, 235)
CHOSEN_FG   = (21, 128, 61)
CHOSEN_BG   = (220, 252, 231)
MENTIONED_FG = (29, 78, 216)
MENTIONED_BG = (219, 234, 254)
NEUTRAL     = (100, 116, 139)
BORDER      = (226, 232, 240)
WHITE       = (255, 255, 255)
TEXT        = (15, 23, 42)
TEXT_MID    = (51, 65, 85)
TEXT_LIGHT  = (100, 116, 139)
WARN_BG     = (254, 249, 195)
WARN_FG     = (120, 53, 15)
INFO_BG     = (219, 234, 254)
INFO_FG     = (29, 78, 216)

ANALYSIS_DATE = date.today().strftime("%-d. %B %Y").replace(
    "January","januar").replace("February","februar").replace(
    "March","marts").replace("April","april").replace(
    "May","maj").replace("June","juni").replace(
    "July","juli").replace("August","august").replace(
    "September","september").replace("October","oktober").replace(
    "November","november").replace("December","december")

PROVIDERS = [
    {"name": "ChatGPT",    "vendor": "OpenAI",       "status": "Nævnt",      "pct": 43,
     "context": "Nævnt som CBD-supplement alternativ (43% af svar)"},
    {"name": "Gemini",     "vendor": "Google",        "status": "Nævnt",      "pct": 31,
     "context": "Nævnt sporadisk; konkurrenter foretrukket"},
    {"name": "Claude",     "vendor": "Anthropic",     "status": "Ikke nævnt", "pct":  8,
     "context": "Meget lav synlighed — sjældent registreret"},
    {"name": "Perplexity", "vendor": "Perplexity AI", "status": "Nævnt",      "pct": 52,
     "context": "Bedst synlig via affiliate-indhold (52%)"},
]

DETAIL_CARDS = [
    {
        "system": "ChatGPT", "vendor": "OpenAI", "status": "Nævnt",
        "quote": (
            '"Der er forskellige produkter til sundhed og velvære — fx My Daily Choice der '
            'sælger HempWorx CBD-olie og kosttilskud. De er anerkendt i direkte-salgs-'
            'segmentet. Til CBD-produkter kan det være relevant at overveje dem, men husk '
            'at sammenligne med andre mærker på markedet."'
        ),
        "query": "Which CBD supplement companies should I consider?",
        "position": "#3 i svar",
    },
    {
        "system": "Gemini", "vendor": "Google", "status": "Nævnt",
        "quote": (
            '"Der er mange muligheder inden for velvære og kosttilskud — Charlotte\'s Web, '
            'CBDistillery og My Daily Choice/HempWorx er alle kendte mærker. CBDistillery '
            'er dog mere veletableret, mens My Daily Choice primært opererer via affiliates '
            'og direkte salg."'
        ),
        "query": "Best wellness supplement brands 2024",
        "position": "#4 i svar",
    },
    {
        "system": "Perplexity", "vendor": "Perplexity AI", "status": "Nævnt",
        "quote": (
            '"My Daily Choice (mydailychoice.com) er et direkte-salgs-selskab grundlagt '
            'af Josh Zwagil i 2014. De er bedst kendte for HempWorx CBD-produkter og har '
            'også brands som Mantra Essential Oils og Stëla Beauty. Selskabet opererer '
            'globalt via et netværk af affiliate-partnere."'
        ),
        "query": "What is mydailychoice.com?",
        "position": "#1 (direkte navnesøgning)",
    },
    {
        "system": "Claude", "vendor": "Anthropic", "status": "Ikke nævnt",
        "quote": (
            "My Daily Choice fremkommer ikke konsistent i Claudes svar ved relevante "
            "søgninger om CBD-supplementer, direkte salg eller wellness. Virksomhedens "
            "navn genkendes sporadisk ved meget specifikke forespørgsler, men fremkommer "
            "ikke som naturlig del af generelle anbefalinger."
        ),
        "query": "Recommended CBD oil brands",
        "position": "Ikke nævnt i 92% af testforespørgsler",
    },
]


class ReportPDF(FPDF):
    def header(self):
        pass

    def footer(self):
        pass

    def c(self, r, g, b):
        self.set_text_color(r, g, b)

    def fc(self, r, g, b):
        self.set_fill_color(r, g, b)

    def dc(self, r, g, b):
        self.set_draw_color(r, g, b)

    def f(self, style="", size=9):
        """Set Liberation Sans font."""
        fmap = {
            "":   "LiberationSans",
            "B":  "LiberationSans-Bold",
            "I":  "LiberationSans-Italic",
            "BI": "LiberationSans-BoldItalic",
        }
        self.set_font(fmap.get(style, "LiberationSans"), size=size)

    def page_header(self, company_short: str):
        self.set_y(10)
        self.f("B", 7)
        self.c(*TEXT_LIGHT)
        self.cell(0, 5, "AIScore · AI-Positionsanalyse", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.f("", 7)
        self.cell(0, 5, f"{company_short} · {ANALYSIS_DATE}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def page_footer(self, page_num: str):
        self.set_y(-12)
        self.f("", 7)
        self.c(*TEXT_LIGHT)
        self.cell(140, 5, "AIScore · Fortroligt", align="L", new_x=XPos.RIGHT)
        self.cell(38, 5, f"Side {page_num}", align="R")

    def eyebrow(self, text: str):
        self.f("B", 7)
        self.c(*ACCENT)
        self.cell(0, 6, text.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def h1(self, text: str, size: int = 14):
        self.f("B", size)
        self.c(*NAVY)
        self.multi_cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def intro(self, text: str):
        self.f("", 9)
        self.c(*TEXT_MID)
        self.multi_cell(0, 5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)

    def status_badge(self, status: str, x: float, y: float):
        w, h = 26, 6
        if "Valgt" in status:
            self.fc(*CHOSEN_BG); self.dc(*CHOSEN_FG); fg = CHOSEN_FG
        elif "Nævnt" in status and "Ikke" not in status:
            self.fc(*MENTIONED_BG); self.dc(*MENTIONED_FG); fg = MENTIONED_FG
        else:
            self.fc(241, 245, 249); self.dc(*NEUTRAL); fg = NEUTRAL
        self.rect(x, y, w, h, style="FD")
        self.set_xy(x, y)
        self.f("B", 6.5)
        self.c(*fg)
        self.cell(w, h, status, align="C")

    def bar(self, pct: int, x: float, y: float, w: float = 55):
        h = 4
        self.fc(226, 232, 240); self.dc(226, 232, 240)
        self.rect(x, y, w, h, style="F")
        fill_w = w * pct / 100
        if pct >= 60:   self.fc(21, 128, 61)
        elif pct >= 30: self.fc(*ACCENT)
        else:           self.fc(*NEUTRAL)
        if fill_w > 0:
            self.rect(x, y, fill_w, h, style="F")
        self.set_xy(x + w + 2, y - 0.5)
        self.f("B", 7)
        self.c(*TEXT)
        self.cell(12, h + 1, f"{pct}%")

    def callout(self, bg, fg, border, title: str, body: str):
        cy = self.get_y()
        self.fc(*bg); self.dc(*border)
        self.rect(16, cy, 178, 18, style="FD")
        self.set_xy(18, cy + 2)
        self.f("B", 8); self.c(*fg)
        self.cell(0, 5, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_x(18)
        self.f("", 7.5); self.c(*fg)
        self.multi_cell(174, 4.5, body, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)


def build_pdf() -> "ReportPDF":
    pdf = ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(16, 18, 16)

    # Register Unicode fonts
    for style, filename in [
        ("LiberationSans",            "LiberationSans-Regular.ttf"),
        ("LiberationSans-Bold",       "LiberationSans-Bold.ttf"),
        ("LiberationSans-Italic",     "LiberationSans-Italic.ttf"),
        ("LiberationSans-BoldItalic", "LiberationSans-BoldItalic.ttf"),
    ]:
        pdf.add_font(style, fname=str(FONT_DIR / filename))

    company       = "My Daily Choice (mydailychoice.com)"
    company_short = "mydailychoice.com"

    # ── COVER ──────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.fc(*NAVY)
    pdf.rect(0, 0, 210, 297, style="F")

    # Decorative circle
    pdf.fc(37, 80, 180)
    pdf.ellipse(140, -20, 110, 110, style="F")

    # Brand
    pdf.set_y(40); pdf.set_x(16)
    pdf.f("B", 11); pdf.c(*WHITE)
    pdf.cell(0, 8, "AIScore", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(16)
    pdf.f("", 8); pdf.c(148, 163, 184)
    pdf.cell(0, 6, "AI-Positionsanalyse", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Title
    pdf.set_y(100); pdf.set_x(16)
    pdf.f("B", 28); pdf.c(*WHITE)
    pdf.multi_cell(140, 13, "AI-Positions-\nanalyse", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5); pdf.set_x(16)
    pdf.f("B", 14); pdf.c(147, 197, 253)
    pdf.cell(0, 8, company_short, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Meta
    pdf.set_y(230); pdf.set_x(16)
    pdf.f("", 8); pdf.c(148, 163, 184)
    pdf.cell(50, 6, "Analysedato"); pdf.cell(80, 6, "Type", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(16)
    pdf.f("B", 8); pdf.c(*WHITE)
    pdf.cell(50, 6, ANALYSIS_DATE); pdf.cell(80, 6, "Fuld AI-synlighedsanalyse", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Demo banner
    pdf.set_y(262); pdf.set_x(16)
    pdf.fc(254, 243, 199); pdf.dc(245, 158, 11)
    pdf.rect(16, 262, 178, 10, style="FD")
    pdf.set_xy(16, 264)
    pdf.f("B", 7); pdf.c(146, 64, 14)
    pdf.cell(178, 6, "DEMO-RAPPORT — Genereret til intern test (Rico) · " + ANALYSIS_DATE, align="C")

    # ── SIDE 2 — OVERBLIK ─────────────────────────────────────────────────
    pdf.add_page()
    pdf.page_header(company_short)
    pdf.set_y(28)

    pdf.eyebrow("Overblik")
    pdf.h1("Jeres AI-position på et øjeblik")
    pdf.intro(
        f"Denne analyse kortlægger, hvordan AI-systemer opfatter og præsenterer "
        f"{company_short} i relevante kontekster. Tallene afspejler AI-synlighed, "
        "ikke søgerangering."
    )

    # Score cards
    card_y = pdf.get_y()
    for i, (num, label, hi) in enumerate([
        ("31 / 100", "Samlet AIScore", True),
        ("4",        "AI-systemer analyseret", False),
        ("28",       "Forespørgsler kørt", False),
    ]):
        cx = 16 + i * 60
        pdf.fc(*(ACCENT if hi else (248, 250, 252)))
        pdf.dc(*BORDER)
        pdf.rect(cx, card_y, 57, 22, style="FD")
        pdf.set_xy(cx, card_y + 3)
        pdf.f("B", 15 if hi else 13)
        pdf.c(*(WHITE if hi else NAVY))
        pdf.cell(57, 9, num, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_x(cx)
        pdf.f("", 7)
        pdf.c(*(WHITE if hi else TEXT_LIGHT))
        pdf.cell(57, 5, label, align="C")

    pdf.set_y(card_y + 28)
    pdf.dc(*BORDER); pdf.line(16, pdf.get_y(), 194, pdf.get_y()); pdf.ln(5)

    pdf.h1("NÆVNT vs. VALGT — sådan læser du rapporten", size=11)
    bx = pdf.get_x(); by = pdf.get_y()
    pdf.status_badge("Valgt", bx, by)
    pdf.status_badge("Nævnt", bx + 30, by)
    pdf.status_badge("Ikke nævnt", bx + 60, by)
    pdf.ln(10)

    pdf.f("", 8.5); pdf.c(*TEXT_MID)
    pdf.multi_cell(0, 5,
        "VALGT: AI-systemet anbefalede aktivt jeres løsning som svar på en konkret forespørgsel.\n"
        "NÆVNT: Systemet nævnte jer i kontekst uden at vælge jer frem for alternativer.\n"
        "IKKE NÆVNT: Ingen registrering i analyseperioden.\n\n"
        "Skellet er afgørende: kun VALGT driver reelle salgsmuligheder.",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    pdf.page_footer("2")

    # ── SIDE 3 — AI-SYSTEMSOVERSIGT ───────────────────────────────────────
    pdf.add_page()
    pdf.page_header(company_short)
    pdf.set_y(28)

    pdf.eyebrow("Systemanalyse")
    pdf.h1("Hvilke AI-systemer ser jer — og hvordan?")
    pdf.intro(
        "Tabellen viser alle analyserede AI-systemer, synlighedsstatus og "
        "perceptionsintensitet (pct. af relevante forespørgsler med registrering)."
    )

    # Table
    th = pdf.get_y()
    col_widths = [32, 30, 26, 62, 28]
    col_labels = ["AI-system", "Udbyder", "Status", "Perception", "Kontekst"]
    pdf.fc(*NAVY); pdf.dc(*BORDER)
    x = 16
    for label, w in zip(col_labels, col_widths):
        pdf.set_xy(x, th)
        pdf.f("B", 7); pdf.c(*WHITE)
        pdf.cell(w, 7, label, fill=True, border=1)
        x += w

    y = th + 7
    for i, p in enumerate(PROVIDERS):
        bg = (255, 255, 255) if i % 2 == 0 else (248, 250, 252)
        x = 16

        # Name
        pdf.set_xy(x, y); pdf.fc(*bg); pdf.dc(*BORDER)
        pdf.f("B", 8); pdf.c(*TEXT)
        pdf.cell(col_widths[0], 10, p["name"], fill=True, border=1)
        x += col_widths[0]

        # Vendor
        pdf.set_xy(x, y); pdf.fc(*bg)
        pdf.f("", 7); pdf.c(*TEXT_LIGHT)
        pdf.cell(col_widths[1], 10, p["vendor"], fill=True, border=1)
        x += col_widths[1]

        # Status
        pdf.set_xy(x, y); pdf.fc(*bg)
        pdf.f("", 7); pdf.c(*TEXT)
        pdf.cell(col_widths[2], 10, p["status"], fill=True, border=1, align="C")
        x += col_widths[2]

        # Bar
        pdf.set_xy(x, y); pdf.fc(*bg)
        pdf.cell(col_widths[3], 10, "", fill=True, border=1)
        pdf.bar(p["pct"], x + 2, y + 3, w=40)
        x += col_widths[3]

        # Context
        pdf.set_xy(x, y); pdf.fc(*bg)
        pdf.f("", 6.5); pdf.c(*TEXT_MID)
        ctx = p["context"]
        if len(ctx) > 30:
            ctx = ctx[:29] + "..."
        pdf.cell(col_widths[4], 10, ctx, fill=True, border=1)

        y += 10

    pdf.set_y(y + 5)
    pdf.callout(
        INFO_BG, INFO_FG, MENTIONED_FG,
        "Hvad er perceptionsintensitet?",
        "Pct. af relevante forespørgsler hvor AI-systemet nævnte/valgte virksomheden. "
        "100% = konsekvent synlig. 0% = ikke registreret."
    )
    pdf.page_footer("3")

    # ── SIDE 4 — DETALJEREDE AI-SVAR ──────────────────────────────────────
    pdf.add_page()
    pdf.page_header(company_short)
    pdf.set_y(28)

    pdf.eyebrow("Perceptionsdetaljer")
    pdf.h1("Hvad siger AI-systemerne præcist?")
    pdf.intro(
        f"Uddrag fra AI-svar der illustrerer, hvordan {company_short} "
        "beskrives i den automatiserede rådgivning."
    )

    for card in DETAIL_CARDS:
        cy = pdf.get_y()
        card_h = 34
        pdf.fc(248, 250, 252); pdf.dc(*BORDER)
        pdf.rect(16, cy, 178, card_h, style="FD")

        # Header
        pdf.set_xy(18, cy + 2)
        pdf.f("B", 9); pdf.c(*TEXT)
        pdf.cell(55, 5, card["system"])
        pdf.f("", 7); pdf.c(*TEXT_LIGHT)
        pdf.cell(40, 5, card["vendor"])
        pdf.status_badge(card["status"], 165, cy + 2)

        pdf.dc(*BORDER); pdf.line(16, cy + 9, 194, cy + 9)

        pdf.set_xy(18, cy + 11)
        pdf.f("I", 7.5); pdf.c(*TEXT_MID)
        pdf.multi_cell(174, 4.5, card["quote"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        meta_y = cy + card_h - 6
        pdf.set_xy(18, meta_y)
        pdf.f("", 6.5); pdf.c(*TEXT_LIGHT)
        pdf.cell(0, 4,
            f'Forespørgsel: "{card["query"][:50]}"  ·  {ANALYSIS_DATE}  ·  {card["position"]}'
        )
        pdf.set_y(cy + card_h + 3)

    pdf.page_footer("4")

    # ── SIDE 5 — STYRKER & SVAGHEDER ──────────────────────────────────────
    pdf.add_page()
    pdf.page_header(company_short)
    pdf.set_y(28)

    pdf.eyebrow("Strukturel analyse")
    pdf.h1("Styrker og svagheder i jeres AI-position")
    pdf.intro(
        "Baseret på mønstre på tværs af alle analyserede AI-systemer og forespørgsler. "
        "Vurdering af hvad AI-systemerne tror om jer — ikke om jeres produkt."
    )

    sw_y = pdf.get_y()
    sw_w, sw_h = 86, 60

    for i, (title, color, items) in enumerate([
        ("Styrker", CHOSEN_FG, [
            "Stærk direkte navne-genkendelse hos Perplexity (52%)",
            "Konsekvent associeret med HempWorx som produkt-brand",
            "Nævnt i CBD-kategorien hos ChatGPT (43%) og Gemini (31%)",
            "Affiliate-netværk genererer citérbart web-indhold til AI",
        ]),
        ("Svagheder", (185, 28, 28), [
            "Ingen VALGT-status — altid alternativ, aldrig primært valg",
            "Claude genkender ikke virksomheden (kun 8% synlighed)",
            "MLM-model associeres negativt i AI-svar om troværdighed",
            "Svag synlighed i europæiske/skandinaviske markeder",
        ]),
    ]):
        cx = 16 + i * (sw_w + 6)
        pdf.fc(248, 250, 252); pdf.dc(*color)
        pdf.rect(cx, sw_y, sw_w, sw_h, style="FD")

        pdf.set_xy(cx + 4, sw_y + 4)
        pdf.f("B", 9); pdf.c(*color)
        pdf.cell(sw_w - 8, 7, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        for item in items:
            pdf.set_x(cx + 4)
            pdf.f("", 7.5); pdf.c(*TEXT_MID)
            pdf.multi_cell(sw_w - 8, 4.5, f"• {item}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1)

    pdf.set_y(sw_y + sw_h + 8)
    pdf.dc(*BORDER); pdf.line(16, pdf.get_y(), 194, pdf.get_y()); pdf.ln(5)

    pdf.callout(
        WARN_BG, WARN_FG, (245, 158, 11),
        "Konkurrentpositionering:",
        "Charlotte's Web og CBDistillery er VALGT i 3-4 ud af 4 AI-systemer i CBD-kategorien. "
        "My Daily Choice's position som 'alternativ' kræver aktiv indsats for at flytte fra "
        "NÆVNT til VALGT."
    )
    pdf.callout(
        INFO_BG, INFO_FG, MENTIONED_FG,
        "Perplexity-mulighed:",
        "Perplexity viser bedst synlighed (52%) via direkte navnesøgninger. "
        "Faktabaseret indhold — produktdata, ingredienslister, tredjeparts-testresultater "
        "— vil styrke AI-citationer markant på tværs af alle systemer."
    )
    pdf.page_footer("5")

    # ── SIDE 6 — ANBEFALINGER ─────────────────────────────────────────────
    pdf.add_page()
    pdf.page_header(company_short)
    pdf.set_y(28)

    pdf.eyebrow("Anbefaling")
    pdf.h1("Hvad gør I nu?")
    pdf.intro(
        "Tre prioriterede handlingsspor rangeret efter potentiel effekt på VALGT-ratio."
    )

    priorities = [
        {
            "label": "PRIORITET 1", "bg": NAVY, "effect": "Høj effekt",
            "title": "Styrk trustworthiness-indhold — bryd MLM-associations-barrieren",
            "body": (
                "Publicér tredjeparts COA-testresultater for HempWorx-produkter som strukturerede "
                "data på hjemmesiden. AI-systemer citerer FDA-compliant, videnskabeligt funderet "
                "indhold langt højere end affiliate-tekst. Tilføj FAQ-sektioner der adresserer "
                '"is My Daily Choice legit?" direkte med faktabaserede svar.'
            ),
        },
        {
            "label": "PRIORITET 2", "bg": (26, 52, 97), "effect": "Middel effekt",
            "title": "Styrk Claude og Gemini via Wikipedia og autoritativt presseindhold",
            "body": (
                "Claude og Gemini trækker tungt på Wikipedia og hvide autoritetskilder. "
                "En faktuel, neutral Wikipedia-artikel om My Daily Choice (korrekte årstal, "
                "grundlæggere og brand-portefølje) vil løfte genkendelsen markant hos begge "
                "systemer. Supplér med presseomtale i anerkendte medier."
            ),
        },
        {
            "label": "PRIORITET 3", "bg": (100, 116, 139), "effect": "Middel effekt",
            "title": "Separér HempWorx-brandet som selvstændig AI-synlig entitet",
            "body": (
                "HempWorx genkendes bedre end \"My Daily Choice\" i CBD-specifikke AI-forespørgsler. "
                "Overvej at give HempWorx.com en mere selvstændig indholdsarkitektur med egne "
                "strukturerede data, skema-markup og produktspecifikationer adskilt fra MLM-framing."
            ),
        },
    ]

    for p in priorities:
        cy = pdf.get_y()
        card_h = 32
        pdf.fc(248, 250, 252); pdf.dc(*BORDER)
        pdf.rect(16, cy, 178, card_h, style="FD")

        # Badge
        pdf.fc(*p["bg"]); pdf.dc(*p["bg"])
        pdf.rect(18, cy + 3, 30, 6, style="F")
        pdf.set_xy(18, cy + 3)
        pdf.f("B", 6.5); pdf.c(*WHITE)
        pdf.cell(30, 6, p["label"], align="C")

        # Title
        pdf.set_xy(52, cy + 3)
        pdf.f("B", 8.5); pdf.c(*TEXT)
        pdf.cell(120, 6, p["title"])

        # Effect
        pdf.set_xy(16, cy + 3)
        pdf.f("", 7); pdf.c(*TEXT_LIGHT)
        pdf.cell(178, 6, p["effect"], align="R")

        pdf.dc(*BORDER); pdf.line(16, cy + 10, 194, cy + 10)

        pdf.set_xy(18, cy + 12)
        pdf.f("", 7.5); pdf.c(*TEXT_MID)
        pdf.multi_cell(174, 4.5, p["body"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_y(cy + card_h + 4)

    pdf.dc(*BORDER); pdf.line(16, pdf.get_y(), 194, pdf.get_y()); pdf.ln(5)

    by = pdf.get_y()
    pdf.set_xy(16, by)
    pdf.f("B", 9); pdf.c(*NAVY)
    pdf.cell(90, 5, "Næste analyse"); pdf.cell(0, 5, "Kontakt", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(16, by + 7)
    pdf.f("", 7.5); pdf.c(*TEXT_MID)
    pdf.multi_cell(85, 4.5,
        "AI-systemers perception ændrer sig løbende. Vi anbefaler kvartalsvise "
        "analyser for at måle effekten af indsatserne.",
        new_x=XPos.RIGHT,
    )
    pdf.set_xy(106, by + 7)
    pdf.f("B", 8.5); pdf.c(*NAVY)
    pdf.cell(88, 5, "InsideAI · AIScore", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(106, by + 13)
    pdf.f("", 8); pdf.c(*TEXT_MID)
    pdf.cell(88, 5, "rapport@aiscore.dk", align="R")

    pdf.page_footer("6")

    return pdf


if __name__ == "__main__":
    print("Genererer AIScore PDF-rapport for mydailychoice.com...")
    pdf = build_pdf()
    pdf.output(str(OUTPUT_PATH))
    size = OUTPUT_PATH.stat().st_size
    print(f"PDF genereret: {OUTPUT_PATH} ({size:,} bytes)")
