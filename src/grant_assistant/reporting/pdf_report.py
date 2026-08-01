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

import logging
import shutil
import subprocess
import tempfile
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


def _find_edge() -> str | None:
    for candidate in _EDGE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return shutil.which("msedge")


def pdf_backend() -> str | None:
    """Name of the available backend ('playwright' or 'edge'), or None."""
    if _playwright_available():
        return "playwright"
    if _find_edge():
        return "edge"
    return None


def _render_with_playwright(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            page.pdf(
                path=str(pdf_path),
                format="Letter",
                print_background=True,
                margin={"top": "0.5in", "bottom": "0.5in", "left": "0.4in", "right": "0.4in"},
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


def write_pdf_report(report: ReportData, path: str | Path) -> Path:
    """Render the grant report to PDF; returns the output path.

    Raises:
        PdfBackendError: when no headless browser backend is available.
    """
    backend = pdf_backend()
    if backend is None:
        raise PdfBackendError(
            "PDF export needs a headless browser. Either install the optional backend "
            "(`uv sync --extra pdf` then `uv run playwright install chromium`) or use "
            "Microsoft Edge (Windows). HTML and Word exports work without any backend."
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html_report(report, offline_charts=True)
    with tempfile.TemporaryDirectory(prefix="grant_pdf_") as tmp:
        html_path = Path(tmp) / "report.html"
        html_path.write_text(html, encoding="utf-8")
        if backend == "playwright":
            _render_with_playwright(html_path, path)
        else:
            _render_with_edge(html_path, path)
    logger.info("Wrote PDF report to %s (backend: %s)", path, backend)
    return path
