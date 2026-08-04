"""Generate a data dictionary from a grant profile.

The profile YAML already is the specification: which source column feeds which
canonical field, which values are legal, when follow-ups are due, what each
performance measure targets, and which findings block submission. That
specification lives where program staff never look.

This renders it as a handout — the document a data manager sends to whoever
produces the extract, so the file arrives correct instead of being corrected
later. Nothing here is authored by hand: everything is read from the profile and
the rule registry, so the handout cannot drift from what the engine enforces.
"""

from __future__ import annotations

from pathlib import Path

from grant_assistant.audit import list_rules
from grant_assistant.configuration import GrantProfile


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_None defined._", ""]
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        cells = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def build_data_dictionary(profile: GrantProfile) -> str:
    """Render the profile as Markdown."""
    p = profile
    required = set(p.required_fields)
    canonical_to_source: dict[str, list[str]] = {}
    for source, canonical in p.field_mappings.items():
        canonical_to_source.setdefault(canonical, []).append(source)

    lines: list[str] = [
        f"# {p.grant_name} — data dictionary",
        "",
        f"**Profile:** `{p.profile_id}`  ",
        f"**Grantor:** {p.grantor or '—'}  ",
        f"**Reporting period:** {p.reporting_period.start} to {p.reporting_period.end}",
        "",
    ]
    if p.description:
        lines += [p.description, ""]
    lines += [
        "This document is generated from the grant profile. It describes the file the",
        "reporting tool expects. Send it to whoever produces the extract.",
        "",
        "## Columns",
        "",
        "Header matching ignores case and spacing, so `Client ID`, `client_id` and",
        "`CLIENT ID` are equivalent. Columns not listed here are ignored.",
        "",
    ]
    rows = []
    for canonical in sorted(canonical_to_source):
        if canonical == "program":
            # Not a controlled_values entry, but not free text either — an
            # unrecognized program is a finding, so say where the list lives.
            accepted = "see Programs below"
        else:
            accepted = ", ".join(p.controlled_values.get(canonical, [])) or "free text"
        rows.append(
            [
                ", ".join(f"`{s}`" for s in sorted(canonical_to_source[canonical])),
                f"`{canonical}`",
                "Yes" if canonical in required else "",
                accepted,
            ]
        )
    lines += _table(["Expected header", "Canonical field", "Required", "Accepted values"], rows)

    lines += ["## Programs", ""]
    lines += _table(
        ["Program", "Also accepted as", "Description"],
        [[d.name, ", ".join(d.aliases) or "—", d.description or "—"] for d in p.programs],
    )

    lines += [
        "## Follow-ups",
        "",
        "A follow-up is due this many months after exit, and is counted overdue once",
        "the grace period has also passed.",
        "",
    ]
    lines += _table(
        ["Follow-up", "Due after exit", "Grace period", "Completion column"],
        [
            [
                f.label,
                f"{f.months_after_exit} months",
                f"{f.grace_days} days",
                f"`{f.completion_field}`",
            ]
            for f in p.followup_schedule
        ],
    )

    lines += ["## Performance measures", ""]
    lines += _table(
        ["ID", "Measure", "Target", "Scope", "Definition"],
        [
            [
                m.id,
                m.name,
                f"{'at least' if m.direction == 'at_least' else 'at most'} {m.target:g}"
                + ("%" if m.unit == "percent" else ""),
                m.program or "All programs",
                m.description or "—",
            ]
            for m in p.performance_measures
        ],
    )

    lines += [
        "## Exit destinations",
        "",
        "Destinations are grouped into categories. Exits to a category marked",
        "**successful** count toward the permanent-housing measures.",
        "",
    ]
    lines += _table(
        ["Category", "Counts as successful", "Destinations"],
        [
            [
                category.replace("_", " ").title(),
                "Yes" if category in p.successful_exit_categories else "",
                ", ".join(values),
            ]
            for category, values in p.exit_destination_categories.items()
        ],
    )

    blocking = set(p.blocking_rules)
    lines += [
        "## Validation rules",
        "",
        "Every rule the audit applies. A **blocking** finding must be resolved before",
        "the report is submitted.",
        "",
    ]
    lines += _table(
        ["Rule", "Checks", "Severity", "Blocking"],
        [
            [
                meta.rule_id,
                meta.name,
                p.severity_overrides.get(meta.rule_id, meta.severity).label,
                "Yes" if (meta.rule_id in blocking or meta.blocking) else "",
            ]
            for meta in list_rules()
        ],
    )

    lines += [
        "## Value limits",
        "",
    ]
    lines += _table(
        ["Limit", "Value"],
        [
            ["Maximum plausible income", f"{p.income_cap:,.0f}"],
            ["Maximum household size", str(p.max_household_size)],
            ["Maximum age", str(p.max_age)],
            ["Age groups", ", ".join(str(b) for b in p.age_group_bounds)],
        ],
    )
    return "\n".join(lines).rstrip() + "\n"


def write_data_dictionary(profile: GrantProfile, path: str | Path) -> Path:
    """Write the data dictionary as Markdown or HTML, chosen by extension."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown = build_data_dictionary(profile)
    if path.suffix.lower() in {".html", ".htm"}:
        path.write_text(_as_html(profile, markdown), encoding="utf-8")
    else:
        path.write_text(markdown, encoding="utf-8")
    return path


def _as_html(profile: GrantProfile, markdown: str) -> str:
    """Minimal self-contained HTML, so the handout opens anywhere."""
    from html import escape

    body: list[str] = []
    rows: list[str] = []

    def flush_table() -> None:
        if not rows:
            return
        cells = [r.strip().strip("|").split("|") for r in rows]
        header, *rest = [c for c in cells if not all(set(x.strip()) <= {"-"} for x in c)]
        body.append("<table><thead><tr>")
        # extend, not "+=": augmented assignment would rebind `body` as a local
        # of this nested function and shadow the list being built.
        body.extend(f"<th>{escape(c.strip())}</th>" for c in header)
        body.append("</tr></thead><tbody>")
        for row in rest:
            body.append("<tr>" + "".join(f"<td>{escape(c.strip())}</td>" for c in row) + "</tr>")
        body.append("</tbody></table>")
        rows.clear()

    for line in markdown.splitlines():
        if line.startswith("|"):
            rows.append(line)
            continue
        flush_table()
        if line.startswith("# "):
            body.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.strip():
            body.append(f"<p>{escape(line)}</p>")
    flush_table()

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(profile.grant_name)} — data dictionary</title><style>"
        "body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:60rem;"
        "margin:2rem auto;padding:0 1rem;line-height:1.5;color:#1a1a1a}"
        "h1{border-bottom:2px solid #2563eb;padding-bottom:.3rem}"
        "h2{margin-top:2rem;color:#1e40af}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.9rem}"
        "th,td{border:1px solid #d4d4d8;padding:.4rem .6rem;text-align:left;vertical-align:top}"
        "th{background:#f4f4f5}code{background:#f4f4f5;padding:.1rem .3rem;border-radius:3px}"
        "</style></head><body>" + "".join(body) + "</body></html>"
    )
