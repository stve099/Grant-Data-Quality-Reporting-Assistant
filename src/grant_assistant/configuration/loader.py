"""Load and validate grant profile YAML files with helpful error messages."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from grant_assistant.configuration.profile import GrantProfile

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs"


class ProfileValidationError(Exception):
    """Raised when a profile file is missing, unreadable, or invalid."""


def _format_pydantic_error(path: Path, exc: ValidationError) -> str:
    lines = [f"Profile '{path.name}' failed validation with {exc.error_count()} error(s):"]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def load_profile_file(path: str | Path) -> GrantProfile:
    """Load a single grant profile from a YAML file.

    Raises:
        ProfileValidationError: if the file cannot be read or fails validation.
    """
    path = Path(path)
    if not path.exists():
        raise ProfileValidationError(f"Profile file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileValidationError(f"Profile '{path.name}' is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileValidationError(
            f"Profile '{path.name}' must contain a YAML mapping at the top level."
        )
    try:
        profile = GrantProfile.model_validate(raw)
    except ValidationError as exc:
        raise ProfileValidationError(_format_pydantic_error(path, exc)) from exc
    logger.info("Loaded profile '%s' from %s", profile.profile_id, path)
    return profile


def list_profiles(config_dir: str | Path | None = None) -> dict[str, Path]:
    """Map profile_id -> file path for every valid-looking YAML profile in a directory."""
    directory = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    found: dict[str, Path] = {}
    if not directory.exists():
        return found
    for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            profile_id = raw.get("profile_id") if isinstance(raw, dict) else None
        except yaml.YAMLError:
            logger.warning("Skipping unreadable profile file: %s", path)
            continue
        if profile_id:
            found[str(profile_id)] = path
    return found


def load_profile(profile_id: str, config_dir: str | Path | None = None) -> GrantProfile:
    """Load a profile by its ``profile_id`` from the config directory.

    Raises:
        ProfileValidationError: if no profile with that id exists or it is invalid.
    """
    profiles = list_profiles(config_dir)
    if profile_id not in profiles:
        available = ", ".join(sorted(profiles)) or "(none found)"
        raise ProfileValidationError(
            f"No profile with id '{profile_id}'. Available profiles: {available}"
        )
    return load_profile_file(profiles[profile_id])
