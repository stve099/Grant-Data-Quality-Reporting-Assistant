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


class ChartBackendError(Exception):
    """Raised only when static chart rendering was explicitly required."""


@lru_cache(maxsize=1)
def chart_backend_available() -> bool:
    """True when static image export works.

    Cached because the import check is the expensive part and the answer cannot
    change within a process.
    """
    try:
        import kaleido  # noqa: F401
    except ImportError:
        logger.debug("kaleido is not installed — Word reports will omit charts.")
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


def require_chart_backend() -> None:
    """Raise with the fix when images are required but unavailable."""
    if not chart_backend_available():
        raise ChartBackendError(f"No static chart backend available. {INSTALL_HINT}")
