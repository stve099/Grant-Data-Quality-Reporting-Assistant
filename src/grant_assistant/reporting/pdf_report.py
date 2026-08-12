"""PDF report generation by printing the HTML report through a headless browser.

Backends, in order of preference:

1. **Playwright Chromium** — install with
   ``uv sync --extra pdf`` then ``uv run playwright install chromium``.
2. **Microsoft Edge** (Windows) — used automatically when installed; no setup.

When neither backend is available, :func:`write_pdf_report` raises a clear
error naming the fix; callers (CLI/UI) surface it as guidance rather than a
crash. Charts are embedded with inline plotly.js so the PDF renders offline.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from grant_assistant.reporting.context import ReportData
from grant_assistant.reporting.html_report import render_html_report

logger = logging.getLogger(__name__)

_EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


class PdfBackendError(Exception):
    """Raised when no PDF rendering backend is available or rendering fails."""


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=1)
def _expected_chromium_revision() -> str | None:
    """The chromium build the installed playwright drives, from its own manifest.

    Read rather than guessed because the pairing is the whole point: a browser
    left behind by an earlier playwright is not a browser this one can launch.
    Returns None if the manifest cannot be read, which is treated as "cannot
    tell" rather than "missing" — see :func:`_playwright_browser_installed`.
    """
    try:
        import playwright

        manifest = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
        entries = json.loads(manifest.read_text(encoding="utf-8"))["browsers"]
    except (ImportError, OSError, ValueError, KeyError):  # pragma: no cover - defensive
        return None
    for entry in entries:
        if entry.get("name") == "chromium":
            revision = entry.get("revision")
            return None if revision is None else str(revision)
    return None  # pragma: no cover - a playwright without chromium


def _playwright_browsers_dir() -> Path:
    """Where playwright keeps downloaded browsers, mirroring its own resolution."""
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if configured == "0":
        import playwright

        return Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers"
    if configured:
        return Path(configured)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    return (Path(cache) if cache else Path.home() / ".cache") / "ms-playwright"


def _playwright_browser_installed() -> bool:
    """Whether the chromium build this playwright expects is actually on disk.

    ``pip install playwright`` brings no browser, and an environment that
    supplies its own may supply the wrong build. Probing playwright itself for
    the answer costs seconds (it starts the driver process), so the directory it
    would look in is checked directly. Both layouts count: a headless launch
    uses the headless shell, but a full chromium is the same download.
    """
    revision = _expected_chromium_revision()
    if revision is None:
        # No manifest to compare against; let the launch itself be the check.
        return True
    root = _playwright_browsers_dir()
    return any(
        (root / f"{name}-{revision}").is_dir() for name in ("chromium", "chromium_headless_shell")
    )


def _find_edge() -> str | None:
    for candidate in _EDGE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return shutil.which("msedge")


def pdf_backend() -> str | None:
    """Name of the available backend ('playwright' or 'edge'), or None.

    Playwright counts only when its browser is installed too. Reporting it
    available on the strength of the import alone turned a missing download into
    a traceback from ``--format all`` and a hard failure in tests that meant to
    skip.
    """
    if _playwright_available() and _playwright_browser_installed():
        return "playwright"
    if _find_edge():
        return "edge"
    return None


def missing_backend_hint() -> str:
    """Why PDF export is unavailable and what fixes it.

    An installed playwright with no browser is a different problem from no
    playwright at all, and "install the extra" is useless advice for the first.
    """
    if _playwright_available() and not _playwright_browser_installed():
        revision = _expected_chromium_revision()
        build = f" (chromium build {revision})" if revision else ""
        return (
            f"Playwright is installed but its browser{build} is not in "
            f"{_playwright_browsers_dir()}. Run `uv run playwright install chromium`. "
            "HTML and Word exports work without it."
        )
    return (
        "PDF export needs a headless browser. Either install the optional backend "
        "(`uv sync --extra pdf` then `uv run playwright install chromium`) or use "
        "Microsoft Edge (Windows). HTML and Word exports work without any backend."
    )


#: Letter (8.5in) minus 0.5in margins = 7.5in of content = 720 CSS px at 96dpi.
#: The page is laid out at exactly this width so Plotly's SVGs — which are
#: sized once at load time and are not re-laid out for printing — match the
#: paper exactly instead of overflowing off the right edge.
PRINT_WIDTH_PX = 720
PAGE_MARGIN = "0.5in"


def _render_with_playwright(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except PlaywrightError as exc:
            # The probe said the browser was there. Reaching here means it is
            # unusable — a partial download, a sandbox restriction, a build the
            # probe could not compare. Degrade like any other missing backend.
            raise PdfBackendError(
                f"The playwright browser could not be launched: {str(exc).splitlines()[0]}. "
                "Run `uv run playwright install chromium` to repair the installation."
            ) from exc
        try:
            page = browser.new_page(viewport={"width": PRINT_WIDTH_PX, "height": 1120})
            page.goto(html_path.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            # Re-fit any chart that sized itself before layout settled.
            page.evaluate(
                """() => {
                    if (!window.Plotly) return;
                    document.querySelectorAll('.js-plotly-plot')
                        .forEach((el) => window.Plotly.Plots.resize(el));
                }"""
            )
            page.wait_for_timeout(400)
            page.pdf(
                path=str(pdf_path),
                format="Letter",
                print_background=True,
                prefer_css_page_size=True,
                margin={
                    "top": PAGE_MARGIN,
                    "bottom": PAGE_MARGIN,
                    "left": PAGE_MARGIN,
                    "right": PAGE_MARGIN,
                },
            )
        finally:
            browser.close()


def _render_with_edge(html_path: Path, pdf_path: Path) -> None:
    edge = _find_edge()
    assert edge is not None
    result = subprocess.run(
        [
            edge,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            # Lay out at the printable width so charts match the paper.
            f"--window-size={PRINT_WIDTH_PX},1120",
            f"--print-to-pdf={pdf_path.resolve()}",
            "--no-pdf-header-footer",
            html_path.resolve().as_uri(),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if not pdf_path.exists():
        raise PdfBackendError(
            f"Edge PDF rendering failed (exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace')[:300]}"
        )


def write_pdf_report(report: ReportData, path: str | Path, template: str = "full") -> Path:
    """Render the grant report to PDF; returns the output path.

    Raises:
        PdfBackendError: when no headless browser backend is available.
    """
    backend = pdf_backend()
    if backend is None:
        raise PdfBackendError(missing_backend_hint())
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html_report(report, offline_charts=True, template=template)
    with tempfile.TemporaryDirectory(prefix="grant_pdf_") as tmp:
        html_path = Path(tmp) / "report.html"
        html_path.write_text(html, encoding="utf-8")
        if backend == "playwright":
            _render_with_playwright(html_path, path)
        else:
            _render_with_edge(html_path, path)
    logger.info("Wrote PDF report to %s (backend: %s)", path, backend)
    return path
