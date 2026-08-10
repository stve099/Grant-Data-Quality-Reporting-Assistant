"""Rules that flag distributions rather than individual records."""

from __future__ import annotations

from grant_assistant import schema
from grant_assistant.audit.engine import RuleContext, rule
from grant_assistant.audit.rules._helpers import _issue, _records
from grant_assistant.models import AuditIssue, IssueRecord, Severity


@rule(
    "DQ-060",
    "Statistical income outlier",
    "statistical",
    Severity.INFO,
    description="Entry incomes far outside the typical range (IQR fence).",
)
def income_outliers(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    vals = df[schema.ENTRY_INCOME]
    valid = vals[(vals.notna()) & (vals >= 0) & (vals <= ctx.profile.income_cap)]
    if len(valid) < ctx.threshold("income_outlier_min_sample", 20):
        return []
    q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
    iqr = q3 - q1
    if iqr <= 0:
        return []
    upper = q3 + ctx.threshold("income_outlier_iqr_multiplier", 3.0) * iqr
    mask = vals.notna() & (vals <= ctx.profile.income_cap) & (vals > upper)
    records = _records(ctx, mask, field=schema.ENTRY_INCOME, value_col=schema.ENTRY_INCOME)
    if not records:
        return []
    return [
        _issue(
            "DQ-060",
            "Statistical income outlier",
            "statistical",
            Severity.INFO,
            False,
            f"Entry incomes are far above the typical range for this dataset "
            f"(above ${upper:,.0f}, the 3×IQR fence). They may be legitimate but can pull "
            "average income figures upward.",
            "Spot-check these values; prefer median income when reporting if they are real.",
            records,
        )
    ]


@rule(
    "DQ-061",
    "Enrollment volume anomaly",
    "statistical",
    Severity.INFO,
    description="Months with unusually high or low enrollment counts.",
)
def enrollment_volume_anomaly(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    dates = df[schema.ENROLLMENT_DATE].dropna()
    if dates.empty:
        return []
    monthly = dates.dt.to_period("M").value_counts().sort_index()
    if len(monthly) < ctx.threshold("anomaly_min_months", 6):
        return []
    mean, std = float(monthly.mean()), float(monthly.std())
    if std == 0:
        return []
    z_limit = ctx.threshold("enrollment_anomaly_zscore", 2.0)
    anomalous = [p for p, c in monthly.items() if abs((c - mean) / std) > z_limit]
    if not anomalous:
        return []
    mask = df[schema.ENROLLMENT_DATE].dt.to_period("M").isin(anomalous)
    month_names = df[schema.ENROLLMENT_DATE].dt.strftime("%Y-%m")
    records = _records(ctx, mask.fillna(False), field=schema.ENROLLMENT_DATE, values=month_names)
    return [
        _issue(
            "DQ-061",
            "Enrollment volume anomaly",
            "statistical",
            Severity.INFO,
            False,
            "Some months have enrollment counts more than two standard deviations from the "
            f"monthly average ({mean:.1f}). This can indicate missing exports, backlogged "
            "data entry, or a real programmatic change worth explaining in the report.",
            "Confirm whether the spike/dip reflects reality or a data pipeline gap.",
            records,
        )
    ]


@rule(
    "DQ-062",
    "Program-level trend anomaly",
    "statistical",
    Severity.INFO,
    description="A single program's monthly enrollments spiking or collapsing.",
)
def program_trend_anomaly(ctx: RuleContext) -> list[AuditIssue]:
    df = ctx.data.df
    records: list[IssueRecord] = []
    details: list[str] = []
    for program in ctx.profile.program_names:
        sub = df[(df[schema.PROGRAM] == program) & df[schema.ENROLLMENT_DATE].notna()]
        if sub.empty:
            continue
        monthly = sub[schema.ENROLLMENT_DATE].dt.to_period("M").value_counts().sort_index()
        if len(monthly) < ctx.threshold("anomaly_min_months", 6):
            continue
        mean, std = float(monthly.mean()), float(monthly.std())
        if std == 0:
            continue
        z_limit = ctx.threshold("program_anomaly_zscore", 2.5)
        anomalous = [p for p, c in monthly.items() if abs((c - mean) / std) > z_limit]
        if not anomalous:
            continue
        details.append(f"{program}: {', '.join(str(p) for p in anomalous)}")
        mask = df[schema.PROGRAM].eq(program) & df[schema.ENROLLMENT_DATE].dt.to_period("M").isin(
            anomalous
        )
        month_names = df[schema.ENROLLMENT_DATE].dt.strftime("%Y-%m")
        records.extend(
            _records(ctx, mask.fillna(False), field=schema.ENROLLMENT_DATE, values=month_names)
        )
    if not records:
        return []
    return [
        _issue(
            "DQ-062",
            "Program-level trend anomaly",
            "statistical",
            Severity.INFO,
            False,
            "Individual programs show months with enrollment counts far outside their own "
            f"typical volume ({'; '.join(details)}). Verify whether this reflects real "
            "program changes or incomplete data.",
            "Review the flagged months with program managers before publishing trends.",
            records,
        )
    ]
