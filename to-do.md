# Job Search Pal — To-Do

Snapshot of what's built vs. what's left, organized by the SRS §2.6 release plan.

## Done

### R0 — Infra & auth
- ✅ Docker stack (`db` / `api` / `web`), `setup.sh` secret generation, Argon2 + JWT cookie, AES-GCM credential encryption.
- ✅ Isolated `claude_config` volume, Claude Code CLI installed inside the `api` container, project `/app/skills` symlinked into `/root/.claude/skills/` on startup.
- ✅ **In-UI Claude Code OAuth flow** via `claude setup-token` under a PTY, SSE-streamed to the browser, token auto-extracted + persisted. Paste-token fallback and Settings-page **Reset authentication** button.
- ✅ Alembic migrations 0001–0006, all post-0001 migrations idempotent.
- ✅ Bearer-token authentication alongside cookie auth (so subprocess skills can act as the user via `Authorization: Bearer`).

### R1 — History & Timeline
- ✅ **All 13 history entity types** with full CRUD: `WorkExperience`, `Education`, `Course` (nested under Education), `Skill`, `Certification`, `Language`, `Project`, `Publication`, `Presentation`, `Achievement`, `VolunteerWork`, `Contact`, `CustomEvent`.
- ✅ **Organizations** shared across Work / Education / TrackedJob / Contact with Monarch-style combobox (type-to-create, case-insensitive dedup) and usage counts.
- ✅ **Career Timeline** horizontal roadmap view with year axis, color-coded lanes per kind, greedy first-fit lane assignment for parallel events, point-marker rendering for single-date events, "present" indicator for ongoing work, toggleable color legend.

### R1 — Containment & relationships
- ✅ **Dedicated skill-link tables** `WorkExperienceSkill` and `CourseSkill` with `usage_notes`. Link / unlink / list endpoints idempotent.
- ✅ **Generic `entity_links` polymorphic many-to-many** — any entity can link to any other across 14 types with auto-resolved `to_label`.
- ✅ **`SkillMultiSelect`** component (searchable + create-on-new, linked or unlinked modes, read-only mode).
- ✅ **`RelatedItemsPanel`** (polymorphic entity linker, read-only mode).
- ✅ **Read/edit gating**: linked skills and related items show as inline chips in the collapsed entity view; add/remove controls only appear when editing.

### R2 — Job Tracking
- ✅ **`/jobs`** Job Tracker list — status-pill filters (13 statuses, counts per status), table view with inline status change, +New Job modal with org combobox.
- ✅ **`/jobs/[id]`** Job Detail with **Overview / Interview Rounds / Artifacts / Contacts / Documents / Activity** tabs.
- ✅ **Interview Artifacts CRUD** — take-home prompts, whiteboard snapshots, feedback notes, recruiter emails, offer letters, prep docs. Optional round-link. Collapsible long-content view.
- ✅ **Contacts tab** — link existing `Contact` records to a TrackedJob via the polymorphic `entity_links` table, with relation + note + email/phone/LinkedIn surfacing.
- ✅ **Status transitions emit `ApplicationEvent`** automatically and auto-stamp `date_applied` / `date_closed`.
- ✅ **Interview Rounds CRUD** — round number, type, scheduled_at, duration, format, outcome pill, self-rating, prep/post notes.
- ✅ **Activity feed** with manual note logging.
- ✅ **Extended TrackedJob fields** (migration 0005): `experience_years_min/max`, `experience_level`, `employment_type`, `education_required`, `visa_sponsorship_offered`, `relocation_offered`, `required_skills`, `nice_to_have_skills`, `date_posted`, `date_applied`, `date_closed`.
- ✅ **`SkillsAnalysis`** component — compares JD-required/nice-to-have skills against the user's catalog, shows matching (green ✓) vs missing (amber `+ Add`) chips. Available on New Job form after fetch and on Job Detail Overview.
- ✅ **URL → autofill** via `POST /jobs/fetch-from-url` using Claude's WebFetch + WebSearch. Extracts ~30 fields including enriched organization context (website / industry / size / HQ / description / tech-stack hints). Full verbatim job description.
- ✅ **Inline status change** on tracker list rows (click badge → dropdown → PUT).
- ✅ **Fetch Queue** (migration 0006 `job_fetch_queue`) — a background asyncio worker polls queued URLs, runs the fetch pipeline, creates a TrackedJob seeded with optional preset status / priority / date_applied / date_closed / notes. UI: collapsible queue card with live state pills, retry on error, "open created job" link.
- ✅ **Excel bulk import**: `GET /jobs/import-template.xlsx` (26 columns + instructions sheet) and `POST /jobs/import` (lenient parser, auto-creates organizations, per-row error surface). UI: **Excel template** / **Import Excel** buttons on the tracker page.

