"""Pydantic models describing a grant reporting profile.

A profile is the single source of configuration for a grant: reporting
period, program names and aliases, field mappings, controlled vocabularies,
follow-up schedules, performance measures, and report settings.
Profiles are stored as YAML files in ``configs/``.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from grant_assistant import schema
from grant_assistant.models import Severity


class ReportingPeriod(BaseModel):
    """Inclusive reporting period for the grant."""

    start: date
    end: date

    @model_validator(mode="after")
    def check_order(self) -> ReportingPeriod:
        if self.end < self.start:
            raise ValueError(
                f"reporting_period.end ({self.end}) is before reporting_period.start ({self.start})"
            )
        return self

    @property
    def label(self) -> str:
        return f"{self.start:%B %d, %Y} – {self.end:%B %d, %Y}"


class ProgramDef(BaseModel):
    """A funded program and the alternate labels it may appear under."""

    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""


class FollowUpDef(BaseModel):
    """A scheduled post-exit follow-up milestone."""

    key: str = Field(description="Short identifier, e.g. '3_month'.")
    label: str = Field(description="Display label, e.g. '3-Month Follow-Up'.")
    months_after_exit: int = Field(gt=0, le=60)
    completion_field: str = Field(
        description="Canonical column holding the follow-up completion date."
    )
    grace_days: int = Field(default=14, ge=0, description="Days past due before flagged overdue.")

    @field_validator("completion_field")
    @classmethod
    def check_completion_field(cls, v: str) -> str:
        if v not in schema.DATE_COLUMNS:
            raise ValueError(
                f"completion_field '{v}' is not a canonical date column "
                f"(expected one of {list(schema.DATE_COLUMNS)})"
            )
        return v


class PerformanceMeasure(BaseModel):
    """A funder performance measure with a target value.

    When ``program`` is set, the metric is evaluated for that program only
    (program-scoped metrics: enrollments, exits, exit_rate, successful_exit_rate,
    permanent_housing_rate, avg_income_change, median_income_change).
    """

    id: str
    name: str
    metric: str = Field(description="Key of a deterministic metric computed by analytics.")
    target: float
    unit: str = Field(default="percent", pattern="^(percent|count|currency)$")
    direction: str = Field(default="at_least", pattern="^(at_least|at_most)$")
    program: str | None = Field(
        default=None, description="Scope the measure to one program (canonical name)."
    )
    description: str = ""


class ReportConfig(BaseModel):
    """Report generation settings."""

    title: str = "Grant Outcome Report"
    prepared_by: str = "Program Data Team"
    sections: list[str] = Field(
        default_factory=lambda: [
            "executive_summary",
            "data_quality",
            "population",
            "demographics",
            "enrollment",
            "outcomes",
            "income",
            "followups",
            "measures",
            "programs",
            "findings",
            "recommendations",
            "methodology",
            "limitations",
            "appendix",
        ]
    )


class GrantProfile(BaseModel):
    """Complete configuration for one grant's reporting workflow."""

    profile_id: str
    grant_name: str
    grantor: str = ""
    description: str = ""
    reporting_period: ReportingPeriod
    programs: list[ProgramDef]
    field_mappings: dict[str, str] = Field(
        description="Maps source spreadsheet headers to canonical column names."
    )
    required_fields: list[str]
    controlled_values: dict[str, list[str]] = Field(default_factory=dict)
    followup_schedule: list[FollowUpDef] = Field(default_factory=list)
    performance_measures: list[PerformanceMeasure] = Field(default_factory=list)
    exit_destination_categories: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Maps outcome categories (e.g. 'permanent_housing') to destination values.",
    )
    successful_exit_categories: list[str] = Field(
        default_factory=lambda: ["permanent_housing"],
        description="Destination categories counted as successful exits.",
    )
    demographic_fields: list[str] = Field(
        default_factory=lambda: [
            schema.GENDER,
            schema.RACE,
            schema.ETHNICITY,
            schema.VETERAN_STATUS,
            schema.DISABILITY_STATUS,
        ]
    )
    age_group_bounds: list[int] = Field(
        default_factory=lambda: [18, 25, 35, 45, 55, 62],
        description="Upper bounds (exclusive) for age groups; a final open-ended group is added.",
    )
    income_cap: float = Field(default=300_000, gt=0, description="Incomes above this are outliers.")
    max_household_size: int = Field(default=12, gt=0)
    max_age: int = Field(default=110, gt=0)
    severity_overrides: dict[str, Severity] = Field(
        default_factory=dict, description="Per-rule severity overrides keyed by rule ID."
    )
    blocking_rules: list[str] = Field(
        default_factory=list, description="Rule IDs that block report submission."
    )
    report: ReportConfig = Field(default_factory=ReportConfig)

    @field_validator("field_mappings")
    @classmethod
    def check_mapping_targets(cls, v: dict[str, str]) -> dict[str, str]:
        bad = sorted(set(v.values()) - set(schema.CANONICAL_COLUMNS))
        if bad:
            raise ValueError(
                f"field_mappings maps to unknown canonical columns: {bad}. "
                f"Valid targets: {list(schema.CANONICAL_COLUMNS)}"
            )
        return v

    @field_validator("required_fields", "demographic_fields")
    @classmethod
    def check_canonical_fields(cls, v: list[str]) -> list[str]:
        bad = sorted(set(v) - set(schema.CANONICAL_COLUMNS))
        if bad:
            raise ValueError(f"unknown canonical columns: {bad}")
        return v

    @field_validator("controlled_values")
    @classmethod
    def check_controlled_fields(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        bad = sorted(set(v) - set(schema.CANONICAL_COLUMNS))
        if bad:
            raise ValueError(f"controlled_values references unknown canonical columns: {bad}")
        return v

    @model_validator(mode="after")
    def check_cross_references(self) -> GrantProfile:
        if not self.programs:
            raise ValueError("at least one program must be defined")
        names = [p.name for p in self.programs]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate program names in profile: {names}")
        bad_cats = set(self.successful_exit_categories) - set(self.exit_destination_categories)
        if bad_cats:
            raise ValueError(
                f"successful_exit_categories reference undefined destination categories: "
                f"{sorted(bad_cats)}"
            )
        measure_ids = [m.id for m in self.performance_measures]
        if len(measure_ids) != len(set(measure_ids)):
            raise ValueError(f"duplicate performance measure ids: {measure_ids}")
        program_names = set(names)
        for measure in self.performance_measures:
            if measure.program is not None and measure.program not in program_names:
                raise ValueError(
                    f"performance measure '{measure.id}' targets unknown program "
                    f"'{measure.program}' (known: {sorted(program_names)})"
                )
        return self

    # -- Convenience lookups -------------------------------------------------

    @property
    def program_names(self) -> list[str]:
        return [p.name for p in self.programs]

    def program_alias_map(self) -> dict[str, str]:
        """Case-insensitive map of every known program label to its canonical name."""
        mapping: dict[str, str] = {}
        for prog in self.programs:
            mapping[prog.name.strip().casefold()] = prog.name
            for alias in prog.aliases:
                mapping[alias.strip().casefold()] = prog.name
        return mapping

    def destination_category(self, destination: str) -> str | None:
        """Return the outcome category for an exit destination value, if mapped."""
        needle = destination.strip().casefold()
        for category, values in self.exit_destination_categories.items():
            if needle in (v.strip().casefold() for v in values):
                return category
        return None

    @property
    def successful_destinations(self) -> set[str]:
        out: set[str] = set()
        for cat in self.successful_exit_categories:
            out.update(self.exit_destination_categories.get(cat, []))
        return out

    def severity_for(self, rule_id: str, default: Severity) -> Severity:
        return self.severity_overrides.get(rule_id, default)

    def is_blocking(self, rule_id: str, default: bool) -> bool:
        if self.blocking_rules:
            return rule_id in self.blocking_rules or default
        return default
