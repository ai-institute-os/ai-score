"""
Renders HTML to PDF bytes using the bundled Puppeteer Node.js script.
Passes HTML via stdin to avoid shell-injection and argument-length limits.
"""
import asyncio
import structlog
from pathlib import Path

log = structlog.get_logger()

_SCRIPT = Path(__file__).parent.parent / "scripts" / "pdf_render.js"


async def render_html_to_pdf(html: str) -> bytes:
    """Render *html* to PDF bytes via Puppeteer. Raises RuntimeError on failure."""
    proc = await asyncio.create_subprocess_exec(
        "node",
        str(_SCRIPT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=html.encode("utf-8"))

    if proc.returncode != 0:
        log.error(
            "pdf_renderer.puppeteer_failed",
            returncode=proc.returncode,
            stderr=stderr.decode("utf-8", errors="replace"),
        )
        raise RuntimeError(
            f"Puppeteer PDF render failed (exit {proc.returncode}): "
            f"{stderr.decode('utf-8', errors='replace')[:500]}"
        )

    log.info("pdf_renderer.done", pdf_bytes=len(stdout))
    return stdout