### R3 — Companion (foundation)
- ✅ **`/companion`** Companion Chat — two-pane UI, multi-turn threading via `claude --resume <session_id>`, auto-title, error surfacing, delete conversation.
- ✅ **Companion sees everything on demand** — per-turn primer describing the entity graph + endpoint map, short-lived service JWT injected as `JSP_API_TOKEN` env var, `Bash` + `Read` + `Grep` + `Glob` + `WebFetch` + `WebSearch` allowed. Companion can `curl` any endpoint as the user.
- ✅ **Skills discoverable** — 15 project skills at `/app/skills/` symlinked into the container's `~/.claude/skills/` on boot.
- ✅ **jd-analyzer** endpoint `POST /jobs/{id}/analyze-jd` — populates `TrackedJob.jd_analysis` with fit score, strengths, gaps, red/green flags, interview focus, questions to ask, resume emphasis, cover-letter hook. JD Analysis panel on Job Detail Overview.
- ✅ **Unified tailor endpoint** `POST /documents/tailor/{job_id}` — picks resume / cover-letter / email / generic prompt based on `doc_type`. Job Detail Documents tab now has one "Write" button with a type selector. Specific `/tailor-resume` and `/tailor-cover-letter` endpoints retained for back-compat.
- ✅ **Arbitrary document upload** — `POST /documents/upload` (multipart, 25 MB cap, any mime), `GET /documents/{id}/file` to stream the original. Inline preview for PDFs (via `<object>`) and images. Text files also get `content_md` populated for inline viewing. Companion can call the same endpoint via its service JWT to snapshot files it produces.
- ✅ **Company researcher** — `POST /organizations/{id}/research` runs WebSearch+WebFetch to populate website / industry / size / HQ / description (only if empty), refresh `research_notes` and `reputation_signals`, and merge `tech_stack_hints` + `source_links`. Panel on Job Detail Overview and embedded research block in the Organizations edit form.
- ✅ **Document Studio** — `/studio` page now lists every GeneratedDocument across all jobs with filter-by-type + filter-by-job. Inline markdown edit (`PUT /documents/{id}`), PDF/image preview, link back to the owning job.
- ✅ **Writing Samples Library** — `GET/POST/PUT/DELETE /documents/samples` and `POST /documents/samples/upload`. `/samples` page with paste-in, .txt/.md upload, tags, word counts, full viewer + editor.

## What's left

### R1 — History polish (small)
- ✅ **Timeline: highlight entities with unresolved gaps** — backend computes a `metadata.gaps[]` list per event (missing highlights, missing summary, missing start date, etc.); frontend rings each event in the accent color and shows a `⚠` prefix. New "⚠ gaps (N)" toggle filters to only incomplete entries.
- ✅ **Timeline: optional grouping by role vs. kind** — new "By kind / By org" segmented toggle. Org mode groups events by subtitle (organization / issuer / venue) onto a single row each; kind mode is unchanged.
- ✅ Upgrade Achievement / Certification / Publication / VolunteerWork issuer / venue fields to use the `OrganizationCombobox` (see migration 0013 entry under R6).

### R2 — Job Tracking polish (medium)
- ✅ **Inline action buttons** — all the header actions are already live on Job Detail (Research Company as a panel on Overview; JD Analyze panel on Overview; Write / Upload on the Documents tab with a type selector that includes outreach_email / thank_you / followup).

