"""Capture README screenshots of the Streamlit app with Playwright.

Usage:
    uv sync --extra pdf                # playwright
    uv run playwright install chromium
    uv run python scripts/capture_screenshots.py

Starts the app with the flawed demo dataset preloaded, walks the key pages,
and writes PNGs into screenshots/.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "screenshots"
PORT = 8599
BASE = f"http://localhost:{PORT}"
DEMO = f"{BASE}/?demo=housing_program_flawed.csv&profile=housing_stability"

#: (sidebar label fragment, output file)
PAGES = [
    ("Upload & Profile", "01_upload_profile.png"),
    ("Audit Dashboard", "02_audit_dashboard.png"),
    ("Issue Explorer", "03_issue_explorer.png"),
    ("Analytics Dashboard", "04_analytics_dashboard.png"),
    ("Analyst Chat", "05_analyst_chat.png"),
    ("Proactive Insights", "06_proactive_insights.png"),
    ("Report Builder", "07_report_builder.png"),
    ("Configuration Help", "08_configuration_help.png"),
]


def wait_for_server(timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with contextlib.suppress(OSError):
            urllib.request.urlopen(f"{BASE}/_stcore/health", timeout=2)
            return
        time.sleep(0.5)
    raise RuntimeError("Streamlit server did not become healthy in time")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/grant_assistant/ui/app.py",
            "--server.port",
            str(PORT),
            "--server.headless",
            "true",
        ],
        cwd=REPO,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="light")
            page.goto(DEMO)
            page.wait_for_selector('[data-testid="stSidebar"]', timeout=30_000)
            page.wait_for_timeout(4_000)  # let the demo pipeline finish
            for label, filename in PAGES:
                target = page.locator('[data-testid="stSidebar"] label', has_text=label).first
                target.click()
                page.wait_for_timeout(3_500)  # charts/tables render
                page.screenshot(path=str(OUT / filename))
                print(f"captured {filename}")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=15)


if __name__ == "__main__":
    main()
