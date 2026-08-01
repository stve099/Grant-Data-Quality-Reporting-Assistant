# Responsible AI Use

This project is built for nonprofit program teams working with sensitive client data under
funder accountability. The AI layer is deliberately constrained. This document maps those
constraints onto the **4D framework** — Delegation, Description, Discernment, Diligence —
so a program director can judge what the AI is and is not trusted to do.

---

## Delegation — deciding what the AI does and does not do

The dividing line in this application is **arithmetic versus articulation**.

| Task | Owner | Why |
|---|---|---|
| Counting enrollments, exits, households | Python | Must be reproducible and auditable |
| Computing rates, income change, follow-up status | Python | A funder can re-derive every figure |
| Applying audit rules and scoring | Python | Rules are policy, not judgement |
| Comparing programs and periods | Python | Deltas must be exact |
| Explaining what a finding means | AI (optional) | Language work, not calculation |
| Drafting an executive summary | AI (optional) | Drafting, from supplied figures |
| Translating technical findings to plain language | AI (optional) | Its comparative advantage |

Nothing that a funder could audit is delegated to the model. If the AI layer is removed
entirely — no API key — every number, chart, report, and export still works. That is the
test of correct delegation: **the AI is an amplifier, not a dependency.**

Work that is *never* delegated:

- Deciding whether data is good enough to submit (the audit's blocking rules decide).
- Choosing what counts as a successful outcome (the grant profile decides).
- Judging an individual client's situation — the system never reasons about individuals.

## Description — telling the AI precisely what is needed

Prompts in this project are structured, not conversational:

- **Role and constraints up front.** The system prompt states the analyst role and seven
  numbered rules, including "never calculate new metrics" and "say so plainly when the
  data cannot answer the question."
- **Data in delimiters.** Calculated results are supplied inside `<fact_sheet>` tags as
  JSON, so the model can tell instructions from data.
- **Tools over prose.** Rather than hoping the model reads a number correctly out of a
  wall of text, it calls typed tools (`get_metric`, `compare_programs`, `get_measures`)
  that return exact values.
- **Explicit output expectations.** Narrative requests state the audience, the length, and
  the prohibition on adding figures.

See `src/grant_assistant/agents/analyst.py` for the prompt and
`src/grant_assistant/agents/tools.py` for the tool contracts.

## Discernment — evaluating what comes back

Trust is verified, not assumed.

- **A prompt-evaluation harness** (`uv run grant-assistant eval`) grades answers against a
  fixed question set. Code-based graders mechanically check that every number in an answer
  traces to a calculated value, that no client identifier appears, that unavailable data
  produces a refusal rather than a guess, and that the system prompt is never disclosed.
- **Deterministic comparison.** Because the same questions can be answered without AI, any
  AI answer can be checked against the deterministic one.
- **Mandatory caveats.** Small samples (denominator under 10), missing data, and blocking
  data quality issues are flagged by the calculation layer and must be carried into the
  narrative.
- **Correlation is not causation.** Causal phrasing is routed to a handler that supplies
  the comparison *and* states plainly that programs serve different populations, so the gap
  is an association rather than a demonstrated effect.

**What a program director should still check.** The AI can write a fluent paragraph around
correct numbers and still emphasize the wrong thing. A human reviews every report before it
goes to a funder. The application supports this by keeping the deterministic figures visible
next to the narrative in every interface.

## Diligence — handling data and disclosure responsibly

- **Client-level data never reaches the model.** The fact sheet contains aggregates only.
  Client IDs, household IDs, and raw rows are excluded by construction, and a test asserts
  that no identifier appears in the AI-visible payload.
- **Row-level detail requires deliberate action.** It appears only in the Issue Explorer and
  the Excel exports — never in chat answers or reports. Asked for a list of clients, the
  analyst gives the count and points to those tools.
- **Uploaded files are untrusted input.** Cells are scanned for prompt-injection phrases;
  suspicious content is neutralized before any AI processing and surfaced to the user as a
  warning. The scan names the column and row but never echoes the payload.
- **Secrets live in the environment.** API keys come from environment variables only;
  `.env` is git-ignored and unreadable by the agent configuration.
- **All shipped data is synthetic.** The sample datasets are generated; tests assert they
  contain no name, SSN, birth date, phone, email, or address fields.
- **Disclosure.** Reports state whether the narrative was AI-assisted or deterministic, so
  a funder always knows how the text was produced.

---

## Practical guidance for nonprofit teams

**Before you upload anything to any AI tool**, check three things: does your data-sharing
agreement permit it, does the vendor train on your inputs, and would a client be surprised?
This application is designed so the answer to the third question is "no" — the model sees
aggregates, not people. That property depends on using the app as built; pasting a raw
export into a general-purpose chatbot discards every protection described here.

**Where AI genuinely helps in grant work:** turning findings into readable narrative,
drafting the fifth version of a summary for a different audience, explaining a technical
data problem to a program manager, and catching what you forgot to look at.

**Where it does not:** deciding whether a number is right, judging an individual client,
or replacing the review a human owes a funder. Those stay with people.