### R3 — Skills MVP (big — the main remaining work)
Project skill definitions already exist at `/skills/<name>/SKILL.md`. Wire them through the API → DB → UI so the user (and Companion) can invoke them.
- ✅ **jd-analyzer** — `POST /jobs/{id}/analyze-jd` wired; panel on Job Detail Overview.
- ✅ **resume-tailor / cover-letter-tailor / generic tailor** — all three now go through the unified `POST /documents/tailor/{job_id}` endpoint (the two legacy specific routes remain). Documents tab shows version list + viewer (copy / download-as-md / edit), Document Studio at `/studio` lists across all jobs.
  - [ ] Chain through `writing-humanizer` when R4 ships.
- ✅ **email-drafter** — the unified tailor endpoint handles `outreach_email`, `thank_you`, and `followup` doc types with a purpose-specific email prompt.
- ✅ **company-researcher** — `POST /organizations/{id}/research` populates research_notes / tech_stack_hints / reputation_signals (engineering culture, work-life balance, layoffs, recent news, red/green flags). UI on Job Detail Overview and the Organizations edit form.
- ✅ **application-tracker workflow** — Companion primer now includes the exact step-by-step ingestion pattern (ask for URL → POST /jobs/queue or /jobs with desired_status=applied → log ApplicationEvent → confirm). Quick-prompt "Log a job I just applied to" on the Companion empty state.
- ✅ **history-interviewer workflow** — primer describes the gap-filling loop (audit via GET /history/*, one question at a time, PUT on confirm). Quick-prompt "Fill gaps in my history" on the Companion empty state.
- ✅ **companion-persona** wrapper — `Persona` model + full CRUD at `/api/v1/personas` + UI on Settings. Active persona (`name`, `description`, `tone_descriptors`, `system_prompt`) is appended to the Companion primer on every turn.
- ✅ Surface **skill invocations inline** in Companion chat — parsed endpoint + tool hints render as small chips under each assistant bubble alongside cost / duration / turns metadata. Cached in `tool_results` JSON so historical messages also show the data.
- ✅ Stream Companion responses (`--output-format stream-json`) — new `POST /companion/conversations/{id}/messages-stream` endpoint streams text deltas and tool-use events as Server-Sent Events. Frontend reads the stream with `fetch` + `ReadableStream`, updates the assistant bubble incrementally, persists server-side on `done`.
- ✅ Rich **`GeneratedDocument` editor** — `/studio/[id]` has a full-screen editor with textarea + selection-based AI (Rewrite / Answer / Create new document). Diff-against-previous-version is still R4 proper.

### R4 — Humanization & Studio (big)
- ✅ **Writing Samples Library** CRUD page: paste-in, tag, `.txt`/`.md` upload.
- ✅ **writing-humanizer** — `POST /documents/{id}/humanize` rewrites a generated document in the user's voice using up-to-N writing samples (optional tag filter). Creates a new doc with `humanized=true`, `parent_version_id` → source, and `humanized_from_samples` recording which samples were consulted. "Humanize" button on the editor triggers it.
- ✅ **Document Studio**: `/studio` lists every GeneratedDocument with type/job filters, inline markdown edit, PDF/image preview, link back to job. `/studio/[id]` is a full editor.
- ✅ **parent_version_id threading + diff controls** — every new tailor/upload/humanize/selection-new-doc version writes `parent_version_id` pointing at the previous version. Editor has a "Diff vs v{N-1}" toggle that fetches the parent and renders a line-level LCS diff (+/- line colors, add/remove counts).
- ✅ **Global editor "Send to Companion → rewrite selection"** — fulfilled by the `/studio/[id]` selection popup, which writes `DocumentEdit` rows for every rewrite / answer / new-doc action.
- ✅ **Interview Artifacts: file upload** — `POST /jobs/{id}/artifacts/upload` (multipart, 25 MB cap, any mime), `GET /jobs/{id}/artifacts/{id}/file` to stream. Text-ish files get `content_md` extracted via the same `doc_text` pipeline as documents. New "Upload file directly" button on the artifact create form.

### R5 — Analytics, Preferences, Personas (medium-big)
- ✅ **Dashboard charts** — live KPI tiles (active apps, response rate, offers won, applied this week + 30-day), status-distribution bar chart, pipeline funnel, and a 30-day activity sparkline. Hand-rolled SVG, no chart lib dependency.
- ✅ **Preferences & Identity** — `/preferences` page with four tabs (Job Preferences / Work Authorization / Criteria List / Demographics). Backend endpoints at `/api/v1/preferences/{job,authorization,criteria,demographics}` with singleton-upsert semantics (criteria is a list).
- ✅ **job-fit-scorer** — `POST /jobs/batch-analyze-jd` batches analyze-jd over every job with a description. `TrackedJobSummary` now exposes `red_flag_count`; Job Tracker renders a `⚠{n}` beside the fit score. "Score all" button in the tracker header.
- ✅ **application-autofiller** — `POST /autofill` with `{ questions, tracked_job_id?, extra_notes? }`. LLM receives Preferences + WorkAuthorization + job context only; demographics NEVER go into the prompt. Model returns `{placeholder}` tokens for demographic / sponsorship questions; backend resolves them from Demographics + WorkAuthorization, logs which fields were shared to `AutofillLog`. Autofill panel on Job Detail Overview with copy-per-answer buttons.
- ✅ **Persona editor + gallery** in Settings; active persona applied globally via Companion primer.
- ✅ **interview-prep** and **interview-retrospective** skills — `POST /jobs/{id}/rounds/{id}/prep` and `/retrospective`. Each round row on the Job Detail Rounds tab has Prep + Retro buttons; Retro opens an inline form and surfaces went-well / went-poorly / gaps / brush-up on submit.
- ✅ **job-strategy-advisor** — `POST /metrics/strategy` computes a fresh snapshot + reads the last 5 historical snapshots + top 15 active jobs, returns `{ headline, working_well, struggling, next_actions, risks }`. Strategy panel on the Dashboard.
- ✅ **MetricSnapshot materialization** — on-demand `POST /metrics/snapshot` computes total_jobs / status_counts / applied-responded counts / response_rate / avg_days_to_response / round pass-rate / weekly & 30-day velocity and persists it. `GET /metrics/snapshots` returns the history. (Cron variant still deferred — on-demand + auto-compute-in-strategy covers the core use.)

### Companion & Studio enhancements
- ✅ **File attach in Companion** — paperclip button on both the full `/companion` composer and the `CompanionDock` widget. Uploads go through `POST /documents/upload` (so the file is preserved in the user's Documents), and the resulting id is passed via `attached_document_ids` on the next message. Backend prefixes the user's prompt with an "USER ATTACHMENTS" block containing each file's extracted `content_md` (PDF/DOCX/HTML text extracted automatically, binary-only files noted with a URL to /file).
- ✅ **New document creation in Studio** — "+ New document" button on `/studio` opens a form with doc-type selector, optional tracked-job attachment, and optional starter content. Creates the document via `POST /documents` and routes straight into the editor.

### R6 — UX polish from real use
- ✅ **Preferences CSV typing bug** — new `CsvInput` component owns its own raw text state; commas and spaces no longer get stripped mid-keystroke.
- ✅ **Work panel dropdowns** — `employment_type` is a dropdown, and a new `remote_policy` dropdown (onsite / hybrid / remote) sits next to it.
- ✅ **Education `concentration`** field (migration 0008).
- ✅ **Courses start_date + end_date** fields (migration 0008).
- ✅ **Project panel** — `description` field removed. Skills / related items already flow through `RelatedItemsPanel` in edit mode.
- ✅ **Contact** — `can_use_as_reference` select (yes / no / unknown) + `relationship_type` expanded with school / project / work categories (manager, co-worker, classmate, project_partner, etc.).
- ✅ **History editor sort** — `_list_for_user` returns rows with null end_date (current) pinned top, then most-recent-end-date, alpha tiebreak on title/name/degree.
- ✅ **Timeline: drop "no highlights" gap warning** — only "no summary" flags now.
- ✅ **Companion markdown rendering** — assistant bubbles go through `react-markdown` + `remark-gfm` with styled lists, headings, code blocks, and tables.
- ✅ **Cost display on OAuth** — meta bar only shows `$cost` when `cost_usd > 0`; OAuth sessions (which report 0) no longer show `$0.000`.
- ✅ **Skills: case-insensitive dedupe on create** — `POST /skills` returns the existing row (same name, any case) instead of creating a duplicate.
- ✅ **Skills: attachment_count + unattached alert** — `SkillOut` exposes `attachment_count`; Skills tab flags `⚠ unattached` when zero. `GET /history/skills/{id}/attachments` returns the full list.
- ✅ **Timeline: same-org inline** — `assignLanes` now prefers lanes whose tail matches the event's subtitle, with a 60-day gap tolerance. Intern → full-time at the same company packs onto one lane.
- ✅ **Timeline: linked-org grouping** — projects linked to a Work or Education via `entity_links` now carry that entity's org as `metadata.effective_org`. By Org mode groups them under the linked job's org instead of "Unaffiliated".
- ✅ **resume-ingest skill** — `POST /history/resume-ingest` (dry_run) analyzes an uploaded resume and returns proposed WorkExperience / Education / Skill / Project entries. Committing (dry_run=false) persists them with case-insensitive skill dedupe and auto-creates Organization rows as needed. "Import from resume" button on the History Editor header opens an upload → review → commit flow.
- ✅ **Course relationships** — `RelatedItemsPanel` now renders on every course (editable in edit mode, read-only in the collapsed course list). Supports linking contacts, work experiences, projects, and every other polymorphic entity type.
- ✅ **Stream-json line-size crash** — bumped `asyncio.StreamReader` buffer from 64 KB to 16 MB when spawning Claude Code. Single assistant/text blocks routinely exceeded 64 KB (big tool_result payloads from history curls) and raised `ValueError: Separator is found, but chunk is longer than limit`, killing the tailor. Also catches the error in a per-line try/except so if we ever hit the new ceiling it logs and continues instead of torching the stream.
- ✅ **Download filename convention** — Studio now suggests `Firstname-Lastname_Resume_Organization` as the filename for both Print/PDF and a new "Download .md" button. Falls back gracefully if resume profile or org aren't populated. Name resolution: resume_profile.full_name → auth.me.display_name.
- ✅ **Queue: account-scoped cooldowns + long-window usage limits** — `_handle_rate_limit` now parses "resets at 3:00 PM" / "in 5 hours" patterns for Claude Pro's 5-hour window, caps cooldowns at 12h, tracks consecutive rate-limit hits in `payload.rate_limit_count` (so the escalating schedule survives attempt roll-backs), and propagates the cooldown to every other queued task for the same user. The whole queue parks together and wakes together.
- ✅ **Generalized task queue** — migration 0012 adds `kind`/`label`/`payload`/`result` to `job_fetch_queue`. Worker is now a dispatcher keyed on `kind` — fetch + score handlers wired today; tailor/humanize/etc. can plug in with just a new handler. Batch scoring enqueues one `score` task per unscored job and returns in <1s.

**Deferred (low priority / requires more scope):**
- ✅ **Project skills junction with `usage_notes`** (migration 0014) — new `project_skills` table mirrors `work_experience_skills` / `course_skills`. Endpoints at `GET/POST/DELETE /api/v1/history/projects/{id}/skills`. `GenericEntityPanel` gained a `skillsEndpoint` prop that renders `SkillMultiSelect` (edit mode) + read-only chips (collapsed). Skills-catalog attachment counts and the detail panel now include projects. Export/import covers the new table.
- ✅ **Preferred locations with per-location radius** (migration 0015) — new `preferred_locations` JSON column on `job_preferences`. Preferences page gains a multi-row editor: city autocomplete seeded with ~90 common US metros (datalist), free-text allowed, per-row 0–200 mi slider with "no cap" sentinel at the max. JD analyzer primer now instructs the Companion to score location fit against this list.
- ✅ **Contact-link picker on history rows** — `RelatedItemsPanel` is now on Work, Education, Courses, and Project; each can link to contacts (and every other polymorphic type) with relation + note. TrackedJob keeps its dedicated Contacts tab.
- ✅ **Organization FK on Achievement / Certification / Publication / VolunteerWork** (migration 0013) — each now has an optional `organization_id` FK to `organizations.id`. The history panels use the same `OrganizationCombobox` as Jobs/Work/Education (type-to-search-or-create). Backend mirrors the resolved org name into the legacy free-text columns (`issuer` / `venue` / `organization`) on save so old reads keep working without a data migration. A new `kind: "org"` option on the declarative `FieldDef` in `shared.tsx` renders the combobox inline with every other field.
- ✅ **Skills catalog: full attachment-detail side view** — click a skill row to open a right-side panel showing evidence notes + every attached Work (with org + dates + usage notes), Course (with parent degree + term + usage notes), and polymorphic EntityLink (tracked_jobs deep-link to `/jobs/{id}`, generated_documents to `/studio/{id}`). Backend endpoint now resolves labels, org names, and usage notes in a single call.
- ✅ **`not_interested` job status** — added to `JOB_STATUSES` on both sides; zinc-grey styled badge with a strikethrough; counts toward `date_closed` auto-stamp alongside won/lost/withdrawn/ghosted/archived.
- ✅ **Company research without a job link** — Organizations page gained a Research button per row; `POST /organizations/{id}/research` already ran standalone (no `tracked_job_id` required) — the button makes the workflow discoverable without opening the edit form first.
- [ ] Spend cap (SRS REQ-COST-002) — enforce per-month LLM ceiling **only when using an API key**. OAuth sessions have no per-turn cost.

## Known minor issues

- ✅ **UTF-8 mojibake fix** — child subprocess now runs with `LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8` (set in the Dockerfile and re-applied in both `run_claude_prompt` and `stream_claude_prompt`). The Node.js CLI and any curls it spawns write non-ASCII bytes as UTF-8, which Python decodes correctly — no more `rÃ©sumÃ©` round-trips.
- [ ] **Organization soft-delete references**: the timeline/history still show the stale name when an org is soft-deleted (by design), but there's no "reassign or hard-delete" workflow yet.
- ✅ **Settings stubs**: AI Persona has full CRUD + activate/deactivate. Data Export / Import is wired up via `/api/v1/admin/export` + `/api/v1/admin/import`.
- ✅ **Sidebar collapse / mobile layout**: drawer-style sidebar on viewports below `md`.
- ✅ **Streaming output** in the Companion — text deltas arrive live via SSE on `/messages-stream`.
- ✅ **CORS / port flexibility** — `next.config.mjs` proxies `/api/*` and `/health/*` through the web origin, so changing `.env` ports no longer requires a frontend rebuild and CORS is moot.
- [ ] **Observability** (SRS §3.3.5): `/metrics` Prometheus endpoint, structured JSON logs with PII scrubbing.
- [ ] **Accessibility pass** (WCAG 2.1 AA per SRS §3.1.1): keyboard traversal audit, ARIA labels on charts, focus indicators in the combobox.
- ✅ **Circular link reverse view** — `GET /history/links?either_type=X&either_id=N` returns links where the entity is on either side, normalized so the queried entity is always the `from_*` side. `RelatedItemsPanel` now uses it so entity B shows inbound links from A without extra bookkeeping.
- ✅ **OAuth debug-file cleanup** — new `_prune_old_debug_files` helper runs at the start of every `claude setup-token` session; deletes `.bin` files older than 7 days while always keeping the most recent 10 for active investigation. Cleans up the `claude_config` volume automatically.

## R9 — Email ingest (new milestone, Chris feature)

- ✅ **Paste-an-email → classify → suggest status change** (migration 0021).
  New `parsed_emails` table logs every email run through the classifier,
  with the Claude output, the matched tracked job (if any), and whether
  the suggestion was applied.
  - Endpoints: `POST /api/v1/email-ingest/parse` (one-shot classify),
    `POST /api/v1/email-ingest/{id}/reparse` (re-run classifier),
    `POST /api/v1/email-ingest/{id}/apply` (confirm with optional
    overrides — flips tracked-job status + logs an ApplicationEvent),
    `POST /api/v1/email-ingest/{id}/dismiss`,
    `DELETE /api/v1/email-ingest/{id}`,
    `GET /api/v1/email-ingest`.
  - Classifier prompt produces a strict JSON shape: `intent` (one of
    rejection / interview_invite / take_home_assigned / offer / withdrew /
    status_update / ghosted / unrelated), confidence, matched_job_id
    (verified to belong to the user before persist), suggested_status
    + suggested_event_type, key_dates extracted from body, summary.
  - Dedupes re-pasted emails via SHA-1 of from + subject + received_at +
    body so an accidental Ctrl-V doesn't double up.
  - New `/inbox` page: paste form on top, list of parsed emails below
    with state filters (new / applied / dismissed / errored / all).
    Selecting a row opens the review panel — user can override the
    matched job, target status, event type, and activity-feed note
    before clicking Apply. Body is collapsible.
  - Apply persists an ApplicationEvent with the email's from / subject
    + a quoted-thread-stripped body snippet, then re-runs the
    deterministic fit-score so the row stays fresh.
  - Sidebar gains an "Email Inbox" entry under the queues.

## R8 — Deterministic fit-score (new milestone, scope amendment)

- ✅ **Replace the Companion-driven `fit_score` with a pure-Python
  weighted average** (migration 0020). Score is reproducible, free, and
  recomputed on every job create / update / JD-analyze. No more Claude
  calls in the scoring path.
  - New `app/scoring/fit.py` produces a `FitResult` with a per-component
    breakdown (verdict ∈ match / partial / miss / veto / unknown /
    informational, weight 0-100, matched_pct, human-readable detail).
  - Seven **built-in components**: salary, remote_policy, location,
    experience_level, employment_type, travel, hours. Each has a default
    weight (70 / 60 / 50 / 60 / 50 / 30 / 30) editable per-user via
    `JobPreferences.builtin_weights` (new JSON column).
  - **JobCriterion.weight** is now first-class 0-100. Weight 0 =
    informational only. Weight 100 + tier=unacceptable + JD match = hard
    veto (forces score=0 with a stamped `veto_reason`). Other tiers
    contribute weight proportionally to numerator / denominator of a
    weighted average.
  - Built-in components also produce vetoes when the JD's value lands
    in the user's `..._unacceptable` lists (remote_policy,
    experience_level, employment_type, salary_unacceptable_below).
  - Persisted onto `tracked_jobs.fit_summary` as `{score, vetoed,
    veto_reason, breakdown[], summary, scored_by:"deterministic"}`. The
    qualitative `summary` from the JD-analyzer is preserved alongside.
  - Endpoints: `POST /jobs/{id}/recompute-fit-score` (single),
    `POST /jobs/recompute-fit-score-all` (every row).
  - **Preferences page**: new `BuiltinWeightsCard` with sliders +
    number inputs for the seven built-ins; criteria list rows now have
    inline tier dropdown + 0-100 weight slider with a 🚫 indicator
    when veto-eligible. "Recompute fit scores" button on both the
    Criteria tab and the Tracker toolbar.
  - **Job detail**: new `FitScoreBreakdownPanel` shows the score, veto
    reason if any, and a per-component table (verdict / label /
    weight / matched%). Refresh button hits the recompute endpoint.
    JD-Analysis panel no longer displays a number — that lives in the
    breakdown panel.

## R7 — Job Leads ingest (new milestone, scope amendment)

- ✅ **Job sources + leads inbox** (migration 0019). New `job_sources`
  and `job_leads` tables. Adapters for Greenhouse / Lever / Ashby /
  Workable / generic RSS / YC. Background poller fans out on a
  per-source schedule (`poll_interval_hours`) and writes deduped
  `JobLead` rows; leads expire after `lead_ttl_hours` if untouched.
  Bulk inbox UI at `/leads` lets the user mark leads
  interested / watching / dismissed; interested + watching auto-create
  a TrackedJob and queue a `score` task. Filters (title regex, location
  regex, remote-only) apply at ingest so the inbox doesn't drown.

## Approved feature requests (in flight / queued)

Migrated from `feature-requests.md` after review. ✅ = shipped this turn,
[ ] = approved but not yet built.

### Workflow & triage
- ✅ **Search jobs on the tracker page** (Chris note on global search) —
  free-text filter input above the table. Matches title, organization
  name, location, notes. Client-side, no backend change.
- ✅ **Bulk status change on tracker** — multi-select bar gains a
  "Change status to…" dropdown that PUTs every selected row's status.
- ✅ **Keyboard shortcuts on the review queue** — on `/jobs/{id}?from=review`,
  `1` = interested, `2` = not interested, `3` = skip, `j` = next.
  Ignored when focus is in an input/textarea.

### JD analysis & matching
- ✅ **Salary expectation vs. listing comparison** — tracker rows show
  green/amber/red salary badge when JD has a salary range, derived from
  `JobPreferences.salary_acceptable_min` / `salary_preferred_target`.
- ✅ **Commute / location fit badge** — tracker rows badge "fit" / "remote ok"
  / "outside radius" based on `preferred_locations` + JD location +
  remote_policy + willing_to_relocate.
- ✅ **Skill-match heatmap on tracker** — sortable Skills column shows a
  thin bar + N/total + %, fed by `TrackedJobSummary.skill_match_pct`
  computed against the user's catalog (name + alias normalize).

### Document workflow
- ✅ **Document tags** (migration 0017) — `tags` JSON array on
  `GeneratedDocument`. Editable in the Studio per-doc; filter the Studio
  list by tag chip.
- ✅ **Resume version comparison view** — Studio editor's diff panel now
  has a left-side version picker; default = parent_version_id, the
  user can pick any sibling version. Old "Diff vs v{N-1}" still works.
- ✅ **Batch humanize on Studio** — multi-select bar + "Humanize all".
  Skips uploads with no text and already-humanized rows; queues each
  through the existing `kind: humanize` queue worker.
- ✅ **PDF export with proper page breaks** — `@page { size: letter;
  margin: 0.5in }` plus `page-break-after: avoid` on headings,
  `page-break-inside: avoid` on bullets/blockquotes/tables, `orphans`
  and `widows` on paragraphs. New `.jsp-page-break` helper class for
  forced breaks.
- ✅ **Cover letter library** (migration 0018) — `cover_letter_snippets`
  table + CRUD at `/api/v1/cover-letter-library` + new
  `/cover-letter-library` page, filterable by kind (hook/bridge/close/
  anecdote/value_prop/other). Tags + content_md per snippet.

### Companion & data
- ✅ **Periodic gap audit + skill-stack suggestions** — Skills page now
  has an "Applied / interview only" toggle on the missing-from-jobs
  audit (status_in scopes to applied + interview-pipeline statuses)
  and a new "Skill stacks worth learning together" section showing
  pairs of skills that co-occur in JDs the user actually engaged with
  (`/api/v1/history/skills/stacks`).
- ✅ **Tracked-job archiving** — `POST /api/v1/jobs/auto-archive` (with
  preview) flips stale rows to `status=archived`: pre-application
  states ≥60d, in-flight ≥90d, ghosted/lost/withdrawn ≥30d. Tracker
  toolbar now has an "Auto-archive stale" button that previews
  candidates first.

### Analytics
- ✅ **Application-to-response funnel by source** — new
  `GET /api/v1/metrics/funnel-by-source` and a Dashboard table that
  renders applied → phone screen → onsite → offer → hired counts +
  rate-from-applied per `source_platform`, sorted by total.

### Integrations & polish
- ✅ **Browser extension stub** — Chromium MV3 scaffold under
  `apps/extension/`. Popup extracts JD via best-effort selectors,
  POSTs to `/api/v1/jobs` as a `to_review` row, options page sets
  the API base. README documents known gaps (no real icons, no
  organization resolver, cookie-only auth).
- ✅ **Accessibility pass** — global `:focus-visible` ring, skip-to-content
  link in `(app)/layout.tsx`, `aria-current="page"` and `aria-label`
  on the sidebar nav, `aria-modal` on the command palette, real `<kbd>`
  styling. Charts and combobox ARIA polish still deferred.
- ✅ **Cmd-K search across everything** — `CommandPalette` mounted at the
  app layout. ⌘/Ctrl+K opens. Hydrates jobs / orgs / docs / skills on
  first open, ranks substring + fuzzy matches, ↑/↓/Enter navigation.

## Non-code housekeeping

- ✅ **Update the README's "What works" section** to match reality —
  rewritten through R9, with links to `to-do.md` + `CHANGELOG.md`.
- ✅ **Add a proper `CHANGELOG.md`** (SRS §3.5.10) — at the repo root,
  organized by R-tag, conventional-commits style.
- [ ] Commit + tag `v0.1.0` after the next stable build cycle. (Holding
  off until the user has cycled through a real job-search session and
  flagged the rough edges they hit.)
- [ ] Remove or rotate the seeded test user (`chris@example.com`)
  before first real use. Setup.sh prompts for a real account on first
  run, but the seed user lingers if you skipped that.
