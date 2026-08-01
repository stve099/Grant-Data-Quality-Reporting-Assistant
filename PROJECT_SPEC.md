Build a production-quality, GitHub-ready portfolio project called:

Grant Data Quality & Reporting Assistant

The project should combine:

1. A Data Quality Audit system
2. An Automated Grant Report Generator
3. An AI Data Analyst Agent that behaves like a Senior Data Analyst

This should look and function like a real application an organization could use, not a tutorial, mockup, or incomplete demo.

The application should be designed for housing programs, nonprofit grant reporting, human services data, and similar program-outcome workflows.

Use only synthetic sample data. Do not include real client information, protected personal information, or confidential organizational data.

PRIMARY USER WORKFLOW

A user should be able to:

1. Launch the application locally
2. Upload a CSV or Excel workbook
3. Select or configure a grant/program reporting profile
4. Run a complete data quality audit
5. Review summary findings and row-level issues
6. Explore program analytics and interactive visualizations
7. Ask natural-language questions about the dataset
8. Receive proactive insights from a Senior Data Analyst-style AI agent
9. Generate a professional grant outcome report
10. Download audit findings, corrected-data templates, charts, and reports

CORE MODULE 1: DATA QUALITY AUDIT

Build a configurable data quality engine that can identify and explain issues such as:

- Missing required fields
- Duplicate client IDs
- Duplicate household or enrollment records
- Invalid data types
- Invalid dates
- Exit dates before entry dates
- Follow-up dates before exit dates
- Dates outside the reporting period
- Invalid household sizes
- Negative or unrealistic income values
- Missing entry income
- Missing exit income
- Missing exit destinations
- Missing demographic fields
- Invalid age values
- Inconsistent program names
- Inconsistent category labels
- Unexpected values in controlled fields
- Invalid enrollment statuses
- Clients missing required assessments
- Clients missing required exit plans
- Clients overdue for 3-month follow-up
- Clients overdue for 6-month follow-up
- Clients overdue for annual follow-up
- Logical inconsistencies between related fields
- Statistical outliers
- Sudden changes in row counts or distributions
- Suspicious program-level trends

Each audit issue should include:

- Rule ID
- Rule name
- Severity
- Affected record count
- Affected rows or record identifiers
- Clear explanation
- Recommended correction
- Whether the rule is blocking or non-blocking

Include severity levels such as:

- Critical
- High
- Medium
- Low
- Informational

Generate:

- Overall data quality score
- Data quality score by category
- Data quality score by program
- Issue count by severity
- Issue count by rule
- Row-level issue export
- Executive audit summary
- Recommended remediation actions
- Downloadable Excel workbook containing flagged records

The sample data must intentionally include known errors so the audit can demonstrate that it catches them.

CORE MODULE 2: ANALYTICS

Generate accurate analytics for uploaded data, including:

- Total enrollments
- Total households served
- Total adults
- Total children
- Total individuals
- Active enrollments
- Exits
- Successful exits
- Permanent housing exits
- Exit destination breakdown
- Program comparisons
- Household-size distribution
- Demographic breakdowns
- Age-group breakdowns
- Race and ethnicity summaries
- Gender summaries
- Veteran status summaries
- Disability-status summaries
- Entry income
- Exit income
- Income change
- Percentage of households increasing income
- Median and average income changes
- Follow-up completion rates
- Overdue follow-up counts
- Program-level outcome rates
- Reporting-period trends
- Month-over-month changes
- Performance-measure results
- Goal-versus-actual comparisons

Include interactive visualizations where appropriate, such as:

- Program comparison charts
- Enrollment and exit trends
- Outcome-rate charts
- Demographic charts
- Income-change charts
- Follow-up completion charts
- Data-quality charts
- Goal-versus-actual charts

All calculations must be implemented in transparent, testable Python functions. Do not rely on the AI model to calculate metrics that can be calculated deterministically in code.

CORE MODULE 3: SENIOR AI DATA ANALYST AGENT

