#!/usr/bin/env python3
"""Standalone script to generate a sample AIScore PDF with dummy data."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

# Add project root and src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# Dummy per-provider scoring data — illustrative example values
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
        "Eksempel Virksomhed er en stærk aktør i sin kategori. "
        "Brandet er velkendt og tilbyder et bredt sortiment."
    ),
}

app = SimpleNamespace(
    firmanavn="Eksempel Virksomhed A/S",
    industry="gel polish",
    detected_company_type="E-commerce",
    overall_score=74,
    queries_run=36,
    rank=1,
    email="kontakt@eksempel.dk",
    scoring_results={
        "openai":     _prov(),
        "claude":     _prov(),
        "perplexity": _prov(),
        "gemini":     _prov(),
    },
    agent_business_summary=(
        "Eksempel Virksomhed A/S er en dansk online shop inden for gel polish "
        "og negle produkter. De sælger til både hjemmebrugere og professionelle."
    ),
    virksomhedsinfo="",
    agent_competitor_notes="Konkurrent1 Konkurrent2",
    competitors=None,
    call_extracted_data=None,
    call_transcript=None,
    agent_interview_questions=None,
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
