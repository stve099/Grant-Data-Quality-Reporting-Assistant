"""Environment bootstrap tests.

The opt-out exists so that importing an entry point — the Streamlit app in
particular, whose loader runs at import time — cannot write a developer's local
``.env`` into ``os.environ`` for the whole test process.
"""

from __future__ import annotations

import os

from grant_assistant.env import SKIP_DOTENV_ENV_VAR, load_environment


def test_skips_when_opt_out_is_set(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GRANT_ASSISTANT_SENTINEL=leaked\n", encoding="utf-8")
    monkeypatch.setenv(SKIP_DOTENV_ENV_VAR, "1")

    assert load_environment(env_file) is False
    assert "GRANT_ASSISTANT_SENTINEL" not in os.environ


def test_loads_when_opt_out_is_absent(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GRANT_ASSISTANT_SENTINEL=loaded\n", encoding="utf-8")
    monkeypatch.delenv(SKIP_DOTENV_ENV_VAR, raising=False)
    monkeypatch.delenv("GRANT_ASSISTANT_SENTINEL", raising=False)

    assert load_environment(env_file) is True
    assert os.environ["GRANT_ASSISTANT_SENTINEL"] == "loaded"


def test_empty_opt_out_value_does_not_skip(monkeypatch, tmp_path):
    """Only a non-empty value opts out; an empty var is not an instruction."""
    env_file = tmp_path / ".env"
    env_file.write_text("GRANT_ASSISTANT_SENTINEL=loaded\n", encoding="utf-8")
    monkeypatch.setenv(SKIP_DOTENV_ENV_VAR, "")
    monkeypatch.delenv("GRANT_ASSISTANT_SENTINEL", raising=False)

    assert load_environment(env_file) is True


def test_existing_environment_wins_over_dotenv(monkeypatch, tmp_path):
    """Injected configuration must never be clobbered by a file in the image."""
    env_file = tmp_path / ".env"
    env_file.write_text("GRANT_ASSISTANT_SENTINEL=from_file\n", encoding="utf-8")
    monkeypatch.delenv(SKIP_DOTENV_ENV_VAR, raising=False)
    monkeypatch.setenv("GRANT_ASSISTANT_SENTINEL", "from_environment")

    load_environment(env_file)
    assert os.environ["GRANT_ASSISTANT_SENTINEL"] == "from_environment"
