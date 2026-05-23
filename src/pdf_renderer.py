"""
Renders HTML to PDF bytes using the bundled Puppeteer Node.js script.
Passes HTML via stdin to avoid shell-injection and argument-length limits.
"""
import asyncio
import os
import structlog
from pathlib import Path

log = structlog.get_logger()

_SCRIPT = Path(__file__).parent.parent / "scripts" / "pdf_render.js"

_CHROME_LIBS = "/paperclip/chrome-libs/extracted/usr/lib/x86_64-linux-gnu:/paperclip/chrome-libs/extracted/lib/x86_64-linux-gnu"
_CHROME_BIN  = "/paperclip/.cache/puppeteer/chrome/linux-148.0.7778.97/chrome-linux64/chrome"


def _build_env() -> dict:
    """Build environment for the Node subprocess with Chrome libs and path wired up."""
    env = os.environ.copy()
    existing_ld = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{_CHROME_LIBS}:{existing_ld}" if existing_ld else _CHROME_LIBS
    if not env.get("PUPPETEER_EXECUTABLE_PATH"):
        env["PUPPETEER_EXECUTABLE_PATH"] = _CHROME_BIN
    return env


async def render_html_to_pdf(html: str) -> bytes:
    """Render *html* to PDF bytes via Puppeteer. Raises RuntimeError on failure."""
    proc = await asyncio.create_subprocess_exec(
        "node",
        str(_SCRIPT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_build_env(),
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
