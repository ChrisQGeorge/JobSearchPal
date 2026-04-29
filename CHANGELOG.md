# Changelog

All notable changes to Job Search Pal. Loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses
SRS §2.6 release tags (R0–R9) as the milestone marker.

The project is pre-1.0; backwards-incompatible schema changes still
land via Alembic migrations rather than a major-version bump.

## Unreleased

### Pending
- Spend cap enforcement (SRS REQ-COST-002, gated on API-key billing).
- Observability — `/metrics` Prometheus endpoint, structured JSON logs.
- Organization soft-delete reassign-or-hard-delete workflow.

## R9 — Email inbox · 2026-04-29

### Added
- `/inbox` page: paste an email body and the Companion classifies it
  (rejection / interview_invite / offer / take_home / status_update /
  unrelated), matches it to one of the user's tracked jobs by org +
  title, and proposes a status change + ApplicationEvent. User
  confirms (or overrides) before anything mutates a TrackedJob.
- Migration `0021_parsed_emails`: stores every email run through the
  classifier with a state machine (new / applied / dismissed /
  errored). Dedupes re-pastes via SHA-1 of from + subject + received
  + body.
- `/api/v1/email-ingest` router: parse / reparse / apply / dismiss /
  list / delete. Classifier output is normalized — suggested status
  must be in an allowlist; matched job_id is verified to belong to
  the requesting user before persist.
- Apply persists an ApplicationEvent with the email's from + subject
  plus a quoted-thread-stripped body snippet.

## R8 — Deterministic fit-score · 2026-04-29

### Changed
- **`fit_score` no longer comes from Claude.** New pure-Python scoring
  engine in `app/scoring/fit.py` runs against the user's preferences
  + criteria + weights. Output is a reproducible 0–100 plus a
  per-component breakdown.
- `_apply_jd_analysis_to_job` no longer pulls a numeric score; only
  the qualitative summary survives. Caller invokes
  `compute_fit_score` after.

### Added
- Migration `0020_builtin_weights_on_job_preferences` adds JSON column
  for per-user weight overrides.
- Seven built-in components (salary, remote_policy, location,
  experience_level, employment_type, travel, hours) with editable
  default weights.
- `JobCriterion.weight` is first-class 0–100. Weight 0 = informational
  only. Weight 100 + tier=unacceptable + matched JD = hard veto.
- Endpoints: `POST /jobs/{id}/recompute-fit-score` (single),
  `POST /jobs/recompute-fit-score-all` (every row).
- Preferences page: `BuiltinWeightsCard` with sliders + number inputs,
  inline tier dropdown + 0–100 weight slider per criterion (🚫
  indicator when veto-eligible), "Recompute fit scores" button.
- Tracker toolbar: "Recompute fit" button.
- Job detail: `FitScoreBreakdownPanel` showing per-component
  verdict / weight / matched%. Refresh button.

## R7 — Source ingest + Job Leads · 2026-04-28

### Added
- `/leads` page: registered ATS feed sources + a triageable lead
  inbox with state filters and bulk actions.
- Migration `0019_job_sources_and_leads`. New `job_sources` table
  (kind / slug_or_url / poll_interval_hours / lead_ttl_hours /
  filters / last_polled_at / last_error) and `job_leads` table
  (deduped on (source_id, external_id), state machine, expires_at).
- Adapters under `app/sources/`: greenhouse, lever, ashby, workable,
  generic rss, yc.
- Background poller (`app/sources/poller.py`) runs alongside the
  fetch-queue worker. Per-source schedule, ingest-time regex filters
  (title include / exclude, location include / exclude, remote-only),
  lead expiration on next tick.
- `POST /api/v1/job-sources/seed-defaults` inserts a starter library
  of disabled sources with worked-example regex filters (Stripe
  engineering only, Discord senior+ US-only, Netflix excluding
  director+, etc.).
- Bulk lead promotion auto-creates a TrackedJob and queues a
  `score` task on the existing fetch queue.

### Fixed
- Pre-dedupe leads in Python rather than catching unique-key errors —
  the prior IntegrityError + rollback path left the async pool in a
  state that surfaced as `MissingGreenlet` on the next request.
- Normalize naive `last_polled_at` to UTC before comparing against
  the tz-aware `cutoff`. MySQL DATETIME columns deserialize naive
  even when written tz-aware.
- Reject empty / whitespace-only `slug_or_url` with a 422 instead of
  silently saving "" and 404-ing on first poll.
- Wrap upstream 4xx responses in actionable error messages
  ("airbnb returned 404 — slug wrong or company isn't on greenhouse").
- Drop the YC default seed and example chips; the
  `companies/feed.atom` URL began returning 404.

## R0–R6 + offshoots · pre-2026-04-28

Foundation work tracked in `to-do.md` and the prior commit history.
Highlights:
- R0–R1: Docker stack, auth, in-UI Claude Code OAuth, AES-256-GCM
  credential encryption, all 13 history entity types with full CRUD,
  Career Timeline.
- R2: Job Tracker with status pills + multi-select bulk actions,
  Excel bulk-import, URL-fetch autofill, salary / location / skill-
  match heatmap badges, Review + Apply queues with `1`/`2`/`3` and
  `j`/`k` keyboard shortcuts, auto-archive of stale rows.
- R3: Companion chat, 15 skills mounted, jd-analyzer / resume-tailor
  / cover-letter-tailor / email-drafter / company-researcher /
  application-autofiller / interview-prep + retro / strategy advisor
  end-to-end.
- R4: Document Studio (selection-based AI, parent-version threading,
  any-vs-any version diff, batch humanize, document tags, PDF page-
  break aware print stylesheet), Writing Samples Library, Cover
  Letter Library.
- R5: Dashboard KPIs, status distribution, pipeline funnel, 30-day
  activity sparkline, application-to-response funnel by source,
  MetricSnapshot materialization.
- R6: Real-use polish — preferred-locations with per-location
  radius, project-skills junction table, Skills tab with
  unattached / dupe / missing-from-jobs sections + "Skill stacks
  worth learning together", periodic gap audit scoped to applied
  jobs, Cmd-K command palette, accessibility pass.

## Conventions

- Commits follow conventional-commits-ish style:
  `feat(scope): …`, `fix(scope): …`, `docs(...)`, `refactor(...)`.
- All Alembic migrations are idempotent (`_has_col` / `_has_table`
  guards) so re-runs are safe.
- Coordinated frontend / backend changes in one commit, since the
  app is a single deployable.
