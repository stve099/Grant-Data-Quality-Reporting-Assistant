"""Audit rule implementations, grouped by what they check.

Every rule is registered with the engine via the :func:`~grant_assistant.audit.engine.rule`
decorator and returns a list of :class:`~grant_assistant.models.AuditIssue`.
Rules read raw values (pre-coercion) when distinguishing "missing" from
"present but invalid".

Importing this package imports every category module, which is what runs the
decorators and populates the registry. A new category module must be added to
the imports below or its rules will never register — the registration test
catches that by asserting the rule count.
"""

from grant_assistant.audit.rules import (
    case_management,
    completeness,
    consistency,
    statistical,
    timeliness,
    uniqueness,
    validity,
)

__all__ = [
    "case_management",
    "completeness",
    "consistency",
    "statistical",
    "timeliness",
    "uniqueness",
    "validity",
]
