"""
Renders HTML to PDF bytes using the bundled Puppeteer Node.js script.
Passes HTML via stdin to avoid shell-injection and argument-length limits.
"""
import asyncio
import os
import shutil
import structlog
from pathlib import Path

log = structlog.get_logger()

_SCRIPT = Path(__file__).parent.parent / "scripts" / "pdf_render.js"

# Candidate Chrome binaries in order of preference (local paperclip fallback last)
_CHROME_CANDIDATES = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/paperclip/.cache/puppeteer/chrome/linux-148.0.7778.97/chrome-linux64/chrome",
]

# Extra libs needed for the locally-extracted Puppeteer Chrome (not needed in Docker/Nix)
_LOCAL_CHROME_LIBS = (
    "/paperclip/chrome-libs/extracted/usr/lib/x86_64-linux-gnu"
    ":/paperclip/chrome-libs/extracted/lib/x86_64-linux-gnu"
)


def _find_chrome() -> str | None:
    """Return Chrome path: env var, then PATH discovery, then known local paths."""
    if path := os.environ.get("PUPPETEER_EXECUTABLE_PATH"):
        return path
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if found := shutil.which(name):
            return found
    for path in _CHROME_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _build_env() -> dict:
    """Build subprocess environment with Chrome path wired up."""
    env = os.environ.copy()
    chrome = _find_chrome()
    if chrome:
        env["PUPPETEER_EXECUTABLE_PATH"] = chrome
        log.info("pdf_renderer.chrome_path", path=chrome)
        # Only the locally-extracted Puppeteer Chrome needs extra LD_LIBRARY_PATH
        if "/paperclip/" in chrome and "chrome-libs" not in env.get("LD_LIBRARY_PATH", ""):
            existing = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{_LOCAL_CHROME_LIBS}:{existing}" if existing else _LOCAL_CHROME_LIBS
    else:
        log.warning("pdf_renderer.no_chrome_found")
    return env


async def render_html_to_pdf(html: str) -> bytes:
    """Render *html* to PDF bytes via Puppeteer. Raises RuntimeError on failure."""
    env = _build_env()
    proc = await asyncio.create_subprocess_exec(
        "node",
        str(_SCRIPT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
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
