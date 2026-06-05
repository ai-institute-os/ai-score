#!/usr/bin/env python3
"""Standalone script to generate the Nailster AIScore PDF with correct data."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

# Add project root and src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# Nailster application data (matches DB record, with corrected industry)
app = SimpleNamespace(
    firmanavn="Nailster A/S",
    industry="Gel polish — Hjemmebrug & Professionelt",
    detected_company_type="E-commerce",
    overall_score=63,
    queries_run=40,
    rank=1,
    email="contact@nailster.dk",
    scoring_results={},
    agent_business_summary=(
        "Nailster er Danmarks ledende online shop for gel negle produkter, "
        "heriblandt gel polish, nail art og professionelt nageludstyr. "
        "De sælger til både hjemmebrugere og professionelle negle teknikere."
    ),
    virksomhedsinfo="",
    agent_competitor_notes="",
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
