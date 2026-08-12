"""Render Plotly figures to PNG bytes for documents that cannot hold HTML.

The HTML and PDF reports embed live Plotly charts; Word cannot, so it was the
one export that arrived as tables of numbers with no visual. Static rendering
needs kaleido, which ships a browser binary and is therefore optional
(``uv sync --extra charts``).

Absence is not an error. A Word report without charts is still a correct Word
report, so :func:`figure_png` returns ``None`` when no backend is installed and
the caller carries on. Only an explicit request for images should ever fail.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import plotly.graph_objects as go

logger = logging.getLogger(__name__)

#: Rendered at 2x the placement width so the image stays sharp in print.
CHART_WIDTH_PX = 1200
CHART_HEIGHT_PX = 700
#: Placement width in inches, sized to a Word page with 1" margins.
CHART_WIDTH_INCHES = 6.0

INSTALL_HINT = "Install the chart backend with: uv sync --extra charts"

#: kaleido 1.x renders through a browser it downloads separately, so an import
#: that succeeds still cannot produce an image until that download has happened.
BROWSER_HINT = (
    "kaleido is installed but has no browser to render with. Run: uv run plotly_get_chrome"
)


class ChartBackendError(Exception):
    """Raised only when static chart rendering was explicitly required."""


@lru_cache(maxsize=1)
def _kaleido_installed() -> bool:
    try:
        import kaleido  # noqa: F401
    except ImportError:
        logger.debug("kaleido is not installed — Word reports will omit charts.")
        return False
    return True


@lru_cache(maxsize=1)
def chart_backend_available() -> bool:
    """True when static image export actually works.

    Proved by rendering, not by importing: kaleido 1.x drives a browser it
    downloads on a separate command, so the import succeeding says nothing about
    whether an image can be produced. Answering yes on the strength of the import
    left `require_chart_backend` raising the wrong advice and made the chart
    tests fail where they meant to skip.

    Cached because the probe costs a render and the answer cannot change within
    a process.
    """
    if not _kaleido_installed():
        return False
    try:
        import plotly.graph_objects as go

        figure: Any = go.Figure()
        figure.to_image(format="png", width=8, height=8, scale=1)
    except Exception as exc:
        logger.debug("kaleido cannot render: %s", exc)
        return False
    return True


def figure_png(
    figure: go.Figure, width: int = CHART_WIDTH_PX, height: int = CHART_HEIGHT_PX
) -> bytes | None:
    """PNG bytes for a figure, or None when no backend is available.

    A rendering failure is logged and treated as absence: one bad chart must not
    cost the whole report.
    """
    if not chart_backend_available():
        return None
    try:
        fig: Any = figure
        return bytes(fig.to_image(format="png", width=width, height=height, scale=1))
    except Exception as exc:  # pragma: no cover - depends on the backend binary
        logger.warning("Chart could not be rendered as an image: %s", exc)
        return None


def missing_backend_hint() -> str:
    """The advice that fits the actual problem: no kaleido, or no browser for it."""
    return BROWSER_HINT if _kaleido_installed() else INSTALL_HINT


def require_chart_backend() -> None:
    """Raise with the fix when images are required but unavailable."""
    if not chart_backend_available():
        raise ChartBackendError(f"No static chart backend available. {missing_backend_hint()}")