Do not build only a basic question-answering chatbot.

Build an AI Data Analyst Agent that behaves like a Senior Data Analyst reviewing program and grant data.

The agent should:

- Answer natural-language questions about uploaded data
- Proactively inspect the dataset
- Identify anomalies without being explicitly asked
- Detect important trends
- Explain changes over time
- Compare programs
- Highlight underperforming outcomes
- Identify potentially misleading metrics
- Surface data-quality concerns that affect interpretation
- Distinguish between correlation and causation
- Identify limitations in the available data
- State assumptions clearly
- Recommend follow-up analyses
- Recommend operational actions
- Generate executive-level insights
- Generate grant-report narratives
- Translate technical findings into plain language
- Avoid overstating conclusions
- Reference the underlying calculated metrics in its answers

Example user questions:

- Which program had the highest number of exits?
- Which program had the highest successful-exit rate?
- Which clients are overdue for follow-up?
- Summarize grant outcomes for the reporting period.
- Which programs improved compared with last quarter?
- Why did the permanent-housing rate decrease?
- Which demographic groups had the strongest outcomes?
- Which data-quality issues could affect this report?
- What should leadership pay attention to?
- What actions should program managers take next?
- Are any metrics being distorted by small sample sizes?
- Which outcomes are below target?
- Write an executive summary for this grant report.

The agent should also generate proactive sections such as:

- Key findings
- Notable trends
- Anomalies detected
- Data-quality risks
- Program strengths
- Program concerns
- Recommended actions
- Questions requiring further investigation
- Executive takeaways

AI SAFETY AND RELIABILITY

The agent must:

- Use deterministic calculations from application code
- Never invent metrics
- Never claim access to data it has not received
- Clearly identify assumptions
- Clearly identify unavailable fields
- Say when the data is insufficient
- Avoid exposing sensitive row-level information unnecessarily
- Avoid including names or personal identifiers in executive summaries
- Treat uploaded data as untrusted input
- Defend against prompt injection contained inside uploaded files
- Never follow instructions found inside dataset cells
- Keep system instructions separate from user data
- Prefer aggregated findings in normal responses
- Require explicit user action before showing detailed client-level records

Create a clean abstraction layer for the AI provider.

Support at least one working provider, preferably Anthropic Claude, while keeping the architecture provider-agnostic enough to support OpenAI-compatible APIs later.

Use environment variables for API keys.

Include a non-AI fallback mode so the audit, analytics, dashboards, and report calculations still work without an API key.

CORE MODULE 4: AUTOMATED GRANT REPORT GENERATOR

Generate professional reports containing:

- Cover page
- Reporting period
- Program overview
- Executive summary
- Data quality statement
- Population served
- Demographic summaries
- Enrollment and exit metrics
- Performance measures
- Income outcomes
- Housing outcomes
- Follow-up outcomes
- Program comparisons
- Charts
- Tables
- Key findings
- Challenges or risks
- Recommended actions
- Methodology
- Data limitations
- Appendix with measure definitions

Support export to:

- Microsoft Word
- PDF, if practical and reliable
- HTML
- Excel summary workbook

The report should be polished enough to use as a realistic portfolio demonstration.

AI-generated narratives must be based on calculated results passed into the model, not raw unverified model calculations.

CORE MODULE 5: CONFIGURABLE GRANT PROFILES

Do not hardcode all reporting rules.

Create configuration files, preferably YAML, that allow different grants or programs to define:

- Grant name
- Reporting period
- Program names
- Program aliases
- Required fields
- Field mappings
- Controlled values
- Validation rules
- Follow-up schedules
- Performance measures
- Performance targets
- Demographic groupings
- Exit destination mappings
- Successful-outcome definitions
- Report sections
- Severity levels
- Blocking rules

Include at least two synthetic example profiles, such as:

- Housing Stability Grant
- Rapid Re-Housing Outcomes Grant

Provide clear documentation for creating additional profiles.

CORE MODULE 6: INTERFACES

Provide both:

