"""One-shot scheduled audit workflow and optional SMTP notification.

The application intentionally does not run its own long-lived scheduler. Operators invoke
``scheduled-audit`` from Windows Task Scheduler, cron, or their existing orchestrator; each
invocation audits, records history, writes a report, and can send one summary email.
"""

from __future__ import annotations

import copy
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from grant_assistant.analytics import AnalyticsResult
from grant_assistant.configuration import GrantProfile
from grant_assistant.history import load_history_summary, record_run
from grant_assistant.models import AuditResult
from grant_assistant.reporting import build_report_data, write_html_report
from grant_assistant.workflow import PipelineResult, run_pipeline

#: Values that disable TLS. Anything else keeps it on, including a typo — the
#: failure mode of an unrecognized value must be "still encrypted".
_TLS_OFF = frozenset({"false", "0", "no", "off"})


def _tls_enabled(raw: str) -> bool:
    return raw.strip().casefold() not in _TLS_OFF


@dataclass(frozen=True)
class ScheduledAuditResult:
    """Artifacts and status produced by one scheduler invocation."""

    pipeline: PipelineResult
    run_id: int
    report_path: Path
    email_sent: bool


def build_audit_email(
    profile: GrantProfile,
    audit: AuditResult,
    analytics: AnalyticsResult,
    source: str,
) -> EmailMessage:
    """Build the plain-text summary sent after an automated run."""
    ready = not audit.blocking_issues
    below_target = [measure.name for measure in analytics.measures if measure.met is False]
    lines = [
        f"Grant: {profile.grant_name}",
        f"Source: {source}",
        f"Data quality score: {audit.overall_score:.1f} ({audit.grade})",
        f"Findings: {audit.total_findings}",
        f"Blocking issue types: {len(audit.blocking_issues)}",
        f"Ready for submission: {'yes' if ready else 'no'}",
        f"Measures below target: {', '.join(below_target) if below_target else 'none'}",
    ]
    message = EmailMessage()
    message["Subject"] = (
        f"{profile.grant_name} scheduled audit: {audit.overall_score:.1f} {audit.grade}"
    )
    message.set_content("\n".join(lines) + "\n")
    return message


def send_audit_email(
    message: EmailMessage,
    recipients: list[str],
    *,
    host: str,
    port: int = 587,
    username: str = "",
    password: str = "",
    sender: str,
    use_tls: bool = True,
) -> None:
    """Send one summary through an operator-supplied SMTP relay.

    The caller's message is not modified: assigning headers in place would append a
    second From/To on a message sent twice, which is exactly what a retrying
    scheduler does.
    """
    if not recipients:
        raise ValueError("At least one email recipient is required.")
    if username and not use_tls:
        raise ValueError("SMTP credentials require TLS.")
    outgoing = copy.deepcopy(message)
    del outgoing["From"]
    del outgoing["To"]
    outgoing["From"] = sender
    outgoing["To"] = ", ".join(recipients)
    with smtplib.SMTP(host, port, timeout=30) as client:
        if use_tls:
            client.starttls(context=ssl.create_default_context())
        if username:
            client.login(username, password)
        client.send_message(outgoing)


def run_scheduled_audit(
    data_file: str | Path,
    profile: str,
    *,
    output_dir: str | Path = "output/scheduled",
    db_path: str | Path = "output/history.db",
    label: str = "scheduled",
    recipients: list[str] | None = None,
    config_dir: str | Path | None = None,
    dry_run: bool = False,
) -> ScheduledAuditResult:
    """Run, persist, report, and optionally notify for one scheduled invocation.

    ``dry_run`` still validates the SMTP configuration and builds the message, but
    connects to nothing. Verifying a relay setup should not require mailing a real
    person, which is the only way an operator could previously test this.
    """
    result = run_pipeline(data_file, profile, config_dir)
    # Read the history before writing this run into it. A scheduled audit is the
    # path that accumulates history in the first place, so its own report is the
    # one that most needs the trend — and the run being recorded now is the
    # current audit, not an observation preceding it.
    history = load_history_summary(db_path, result.profile.profile_id, result.audit)
    run_id = record_run(
        result.profile,
        result.audit,
        result.analytics,
        db_path,
        label=label,
        source=str(data_file),
    )
    output = Path(output_dir)
    report_path = output / f"{result.profile.profile_id}-run-{run_id}.html"
    report = build_report_data(result.analytics, result.audit, result.profile, history=history)
    write_html_report(report, report_path, offline_charts=True)

    email_sent = False
    if recipients:
        host = os.environ.get("GRANT_ASSISTANT_SMTP_HOST", "").strip()
        sender = os.environ.get("GRANT_ASSISTANT_SMTP_FROM", "").strip()
        if not host or not sender:
            raise ValueError(
                "Email recipients were supplied, but GRANT_ASSISTANT_SMTP_HOST and "
                "GRANT_ASSISTANT_SMTP_FROM are not configured."
            )
        message = build_audit_email(result.profile, result.audit, result.analytics, str(data_file))
        username = os.environ.get("GRANT_ASSISTANT_SMTP_USERNAME", "")
        use_tls = _tls_enabled(os.environ.get("GRANT_ASSISTANT_SMTP_TLS", "true"))
        if dry_run:
            # Same precondition the real send enforces, so a dry run cannot pass
            # against a configuration that would be rejected in production.
            if username and not use_tls:
                raise ValueError("SMTP credentials require TLS.")
        else:
            send_audit_email(
                message,
                recipients,
                host=host,
                port=int(os.environ.get("GRANT_ASSISTANT_SMTP_PORT", "587")),
                username=username,
                password=os.environ.get("GRANT_ASSISTANT_SMTP_PASSWORD", ""),
                sender=sender,
                use_tls=use_tls,
            )
            email_sent = True

    return ScheduledAuditResult(result, run_id, report_path, email_sent)
