"""Canonical dataset schema used internally by every module.

Uploaded files are mapped onto these canonical column names via the
``field_mappings`` section of a grant profile, so audit rules, analytics,
and reports never depend on a funder's specific spreadsheet headers.
"""

from __future__ import annotations

# Identity
CLIENT_ID = "client_id"
HOUSEHOLD_ID = "household_id"

# Enrollment
PROGRAM = "program"
PROGRAM_RAW = "program_raw"
ENROLLMENT_DATE = "enrollment_date"
ENROLLMENT_STATUS = "enrollment_status"
EXIT_DATE = "exit_date"
EXIT_DESTINATION = "exit_destination"

# Household composition
HOUSEHOLD_SIZE = "household_size"
ADULTS = "adults"
CHILDREN = "children"

# Demographics
AGE = "age"
GENDER = "gender"
RACE = "race"
ETHNICITY = "ethnicity"
VETERAN_STATUS = "veteran_status"
DISABILITY_STATUS = "disability_status"

# Income
ENTRY_INCOME = "entry_income"
EXIT_INCOME = "exit_income"

# Case management
ASSESSMENT_STATUS = "assessment_status"
EXIT_PLAN_STATUS = "exit_plan_status"

# Follow-up completion dates (due dates are derived from the exit date)
FOLLOWUP_3M_DATE = "followup_3m_date"
FOLLOWUP_6M_DATE = "followup_6m_date"
FOLLOWUP_12M_DATE = "followup_12m_date"

DATE_COLUMNS: tuple[str, ...] = (
    ENROLLMENT_DATE,
    EXIT_DATE,
    FOLLOWUP_3M_DATE,
    FOLLOWUP_6M_DATE,
    FOLLOWUP_12M_DATE,
)

NUMERIC_COLUMNS: tuple[str, ...] = (
    HOUSEHOLD_SIZE,
    ADULTS,
    CHILDREN,
    AGE,
    ENTRY_INCOME,
    EXIT_INCOME,
)

TEXT_COLUMNS: tuple[str, ...] = (
    CLIENT_ID,
    HOUSEHOLD_ID,
    PROGRAM,
    ENROLLMENT_STATUS,
    EXIT_DESTINATION,
    GENDER,
    RACE,
    ETHNICITY,
    VETERAN_STATUS,
    DISABILITY_STATUS,
    ASSESSMENT_STATUS,
    EXIT_PLAN_STATUS,
)

CANONICAL_COLUMNS: tuple[str, ...] = (
    CLIENT_ID,
    HOUSEHOLD_ID,
    PROGRAM,
    ENROLLMENT_DATE,
    ENROLLMENT_STATUS,
    EXIT_DATE,
    EXIT_DESTINATION,
    HOUSEHOLD_SIZE,
    ADULTS,
    CHILDREN,
    AGE,
    GENDER,
    RACE,
    ETHNICITY,
    VETERAN_STATUS,
    DISABILITY_STATUS,
    ENTRY_INCOME,
    EXIT_INCOME,
    ASSESSMENT_STATUS,
    EXIT_PLAN_STATUS,
    FOLLOWUP_3M_DATE,
    FOLLOWUP_6M_DATE,
    FOLLOWUP_12M_DATE,
)

#: Human-readable labels for canonical columns (used in reports and the UI).
COLUMN_LABELS: dict[str, str] = {
    CLIENT_ID: "Client ID",
    HOUSEHOLD_ID: "Household ID",
    PROGRAM: "Program",
    ENROLLMENT_DATE: "Enrollment Date",
    ENROLLMENT_STATUS: "Enrollment Status",
    EXIT_DATE: "Exit Date",
    EXIT_DESTINATION: "Exit Destination",
    HOUSEHOLD_SIZE: "Household Size",
    ADULTS: "Adults",
    CHILDREN: "Children",
    AGE: "Age",
    GENDER: "Gender",
    RACE: "Race",
    ETHNICITY: "Ethnicity",
    VETERAN_STATUS: "Veteran Status",
    DISABILITY_STATUS: "Disability Status",
    ENTRY_INCOME: "Entry Income",
    EXIT_INCOME: "Exit Income",
    ASSESSMENT_STATUS: "Assessment Status",
    EXIT_PLAN_STATUS: "Exit Plan Status",
    FOLLOWUP_3M_DATE: "3-Month Follow-Up Date",
    FOLLOWUP_6M_DATE: "6-Month Follow-Up Date",
    FOLLOWUP_12M_DATE: "12-Month Follow-Up Date",
}


def label_for(column: str) -> str:
    """Return the display label for a canonical column name."""
    return COLUMN_LABELS.get(column, column.replace("_", " ").title())
