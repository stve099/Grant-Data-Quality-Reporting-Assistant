"""High-level orchestration shared by the CLI and the Streamlit UI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from grant_assistant.agents import DataAnalystAgent, get_provider
from grant_assistant.analytics import AnalyticsResult, compute_analytics
from grant_assistant.audit import run_audit
from grant_assistant.configuration import GrantProfile, load_profile, load_profile_file
from grant_assistant.history import HistorySummary
from grant_assistant.ingestion import PreparedData, load_dataset, prepare_dataset
from grant_assistant.models import AuditResult

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure structured console logging once per process."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def resolve_profile(profile: str, config_dir: str | Path | None = None) -> GrantProfile:
    """Load a profile by id (from configs/) or by direct file path."""
    path = Path(profile)
    if path.suffix.lower() in {".yaml", ".yml"} and path.exists():
        return load_profile_file(path)
    return load_profile(profile, config_dir)


@dataclass
class PipelineResult:
    """Everything produced by a full audit + analytics run."""

    profile: GrantProfile
    prepared: PreparedData
    audit: AuditResult
    analytics: AnalyticsResult

    def make_agent(
        self, use_ai: bool = True, history: HistorySummary | None = None
    ) -> DataAnalystAgent:
        provider = get_provider() if use_ai else None
        return DataAnalystAgent(
            self.analytics, self.audit, self.profile, provider=provider, history=history
        )


def run_pipeline_on_frame(
    source: pd.DataFrame,
    grant_profile: GrantProfile,
    today: date | None = None,
) -> PipelineResult:
    """Prepare, audit, and analyze an already-loaded source frame.

    Takes the *source* frame — original headers, before mapping — because the
    profile is what decides which headers map and which are dropped. Re-running a
    dataset under a different profile therefore has to start here;
    :attr:`PreparedData.raw` is already mapped and cannot be re-prepared.
    """
    prepared = prepare_dataset(source, grant_profile)
    return PipelineResult(
        profile=grant_profile,
        prepared=prepared,
        audit=run_audit(prepared, grant_profile, today=today),
        analytics=compute_analytics(prepared, grant_profile, as_of=today),
    )


def run_pipeline(
    data_path: str | Path,
    profile: str,
    config_dir: str | Path | None = None,
    today: date | None = None,
) -> PipelineResult:
    """Load, prepare, audit, and analyze a dataset with one call."""
    grant_profile = resolve_profile(profile, config_dir)
    return run_pipeline_on_frame(load_dataset(data_path), grant_profile, today=today)