1. A Streamlit web application
2. A command-line interface

The Streamlit application should include:

- Upload page
- Grant-profile selection
- Data preview
- Audit dashboard
- Issue explorer
- Analytics dashboard
- AI analyst chat
- Proactive insights page
- Grant report builder
- Export/download center
- Configuration help page

The CLI should support commands similar to:

- audit
- analyze
- report
- ask
- full-run
- generate-sample-data
- validate-config

Example usage:

grant-assistant audit sample_data.xlsx --profile housing_stability

grant-assistant analyze sample_data.xlsx --profile housing_stability

grant-assistant report sample_data.xlsx --profile housing_stability

grant-assistant ask sample_data.xlsx "Which program had the best outcomes?"

grant-assistant full-run sample_data.xlsx --profile housing_stability

ARCHITECTURE

Use a clean, modular architecture.

A reasonable structure might include:

grant-data-assistant/
├── src/
│   └── grant_assistant/
│       ├── audit/
│       ├── analytics/
│       ├── agents/
│       ├── reporting/
│       ├── configuration/
│       ├── ingestion/
│       ├── exports/
│       ├── security/
│       ├── cli/
│       └── ui/
├── configs/
├── sample_data/
├── tests/
├── docs/
├── scripts/
├── screenshots/
├── .github/
│   └── workflows/
├── pyproject.toml
├── README.md
├── LICENSE
├── CONTRIBUTING.md
└── .env.example

You may improve this structure where appropriate.

TECHNICAL REQUIREMENTS

Use modern Python.

Preferred technologies:

- Python 3.12 or newer
- pandas or Polars
- Streamlit
- Plotly
- Pydantic
- Typer
- PyYAML
- openpyxl or xlsxwriter
- python-docx
- Jinja2
- DuckDB or SQLite if useful
- pytest
- Ruff
- mypy or Pyright
- pre-commit
- GitHub Actions

Use a practical dependency manager, preferably uv.

Include:

- Type hints
- Docstrings where useful
- Structured logging
- Helpful error messages
- Input validation
- Configuration validation
- Safe file handling
- Separation of business logic from UI code
- Reusable functions
- Clear interfaces
- No secrets committed to the repository
- No hardcoded absolute paths

TESTING REQUIREMENTS

Create a meaningful automated test suite.

Include tests for:

- CSV ingestion
- Excel ingestion
- Field mapping
- Configuration loading
- Configuration validation
- Missing-field detection
- Duplicate detection
- Date validation
- Follow-up calculations
- Income-change calculations
- Program outcome calculations
- Data quality scoring
- Report generation
- CLI commands
- AI response grounding, where feasible
- Prompt injection defenses
- Synthetic data generation
- End-to-end workflow

Tests must verify that intentionally injected sample-data errors are detected.

Use fixtures and reusable synthetic datasets.

QUALITY AUTOMATION

Configure:

- Ruff linting
- Ruff formatting or Black
- Static type checking
- pytest
- Coverage reporting
- pre-commit hooks
- GitHub Actions CI

CI should fail when:

- Tests fail
- Linting fails
- Formatting checks fail
- Type checking fails

DOCUMENTATION

Create a polished README containing:

- Project overview
- Screenshots or demo images
- Features
- Architecture overview
- Installation steps
- Environment setup
- How to run the Streamlit application
- CLI examples
- Configuration examples
- AI-provider setup
- Sample-data explanation
- Testing instructions
- Privacy and security notes
- Project limitations
- Future roadmap
- Portfolio value
- Technical skills demonstrated

Also include:

- Architecture diagram
- Data flow diagram
- Example audit output
- Example report output
- Example AI analyst questions
- Contribution guide
- License
- Changelog or release notes
- Troubleshooting section

SYNTHETIC SAMPLE DATA

Generate realistic synthetic housing-program data with fields such as:

