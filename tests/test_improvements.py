"""Provider resilience improvements."""

from __future__ import annotations

import asyncio


def test_provider_error_preserves_failure_category():
    from grant_assistant.agents.provider import AIProviderError, AIProviderFailure

    error = AIProviderError.from_exception(
        TimeoutError("slow"), provider="test", operation="complete"
    )

    assert error.failure is AIProviderFailure.TIMEOUT
    assert error.retryable is True
    assert "test complete timed out" in str(error)


def test_provider_authentication_error_is_not_retryable():
    from grant_assistant.agents.provider import AIProviderError, AIProviderFailure

    auth_error = type("AuthenticationError", (Exception,), {})("bad key")
    error = AIProviderError.from_exception(auth_error, provider="test", operation="complete")

    assert error.failure is AIProviderFailure.AUTHENTICATION
    assert error.retryable is False


def test_provider_server_status_is_retryable():
    from grant_assistant.agents.provider import AIProviderError, AIProviderFailure

    server_error = type("InternalServerError", (Exception,), {"status_code": 503})(
        "temporarily unavailable"
    )
    error = AIProviderError.from_exception(server_error, provider="openai", operation="complete")

    assert error.failure is AIProviderFailure.PROVIDER
    assert error.retryable is True


def test_provider_request_timeout_status_is_retryable():
    from grant_assistant.agents.provider import AIProviderError, AIProviderFailure

    timeout_error = type("APIStatusError", (Exception,), {"status_code": 408})("timed out")
    error = AIProviderError.from_exception(
        timeout_error, provider="anthropic", operation="complete"
    )

    assert error.failure is AIProviderFailure.TIMEOUT
    assert error.retryable is True


def test_async_provider_adapter_runs_a_sync_provider():
    class Provider:
        name = "fake"

        def complete(self, system, messages, max_tokens=1500):
            return "ok"

    async def run():
        from grant_assistant.agents.provider import complete_async

        return await complete_async(Provider(), "system", [{"role": "user", "content": "hi"}])

    assert asyncio.run(run()) == "ok"


def test_report_branding_and_section_selection_are_honored(profile, analytics_clean):
    from grant_assistant.reporting import build_report_data, render_html_report

    branded = profile.model_copy(deep=True)
    branded.report.brand_color = "#123456"
    branded.report.brand_dark_color = "#102030"
    branded.report.sections = ["executive_summary", "population"]
    report = build_report_data(analytics_clean, None, branded)

    html = render_html_report(report, include_charts=False)

    assert "--brand: #123456" in html
    assert "--brand-dark: #102030" in html
    assert "Executive Summary" in html
    assert "Population Served" in html
    assert "Income Outcomes" not in html
    assert "Performance Measures" not in html


def test_report_sections_reject_unknown_or_duplicate_names(profile):
    import pytest
    from pydantic import ValidationError

    from grant_assistant.configuration import GrantProfile

    payload = profile.model_dump(mode="python")
    payload["report"]["sections"] = ["outcomes", "outcome"]
    with pytest.raises(ValidationError, match="unknown report sections"):
        GrantProfile.model_validate(payload)

    payload["report"]["sections"] = ["outcomes", "outcomes"]
    with pytest.raises(ValidationError, match="duplicate report sections"):
        GrantProfile.model_validate(payload)


def test_related_dataset_merge_adds_columns_by_canonical_join_key(profile, tmp_path):
    import pandas as pd

    from grant_assistant.ingestion import merge_related_datasets

    primary = pd.DataFrame(
        {
            "Client ID": ["A", "B"],
            "Program Name": ["RRH", "ES"],
            "Entry Date": ["2025-01-01", "2025-01-02"],
        }
    )
    related = pd.DataFrame(
        {
            "Client ID": ["A", "B"],
            "Monthly Income at Exit": ["1000", "1200"],
            "Exit Destination": ["Rental by client, no subsidy", "Emergency shelter"],
        }
    )
    primary_path = tmp_path / "primary.csv"
    related_path = tmp_path / "income.csv"
    primary.to_csv(primary_path, index=False)
    related.to_csv(related_path, index=False)

    merged = merge_related_datasets(primary_path, [related_path], profile)

    assert list(merged["Client ID"]) == ["A", "B"]
    assert list(merged["Monthly Income at Exit"].astype(str)) == ["1000", "1200"]


def test_related_dataset_merge_normalizes_join_key_whitespace(profile, tmp_path):
    import pandas as pd

    from grant_assistant.ingestion import merge_related_datasets

    primary = pd.DataFrame({"Client ID": ["A"], "Program Name": ["RRH"]})
    related = pd.DataFrame({"Client ID": [" A "], "Case Manager": ["One"]})
    primary_path = tmp_path / "primary.csv"
    related_path = tmp_path / "services.csv"
    primary.to_csv(primary_path, index=False)
    related.to_csv(related_path, index=False)

    merged = merge_related_datasets(primary_path, [related_path], profile)

    assert merged.loc[0, "Case Manager"] == "One"
    assert merged.loc[0, "Client ID"] == "A"


