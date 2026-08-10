"""Register the focused core CLI command modules."""

from grant_assistant.cli import (
    audit_commands,
    comparison_commands,
    operations_commands,
    report_commands,
)

__all__: list[str] = []

_ = (audit_commands, comparison_commands, operations_commands, report_commands)
