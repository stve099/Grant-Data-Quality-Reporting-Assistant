"""Shared fixtures: profiles, synthetic datasets, and row-building helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from grant_assistant.analytics import AnalyticsResult, compute_analytics
from grant_assistant.audit import run_audit
from grant_assistant.configuration import GrantProfile, load_profile
from grant_assistant.datagen import generate_clean_dataset, inject_issues
from grant_assistant.datagen.generator import H
from grant_assistant.env import SKIP_DOTENV_ENV_VAR
from grant_assistant.ingestion import PreparedData, prepare_dataset
from grant_assistant.models import AuditResult

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "configs"

#: Fixed evaluation date so follow-up math never depends on the wall clock.
TODAY = date(2026, 8, 1)


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from the developer's own provider configuration.

    Two leaks to close. First, provider selector vars already exported in the
    shell. Second, and less obvious: both entry points read a real ``.env`` into
    ``os.environ`` for the whole pytest process the moment either is exercised —
    so a developer with a working ``.env`` saw failures that CI never would.

    Setting the documented opt-out covers both, including the Streamlit app,
    whose ``load_environment()`` runs at import and so could never be patched in
    time by name. ``ANTHROPIC_API_KEY`` is cleared here too; tests that want a
    provider set their own values via ``monkeypatch.setenv``.
    """
    monkeypatch.setenv(SKIP_DOTENV_ENV_VAR, "1")
    for var in (
        "GRANT_ASSISTANT_PROVIDER",
        "GRANT_ASSISTANT_MODEL",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)


# A fully valid ACTIVE enrollment in source-file format.
VALID_ACTIVE: dict[str, Any] = {
    H["client_id"]: "C-1",
    H["household_id"]: "H-1",
    H["program"]: "Rapid Re-Housing",
    H["enrollment_date"]: "2024-08-15",
    H["enrollment_status"]: "Active",
    H["exit_date"]: "",
    H["exit_destination"]: "",
    H["household_size"]: 1,
    H["adults"]: 1,
    H["children"]: 0,
    H["age"]: 30,
    H["gender"]: "Female",
    H["race"]: "White",
    H["ethnicity"]: "Non-Hispanic/Non-Latino",
    H["veteran_status"]: "No",
    H["disability_status"]: "No",
    H["entry_income"]: 500,
    H["exit_income"]: "",
    H["assessment_status"]: "Completed",
    H["exit_plan_status"]: "In Progress",
    H["followup_3m"]: "",
    H["followup_6m"]: "",
    H["followup_12m"]: "",
}

# A fully valid EXITED enrollment (all follow-ups completed on time).
VALID_EXITED: dict[str, Any] = {
    **VALID_ACTIVE,
    H["client_id"]: "C-2",
    H["household_id"]: "H-2",
    H["enrollment_status"]: "Exited",
    H["exit_date"]: "2025-01-15",
    H["exit_destination"]: "Rental by client, no subsidy",
    H["exit_income"]: 900,
    H["exit_plan_status"]: "Completed",
    H["followup_3m"]: "2025-04-20",
    H["followup_6m"]: "2025-07-20",
    H["followup_12m"]: "2026-01-20",
}


def make_row(base: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    """Build one source-format row from a template with per-field overrides.

    Overrides use canonical short keys from ``H`` (e.g. ``client_id="C-9"``).
    """
    row = dict(base or VALID_ACTIVE)
    for key, value in overrides.items():
        row[H[key]] = value
    return row


def make_source_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(H.values()))


def fired_rules(audit: AuditResult) -> dict[str, set[str]]:
    """Map rule_id -> set of affected client ids (for concise assertions)."""
    return {i.rule_id: {r.client_id for r in i.records} for i in audit.issues if i.record_count}


@pytest.fixture(scope="session")
def profile() -> GrantProfile:
    return load_profile("housing_stability", CONFIG_DIR)


@pytest.fixture(scope="session")
def rrh_profile() -> GrantProfile:
    return load_profile("rapid_rehousing", CONFIG_DIR)


@pytest.fixture(scope="session")
def clean_df() -> pd.DataFrame:
    return generate_clean_dataset(n_clients=180, seed=11)


@pytest.fixture(scope="session")
def flawed() -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    return inject_issues(generate_clean_dataset(n_clients=180, seed=11), seed=12)


@pytest.fixture(scope="session")
def prepared_clean(clean_df: pd.DataFrame, profile: GrantProfile) -> PreparedData:
    return prepare_dataset(clean_df, profile)


@pytest.fixture(scope="session")
def prepared_flawed(flawed, profile: GrantProfile) -> PreparedData:
    return prepare_dataset(flawed[0], profile)


@pytest.fixture(scope="session")
def audit_clean(prepared_clean: PreparedData, profile: GrantProfile) -> AuditResult:
    return run_audit(prepared_clean, profile, today=TODAY)


@pytest.fixture(scope="session")
def audit_flawed(prepared_flawed: PreparedData, profile: GrantProfile) -> AuditResult:
    return run_audit(prepared_flawed, profile, today=TODAY)


@pytest.fixture(scope="session")
def analytics_clean(prepared_clean: PreparedData, profile: GrantProfile) -> AnalyticsResult:
    return compute_analytics(prepared_clean, profile, as_of=TODAY)


@pytest.fixture(scope="session")
def analytics_flawed(prepared_flawed: PreparedData, profile: GrantProfile) -> AnalyticsResult:
    return compute_analytics(prepared_flawed, profile, as_of=TODAY)


def audit_source_rows(
    rows: list[dict[str, Any]], profile: GrantProfile, today: date = TODAY
) -> AuditResult:
    """Prepare and audit a small hand-built source-format dataset."""
    prepared = prepare_dataset(make_source_df(rows), profile)
    return run_audit(prepared, profile, today=today)
