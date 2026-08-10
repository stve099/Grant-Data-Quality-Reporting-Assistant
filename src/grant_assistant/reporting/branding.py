"""Shared report branding: profile colors and the optional organization logo.

Branding resolves in one place so it cannot drift between renderers. HTML embeds the
logo as a data URI while Word and PowerPoint insert the same bytes as a picture, and
every renderer reads the same profile colors — a deck can never carry a different
brand than the report it summarizes.
"""

from __future__ import annotations

import logging
from base64 import b64encode
from pathlib import Path

from grant_assistant.reporting.context import ReportData

logger = logging.getLogger(__name__)

#: A logo is a masthead image, not an asset library. Capping it keeps a mis-set
#: ``logo_path`` from inflating every export the profile produces.
MAX_LOGO_BYTES = 2 * 1024 * 1024

LOGO_MIME_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def brand_rgb(report: ReportData, *, dark: bool = True) -> tuple[int, int, int]:
    """Profile brand color as an RGB triple for the binary renderers.

    ``ReportConfig`` validates both colors against a six-digit hex pattern, so the
    slices below cannot fail on a profile that loaded.
    """
    value = report.profile.report.brand_dark_color if dark else report.profile.report.brand_color
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def logo_bytes(report: ReportData) -> tuple[bytes, str] | None:
    """Read the profile logo as ``(bytes, mime)``, or ``None`` when unusable.

    An export missing its logo is still a correct export, so an unreadable, oversized,
    or wrong-format path warns and degrades rather than failing the report.
    """
    path_value = report.profile.report.logo_path
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    mime = LOGO_MIME_TYPES.get(path.suffix.casefold())
    try:
        if mime is None or not path.is_file() or path.stat().st_size > MAX_LOGO_BYTES:
            logger.warning(
                "Skipping report logo %s: use a local PNG/JPEG no larger than 2 MB.", path
            )
            return None
        return path.read_bytes(), mime
    except OSError as exc:
        logger.warning("Skipping report logo %s: %s", path, exc)
        return None


def logo_data_uri(report: ReportData) -> str:
    """The profile logo as an inline data URI, or an empty string when unavailable."""
    resolved = logo_bytes(report)
    if resolved is None:
        return ""
    payload, mime = resolved
    return f"data:{mime};base64,{b64encode(payload).decode('ascii')}"