def test_related_dataset_merge_rejects_duplicate_join_keys(profile, tmp_path):
    import pandas as pd
    import pytest

    from grant_assistant.ingestion import IngestionError, merge_related_datasets

    primary = pd.DataFrame({"Client ID": ["A"], "Program Name": ["RRH"]})
    related = pd.DataFrame({"Client ID": ["A", "A"], "Monthly Income at Exit": ["1", "2"]})
    primary_path = tmp_path / "primary.csv"
    related_path = tmp_path / "income.csv"
    primary.to_csv(primary_path, index=False)
    related.to_csv(related_path, index=False)

    with pytest.raises(IngestionError, match="duplicate join key"):
        merge_related_datasets(primary_path, [related_path], profile)


def test_related_dataset_merge_rejects_missing_join_keys(profile, tmp_path):
    import pandas as pd
    import pytest

    from grant_assistant.ingestion import IngestionError, merge_related_datasets

    primary = pd.DataFrame({"Client ID": ["A"], "Program Name": ["RRH"]})
    related = pd.DataFrame({"Client ID": ["A", None], "Monthly Income at Exit": ["1", "2"]})
    primary_path = tmp_path / "primary.csv"
    related_path = tmp_path / "income.csv"
    primary.to_csv(primary_path, index=False)
    related.to_csv(related_path, index=False)

    with pytest.raises(IngestionError, match="missing join key"):
        merge_related_datasets(primary_path, [related_path], profile)


def test_profile_rejects_alias_collision_between_programs(profile):
    import pytest
    from pydantic import ValidationError

    from grant_assistant.configuration import GrantProfile

    payload = profile.model_dump()
    payload["programs"][1]["aliases"].append(payload["programs"][0]["aliases"][0])
    with pytest.raises(ValidationError, match=r"alias.*more than one program"):
        GrantProfile.model_validate(payload)


def test_scheduled_audit_email_contains_submission_signal(analytics_clean, audit_clean, profile):
    from grant_assistant.automation import build_audit_email

    message = build_audit_email(profile, audit_clean, analytics_clean, "nightly.csv")

    assert profile.grant_name in message["Subject"]
    assert "Data quality score" in message.get_content()
    assert "Ready for submission: yes" in message.get_content()


def test_send_audit_email_uses_verified_tls_and_smtp_credentials(monkeypatch):
    import ssl

    from grant_assistant.automation import send_audit_email

    calls: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int):
            calls["connection"] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def starttls(self, *, context):
            calls["tls_context"] = context

        def login(self, username: str, password: str):
            calls["login"] = (username, password)

        def send_message(self, message):
            calls["message"] = message

    monkeypatch.setattr("grant_assistant.automation.smtplib.SMTP", FakeSMTP)

    from email.message import EmailMessage

    message = EmailMessage()
    message.set_content("Synthetic audit summary")
    send_audit_email(
        message,
        ["reviewer@example.org"],
        host="smtp.example.org",
        username="mailer",
        password="test-only-password",
        sender="reports@example.org",
    )

    assert calls["connection"] == ("smtp.example.org", 587, 30)
    assert isinstance(calls["tls_context"], ssl.SSLContext)
    assert calls["tls_context"].verify_mode == ssl.CERT_REQUIRED
    assert calls["login"] == ("mailer", "test-only-password")
    assert calls["message"] is message
    assert message["To"] == "reviewer@example.org"
    assert message["From"] == "reports@example.org"


def test_send_audit_email_rejects_credentials_without_tls():
    from email.message import EmailMessage

    import pytest

    from grant_assistant.automation import send_audit_email

    with pytest.raises(ValueError, match="credentials require TLS"):
        send_audit_email(
            EmailMessage(),
            ["reviewer@example.org"],
            host="smtp.example.org",
            username="mailer",
            password="test-only-password",
            sender="reports@example.org",
            use_tls=False,
        )


def test_new_cli_commands_are_registered():
    from typer.testing import CliRunner

    from grant_assistant.cli.main import app

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "merge-datasets" in result.stdout
    assert "scheduled-audit" in result.stdout


def test_html_report_embeds_small_local_logo(profile, analytics_clean, tmp_path):
    from grant_assistant.reporting import build_report_data, render_html_report

    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    branded = profile.model_copy(deep=True)
    branded.report.logo_path = str(logo)

    html = render_html_report(
        build_report_data(analytics_clean, None, branded), include_charts=False
    )

    assert 'src="data:image/png;base64,' in html
    assert 'alt="Organization logo"' in html