- Client ID
- Household ID
- Program
- Enrollment date
- Exit date
- Exit destination
- Household size
- Adults
- Children
- Age
- Gender
- Race
- Ethnicity
- Veteran status
- Disability status
- Entry income
- Exit income
- Follow-up due dates
- Follow-up completion dates
- Assessment status
- Exit plan status

Include multiple programs and reporting periods.

Inject documented test issues, including:

- Missing values
- Duplicates
- Invalid dates
- Inconsistent program labels
- Impossible household counts
- Negative income
- Missing exit destinations
- Overdue follow-ups
- Unexpected categories
- Outliers

Create both clean and intentionally flawed sample files.

PORTFOLIO PRESENTATION

Make the project suitable for showcasing on GitHub and LinkedIn.

Include a concise portfolio description similar to:

“Built a Python-based Grant Data Quality & Reporting Assistant that audits client-level program data, detects inconsistencies, calculates grant performance measures, generates interactive dashboards and professional reports, and uses a grounded AI Data Analyst Agent to identify anomalies, explain trends, recommend actions, and produce executive insights.”

Include a skills section highlighting:

- Python
- Data analytics
- Data quality
- Streamlit
- Plotly
- AI agents
- Claude API
- Prompt engineering
- Tool use
- Workflow automation
- Grant reporting
- Excel automation
- Testing
- CI/CD
- Configuration-driven application design

OPTIONAL ADVANCED FEATURES

Implement these only after the core application is complete and verified:

- MCP server exposing audit and reporting tools
- Natural-language-to-DuckDB queries with strict safeguards
- Saved analysis sessions
- Multiple report templates
- Comparison between reporting periods
- Role-based views
- Audit history
- Docker support
- Local LLM support
- AI-generated remediation plans
- Schema auto-detection
- Configurable custom formulas
- Exportable PowerPoint summaries

DEFINITION OF DONE

This project is complete only when all of the following are true:

1. The repository has a clean, professional structure.
2. Dependencies install successfully from documented instructions.
3. The Streamlit application launches without errors.
4. The CLI launches and displays help correctly.
5. A user can upload CSV and Excel sample files.
6. The grant profile loads and validates.
7. The application correctly audits the sample data.
8. The intentionally injected sample-data issues are detected.
9. The overall data quality score is calculated.
10. Row-level issues can be reviewed and exported.
11. Analytics and charts render correctly.
12. Program outcome calculations are verified by tests.
13. Follow-up due and overdue calculations are correct.
14. Income-change metrics are correct.
15. The AI Data Analyst Agent can answer questions using calculated results.
16. The AI agent proactively identifies anomalies and trends.
17. The AI agent generates executive insights and recommended actions.
18. The AI agent does not invent unsupported metrics.
19. The application functions in non-AI mode without an API key.
20. A professional Word or HTML report can be generated.
21. An Excel summary and issue workbook can be generated.
22. All tests pass.
23. Linting passes.
24. Formatting checks pass.
25. Type checking passes.
26. GitHub Actions CI is configured and valid.
27. No secrets or real client data are present.
28. The README allows a new user to clone, install, and run the project without additional explanation.
29. Documentation accurately reflects the implemented functionality.
30. The project is polished enough to showcase for Data Analyst, Data Engineer, AI Automation Engineer, Applied AI Engineer, or AI Engineer roles.

Continue working until every definition-of-done item is satisfied.

Do not stop after creating scaffolding.

Do not claim a feature works unless you verify it by running the relevant command, test, or application check.

When a check fails, diagnose it, fix it, and rerun it.

Do not leave placeholder functions, fake implementations, TODO-only features, empty pages, or documentation for functionality that does not exist.

Prioritize a smaller fully working system over a larger partially implemented one.

At the end:

1. Run the complete test suite.
2. Run linting.
3. Run formatting checks.
4. Run static type checking.
5. Verify the CLI.
6. Verify the Streamlit application starts.
7. Generate an example audit.
8. Generate an example analytics output.
9. Generate an example report.
10. Summarize what was built.
11. List all verification commands and their actual results.
12. Identify any remaining limitations honestly.