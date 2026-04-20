# Claude Code Skills — Job Search Pal

Each subdirectory here is a Claude Code skill the Companion can invoke. Every skill has a `SKILL.md` with YAML frontmatter (`name` + `description`) and a body describing the skill's purpose, inputs, outputs, and guardrails.

These files are intentionally skeletons pending the R3+ implementation waves. The runtime invocation path (FastAPI → Claude Code CLI subprocess) is wired in `apps/api/app/skills/`.

## Skills

| Skill                   | Release | Purpose                                                                |
|-------------------------|---------|------------------------------------------------------------------------|
| `resume-tailor`         | R3      | Tailor a resume to a `TrackedJob` using canonical history only.        |
| `cover-letter-tailor`   | R3      | Tailor a cover letter; output is humanized before return.              |
| `email-drafter`         | R3      | Follow-ups, thank-yous, recruiter replies, negotiation drafts.         |
| `jd-analyzer`           | R3      | Extract structured signal from a job description.                      |
| `company-researcher`    | R3      | Assemble a public-signal summary for a company.                        |
| `history-interviewer`   | R3      | Fill gaps in history by asking the user targeted questions.            |
| `application-tracker`   | R3      | Create/update `TrackedJob`, `ApplicationEvent`, `InterviewRound`.      |
| `writing-humanizer`     | R4      | Rewrite AI output in the user's voice from `WritingSample` records.    |
| `interview-prep`        | R5      | Generate practice questions, drill the user, store prep as artifacts.  |
| `interview-retrospective` | R5    | Capture reflections after a round and store as artifacts.              |
| `job-strategy-advisor`  | R5      | Review the funnel and recommend search-strategy adjustments.           |
| `job-fit-scorer`        | R5      | Score a `TrackedJob` against `JobPreferences` + `JobCriterion`.        |
| `application-autofiller`| R5      | Emit application-form answers respecting `DemographicSharePolicy`.     |
| `selection-rewriter`    | R4      | In-editor "Send to Companion" rewrite of a text selection.             |
| `companion-persona`     | R3      | Wrapper that applies the active `Persona` to every skill output.       |

## Conventions

- Every generation skill **must not** fabricate facts not present in the user's canonical history.
- Every skill records a corresponding `AuditLog` entry when it mutates data.
- Demographic / identity data never appears in LLM prompts as free text — placeholders only (see `application-autofiller`).
