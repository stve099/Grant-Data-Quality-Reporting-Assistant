"""Draft a grant profile from a sample extract.

Onboarding a funder means hand-writing a profile: mapping every source header to
a canonical field, listing each program and its aliases, transcribing controlled
vocabularies. It is an hour of tedious work with a typo in it, and it is the
main thing standing between "config-only onboarding" as a claim and as a fact.

Most of that can be read off the file. Headers map by normalized comparison and
by fuzzy similarity; programs and controlled values are read from the data;
reporting period is inferred from the date range present.

The output is explicitly a *draft*. Every inference is annotated with what it
was based on, low-confidence guesses are commented out rather than silently
applied, and unmapped columns are listed so nothing is quietly dropped. A
generator that produced a confident-looking wrong profile would cost more time
than writing one by hand.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

from grant_assistant import schema

logger = logging.getLogger(__name__)

#: Similarity above which a header is offered as a mapping, and above which it
#: is applied rather than left commented out.
SUGGEST_THRESHOLD = 0.62
CONFIDENT_THRESHOLD = 0.85

#: Columns whose distinct values are worth transcribing as a vocabulary. Beyond
#: this many distinct values it is free text, not a controlled list.
MAX_VOCABULARY_SIZE = 25

#: Fields the audit needs to do anything useful. A funder may require more,
#: which is why the generated file lists them for review rather than assuming
#: this set is complete.
DEFAULT_REQUIRED_FIELDS: tuple[str, ...] = (
    schema.CLIENT_ID,
    schema.HOUSEHOLD_ID,
    schema.PROGRAM,
    schema.ENROLLMENT_DATE,
    schema.ENROLLMENT_STATUS,
)


@dataclass
class FieldGuess:
    """One proposed source-header to canonical-field mapping."""

    source_header: str
    canonical: str
    confidence: float
    reason: str

    @property
    def is_confident(self) -> bool:
        return self.confidence >= CONFIDENT_THRESHOLD


@dataclass
class ProfileDraft:
    """A generated draft plus everything a human needs to check it."""

    profile_id: str
    grant_name: str
    mappings: list[FieldGuess] = field(default_factory=list)
    unmapped_headers: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)
    vocabularies: dict[str, list[str]] = field(default_factory=dict)
    period_start: str = ""
    period_end: str = ""

    @property
    def confident(self) -> list[FieldGuess]:
        return [g for g in self.mappings if g.is_confident]

    @property
    def uncertain(self) -> list[FieldGuess]:
        return [g for g in self.mappings if not g.is_confident]


def _normalize(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(header).casefold())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


#: Wording real extracts use that no string-similarity measure would connect to
#: the canonical name. Kept small and explicit rather than clever.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    schema.ENROLLMENT_DATE: ("entrydate", "startdate", "admissiondate", "intakedate"),
    schema.EXIT_DATE: ("dischargedate", "enddate", "departuredate"),
    schema.ENTRY_INCOME: ("incomeatentry", "monthlyincomeatentry", "startingincome"),
    schema.EXIT_INCOME: ("incomeatexit", "monthlyincomeatexit", "endingincome"),
    schema.PROGRAM: ("programname", "projectname", "project", "programtype"),
    schema.CLIENT_ID: ("clientid", "personalid", "participantid", "clientnumber"),
    schema.HOUSEHOLD_ID: ("householdid", "familyid", "caseid"),
    schema.ENROLLMENT_STATUS: ("status", "enrollmentstatus", "recordstatus"),
    schema.EXIT_DESTINATION: ("destination", "exitdestination", "dischargedestination"),
    schema.AGE: ("ageatentry", "age", "clientage"),
}


def _guess_field(header: str) -> FieldGuess | None:
    """Best canonical match for one source header, or None if nothing fits."""
    normalized = _normalize(header)

    for canonical, synonyms in _SYNONYMS.items():
        if normalized in synonyms:
            return FieldGuess(header, canonical, 1.0, "known alias for this field")

    best, best_score = "", 0.0
    for canonical in schema.CANONICAL_COLUMNS:
        score = _similarity(header, canonical)
        if score > best_score:
            best, best_score = canonical, score

    if best_score >= 0.999:
        return FieldGuess(header, best, 1.0, "exact match")
    if best_score >= SUGGEST_THRESHOLD:
        return FieldGuess(header, best, round(best_score, 2), f"{best_score:.0%} similar to name")
    return None


def _infer_period(frame: pd.DataFrame, columns: list[str]) -> tuple[str, str]:
    """Earliest and latest plausible dates across the mapped date columns."""
    stamps: list[pd.Timestamp] = []
    for column in columns:
        if column not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[column], errors="coerce", format="mixed").dropna()
        stamps.extend([parsed.min(), parsed.max()] if not parsed.empty else [])
    if not stamps:
        return "", ""
    return min(stamps).date().isoformat(), max(stamps).date().isoformat()


def draft_profile(
    frame: pd.DataFrame, profile_id: str = "new_grant", grant_name: str = "New Grant"
) -> ProfileDraft:
    """Infer a profile draft from a sample extract."""
    draft = ProfileDraft(profile_id=profile_id, grant_name=grant_name)

    claimed: dict[str, FieldGuess] = {}
    for header in frame.columns:
        guess = _guess_field(str(header))
        if guess is None:
            draft.unmapped_headers.append(str(header))
            continue
        # Two headers can match one field; the stronger guess wins and the other
        # is reported as unmapped rather than silently overwriting it.
        existing = claimed.get(guess.canonical)
        if existing is None or guess.confidence > existing.confidence:
            if existing is not None:
                draft.unmapped_headers.append(existing.source_header)
            claimed[guess.canonical] = guess
        else:
            draft.unmapped_headers.append(str(header))

    draft.mappings = sorted(claimed.values(), key=lambda g: g.canonical)
    mapped_canonicals = set(claimed)
    draft.missing_required = sorted(
        c for c in DEFAULT_REQUIRED_FIELDS if c not in mapped_canonicals
    )

    reverse = {g.canonical: g.source_header for g in draft.mappings}

    program_column = reverse.get(schema.PROGRAM)
    if program_column and program_column in frame.columns:
        values = frame[program_column].dropna().astype(str).str.strip()
        draft.programs = sorted({v for v in values if v})[:20]

    for canonical in (
        schema.GENDER,
        schema.RACE,
        schema.ETHNICITY,
        schema.VETERAN_STATUS,
        schema.DISABILITY_STATUS,
        schema.ENROLLMENT_STATUS,
        schema.EXIT_DESTINATION,
    ):
        column = reverse.get(canonical)
        if not column or column not in frame.columns:
            continue
        values = frame[column].dropna().astype(str).str.strip()
        distinct = sorted({v for v in values if v})
        if 0 < len(distinct) <= MAX_VOCABULARY_SIZE:
            draft.vocabularies[canonical] = distinct

    date_columns = [reverse[c] for c in (schema.ENROLLMENT_DATE, schema.EXIT_DATE) if c in reverse]
    draft.period_start, draft.period_end = _infer_period(frame, date_columns)
    draft.unmapped_headers = sorted(set(draft.unmapped_headers))
    return draft


def draft_to_yaml(draft: ProfileDraft) -> str:
    """Render the draft as commented YAML a human finishes by hand."""

    def quote(value: str) -> str:
        return '"' + value.replace('"', '\\"') + '"'

    lines = [
        f"# Draft profile generated from a sample extract for {draft.grant_name}.",
        "#",
        "# This is a starting point, not a finished profile. Check every mapping,",
        "# fill in the performance measures, and validate with:",
        "#     grant-assistant validate-config",
        "",
        f"profile_id: {draft.profile_id}",
        f"grant_name: {quote(draft.grant_name)}",
        'grantor: ""',
        'description: ""',
        "",
        "reporting_period:",
        f"  start: {draft.period_start or '2024-07-01  # no dates found; set this'}",
        f"  end: {draft.period_end or '2025-06-30  # no dates found; set this'}",
        "",
    ]

    lines.append("field_mappings:")
    if draft.confident:
        for guess in draft.confident:
            lines.append(f"  {quote(guess.source_header)}: {guess.canonical}")
    if draft.uncertain:
        lines.append("  # Uncertain — uncomment after checking each one:")
        for guess in draft.uncertain:
            lines.append(f"  # {quote(guess.source_header)}: {guess.canonical}  # {guess.reason}")
    lines.append("")

    if draft.missing_required:
        lines.append("# WARNING: no column was found for these required fields:")
        for canonical in draft.missing_required:
            lines.append(f"#   {canonical}")
        lines.append("")
    if draft.unmapped_headers:
        lines.append("# Columns in the file that were not mapped (ignored by the audit):")
        for header in draft.unmapped_headers:
            lines.append(f"#   {header}")
        lines.append("")

    lines.append("programs:")
    if draft.programs:
        for name in draft.programs:
            lines.append(f"  - name: {quote(name)}")
            lines.append("    aliases: []")
    else:
        lines.append("  # No program column was mapped; add programs by hand.")
        lines.append('  - name: "Program A"')
        lines.append("    aliases: []")
    lines.append("")

    lines.append("required_fields:")
    for canonical in sorted(DEFAULT_REQUIRED_FIELDS):
        lines.append(f"  - {canonical}")
    lines.append("")

    lines.append("controlled_values:")
    if draft.vocabularies:
        for canonical, values in draft.vocabularies.items():
            lines.append(f"  {canonical}:")
            for value in values:
                lines.append(f"    - {quote(value)}")
    else:
        lines.append("  {}")
    lines.append("")

    lines += [
        "# Fill these in from the funder's requirements — they cannot be inferred",
        "# from a data file, and the audit is much less useful without them.",
        "performance_measures: []",
        "followup_schedule: []",
        "",
    ]
    return "\n".join(lines) + "\n"
