# Job Search Pal — Done

Archive of every shipped feature. Migrated out of `to-do.md` so the
active punch-list stays scannable. Organized by SRS §2.6 release plan
plus the out-of-band milestones (R7 Job Leads, R8 Deterministic
fit-score, R9 Email ingest) that the project picked up along the way.

## R0 — Infra & auth

- ✅ Docker stack (`db` / `api` / `web`), `setup.sh` secret generation, Argon2 + JWT cookie, AES-GCM credential encryption.
- ✅ Isolated `claude_config` volume, Claude Code CLI installed inside the `api` container, project `/app/skills` symlinked into `/root/.claude/skills/` on startup.
- ✅ **In-UI Claude Code OAuth flow** via `claude setup-token` under a PTY, SSE-streamed to the browser, token auto-extracted + persisted. Paste-token fallback and Settings-page **Reset authentication** button.
- ✅ Alembic migrations 0001–0006, all post-0001 migrations idempotent.
- ✅ Bearer-token authentication alongside cookie auth (so subprocess skills can act as the user via `Authorization: Bearer`).

## R1 — History & Timeline

- ✅ **All 13 history entity types** with full CRUD: `WorkExperience`, `Education`, `Course` (nested under Education), `Skill`, `Certification`, `Language`, `Project`, `Publication`, `Presentation`, `Achievement`, `VolunteerWork`, `Contact`, `CustomEvent`.
- ✅ **Organizations** shared across Work / Education / TrackedJob / Contact with Monarch-style combobox (type-to-create, case-insensitive dedup) and usage counts.
- ✅ **Career Timeline** horizontal roadmap view with year axis, color-coded lanes per kind, greedy first-fit lane assignment for parallel events, point-marker rendering for single-date events, "present" indicator for ongoing work, toggleable color legend.

### R1 — Containment & relationships
- ✅ **Dedicated skill-link tables** `WorkExperienceSkill` and `CourseSkill` with `usage_notes`. Link / unlink / list endpoints idempotent.
- ✅ **Generic `entity_links` polymorphic many-to-many** — any entity can link to any other across 14 types with auto-resolved `to_label`.
- ✅ **`SkillMultiSelect`** component (searchable + create-on-new, linked or unlinked modes, read-only mode).
- ✅ **`RelatedItemsPanel`** (polymorphic entity linker, read-only mode).
- ✅ **Read/edit gating**: linked skills and related items show as inline chips in the collapsed entity view; add/remove controls only appear when editing.

### R1 — History polish
- ✅ **Timeline: highlight entities with unresolved gaps** — backend computes a `metadata.gaps[]` list per event (missing highlights, missing summary, missing start date, etc.); frontend rings each event in the accent color and shows a `⚠` prefix. New "⚠ gaps (N)" toggle filters to only incomplete entries.
- ✅ **Timeline: optional grouping by role vs. kind** — new "By kind / By org" segmented toggle. Org mode groups events by subtitle (organization / issuer / venue) onto a single row each; kind mode is unchanged.
- ✅ Upgrade Achievement / Certification / Publication / VolunteerWork issuer / venue fields to use the `OrganizationCombobox` (see migration 0013 entry under R6).

## R2 — Job Tracking

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
- ✅ **Inline action buttons** — all the header actions are already live on Job Detail (Research Company as a panel on Overview; JD Analyze panel on Overview; Write / Upload on the Documents tab with a type selector that includes outreach_email / thank_you / followup).

## R3 — Companion (foundation)

- ✅ **`/companion`** Companion Chat — two-pane UI, multi-turn threading via `claude --resume <session_id>`, auto-title, error surfacing, delete conversation.
- ✅ **Companion sees everything on demand** — per-turn primer describing the entity graph + endpoint map, short-lived service JWT injected as `JSP_API_TOKEN` env var, `Bash` + `Read` + `Grep` + `Glob` + `WebFetch` + `WebSearch` allowed. Companion can `curl` any endpoint as the user.
- ✅ **Skills discoverable** — 15 project skills at `/app/skills/` symlinked into the container's `~/.claude/skills/` on boot.
- ✅ **jd-analyzer** endpoint `POST /jobs/{id}/analyze-jd` — populates `TrackedJob.jd_analysis` with strengths, gaps, red/green flags, interview focus, questions to ask, resume emphasis, cover-letter hook. JD Analysis panel on Job Detail Overview.
- ✅ **Unified tailor endpoint** `POST /documents/tailor/{job_id}` — picks resume / cover-letter / email / generic prompt based on `doc_type`. Job Detail Documents tab now has one "Write" button with a type selector.
- ✅ **Arbitrary document upload** — `POST /documents/upload` (multipart, 25 MB cap, any mime), `GET /documents/{id}/file` to stream the original. Inline preview for PDFs (via `<object>`) and images. Text files also get `content_md` populated for inline viewing. Companion can call the same endpoint via its service JWT to snapshot files it produces.
- ✅ **Company researcher** — `POST /organizations/{id}/research` populates website / industry / size / HQ / description (only if empty), refresh `research_notes` and `reputation_signals`, and merge `tech_stack_hints` + `source_links`. Two-stage flow: direct httpx fetch of homepage + Wikipedia → Claude parse with no tools.
- ✅ **Document Studio** — `/studio` page lists every GeneratedDocument across all jobs with filter-by-type + filter-by-job. Inline markdown edit (`PUT /documents/{id}`), PDF/image preview, link back to the owning job.
- ✅ **Writing Samples Library** — `GET/POST/PUT/DELETE /documents/samples` and `POST /documents/samples/upload`. `/samples` page with paste-in, .txt/.md upload, tags, word counts, full viewer + editor.
- ✅ **email-drafter** — the unified tailor endpoint handles `outreach_email`, `thank_you`, and `followup` doc types with a purpose-specific email prompt.
- ✅ **application-tracker workflow** — Companion primer includes the exact step-by-step ingestion pattern (ask for URL → POST /jobs/queue or /jobs with desired_status=applied → log ApplicationEvent → confirm). Quick-prompt "Log a job I just applied to" on the Companion empty state.
- ✅ **history-interviewer workflow** — primer describes the gap-filling loop (audit via GET /history/*, one question at a time, PUT on confirm). Quick-prompt "Fill gaps in my history" on the Companion empty state.
- ✅ **companion-persona** wrapper — `Persona` model + full CRUD at `/api/v1/personas` + UI on Settings. Active persona (`name`, `description`, `tone_descriptors`, `system_prompt`) is appended to the Companion primer on every turn.
- ✅ Surface **skill invocations inline** in Companion chat — parsed endpoint + tool hints render as small chips under each assistant bubble alongside cost / duration / turns metadata.
- ✅ Stream Companion responses (`--output-format stream-json`) — `POST /companion/conversations/{id}/messages-stream` endpoint streams text deltas and tool-use events as Server-Sent Events.
- ✅ Rich **`GeneratedDocument` editor** — `/studio/[id]` has a full-screen editor with textarea + selection-based AI (Rewrite / Answer / Create new document).

## R4 — Humanization & Studio

- ✅ **Writing Samples Library** CRUD page: paste-in, tag, `.txt`/`.md` upload.
- ✅ **writing-humanizer** — `POST /documents/{id}/humanize` rewrites a generated document in the user's voice using up-to-N writing samples (optional tag filter). Creates a new doc with `humanized=true`, `parent_version_id` → source, and `humanized_from_samples` recording which samples were consulted. "Humanize" button on the editor triggers it.
- ✅ **Document Studio**: `/studio` lists every GeneratedDocument with type/job filters, inline markdown edit, PDF/image preview, link back to job. `/studio/[id]` is a full editor.
- ✅ **parent_version_id threading + diff controls** — every new tailor/upload/humanize/selection-new-doc version writes `parent_version_id` pointing at the previous version. Editor has a "Compare versions" picker that diffs against any sibling version.
- ✅ **Global editor "Send to Companion → rewrite selection"** — the `/studio/[id]` selection popup writes `DocumentEdit` rows for every rewrite / answer / new-doc action.
- ✅ **Interview Artifacts: file upload** — `POST /jobs/{id}/artifacts/upload` (multipart, 25 MB cap, any mime), `GET /jobs/{id}/artifacts/{id}/file` to stream. Text-ish files get `content_md` extracted via the same `doc_text` pipeline as documents.

## R5 — Analytics, Preferences, Personas

- ✅ **Dashboard charts** — live KPI tiles (active apps, response rate, offers won, applied this week + 30-day), status-distribution bar chart, pipeline funnel, and a 30-day activity sparkline. Hand-rolled SVG, no chart lib dependency.
- ✅ **Preferences & Identity** — `/preferences` page with four tabs (Job Preferences / Work Authorization / Criteria List / Demographics). Backend endpoints at `/api/v1/preferences/{job,authorization,criteria,demographics}` with singleton-upsert semantics (criteria is a list).
- ✅ **job-fit-scorer** — `POST /jobs/batch-analyze-jd` batches analyze-jd over every job with a description. `TrackedJobSummary` exposes `red_flag_count`; Job Tracker renders a `⚠{n}` beside the fit score. "Score all" button in the tracker header.
- ✅ **application-autofiller** — `POST /autofill` with `{ questions, tracked_job_id?, extra_notes? }`. LLM receives Preferences + WorkAuthorization + job context only; demographics NEVER go into the prompt. Model returns `{placeholder}` tokens for demographic / sponsorship questions; backend resolves them from Demographics + WorkAuthorization, logs which fields were shared to `AutofillLog`. Autofill panel on Job Detail Overview with copy-per-answer buttons.
- ✅ **Persona editor + gallery** in Settings; active persona applied globally via Companion primer.
- ✅ **interview-prep** and **interview-retrospective** skills — `POST /jobs/{id}/rounds/{id}/prep` and `/retrospective`. Each round row on the Job Detail Rounds tab has Prep + Retro buttons; Retro opens an inline form and surfaces went-well / went-poorly / gaps / brush-up on submit.
- ✅ **job-strategy-advisor** — `POST /metrics/strategy` computes a fresh snapshot + reads the last 5 historical snapshots + top 15 active jobs, returns `{ headline, working_well, struggling, next_actions, risks }`. Strategy panel on the Dashboard.
- ✅ **MetricSnapshot materialization** — on-demand `POST /metrics/snapshot` computes total_jobs / status_counts / applied-responded counts / response_rate / avg_days_to_response / round pass-rate / weekly & 30-day velocity and persists it. `GET /metrics/snapshots` returns the history.
- ✅ **File attach in Companion** — paperclip button on both the full `/companion` composer and the `CompanionDock` widget. Uploads go through `POST /documents/upload`, the resulting id is passed via `attached_document_ids` on the next message.
- ✅ **New document creation in Studio** — "+ New document" button on `/studio` opens a form with doc-type selector, optional tracked-job attachment, and optional starter content.

## R6 — UX polish from real use

- ✅ **Preferences CSV typing bug** — new `CsvInput` component owns its own raw text state; commas and spaces no longer get stripped mid-keystroke.
- ✅ **Work panel dropdowns** — `employment_type` is a dropdown, and a new `remote_policy` dropdown (onsite / hybrid / remote) sits next to it.
- ✅ **Education `concentration`** field (migration 0008).
- ✅ **Courses start_date + end_date** fields (migration 0008).
- ✅ **Project panel** — `description` field removed. Skills / related items already flow through `RelatedItemsPanel` in edit mode.
- ✅ **Contact** — `can_use_as_reference` select (yes / no / unknown) + `relationship_type` expanded with school / project / work categories.
- ✅ **History editor sort** — `_list_for_user` returns rows with null end_date (current) pinned top, then most-recent-end-date, alpha tiebreak.
- ✅ **Timeline: drop "no highlights" gap warning** — only "no summary" flags now.
- ✅ **Companion markdown rendering** — assistant bubbles go through `react-markdown` + `remark-gfm` with styled lists, headings, code blocks, and tables.
- ✅ **Cost display on OAuth** — meta bar only shows `$cost` when `cost_usd > 0`; OAuth sessions (which report 0) no longer show `$0.000`.
- ✅ **Skills: case-insensitive dedupe on create** — `POST /skills` returns the existing row (same name, any case) instead of creating a duplicate.
- ✅ **Skills: attachment_count + unattached alert** — `SkillOut` exposes `attachment_count`; Skills tab flags `⚠ unattached` when zero. `GET /history/skills/{id}/attachments` returns the full list.
- ✅ **Timeline: same-org inline** — `assignLanes` prefers lanes whose tail matches the event's subtitle, with a 60-day gap tolerance. Intern → full-time at the same company packs onto one lane.
- ✅ **Timeline: linked-org grouping** — projects linked to a Work or Education via `entity_links` carry that entity's org as `metadata.effective_org`. By Org mode groups them under the linked job's org.
- ✅ **resume-ingest skill** — `POST /history/resume-ingest` (dry_run) analyzes an uploaded resume and returns proposed WorkExperience / Education / Skill / Project entries. Committing (dry_run=false) persists them with case-insensitive skill dedupe and auto-creates Organization rows as needed. "Import from resume" button on the History Editor header.
- ✅ **Course relationships** — `RelatedItemsPanel` renders on every course (editable in edit mode, read-only collapsed). Supports linking contacts, work experiences, projects, and every other polymorphic entity type.
- ✅ **Stream-json line-size crash** — bumped `asyncio.StreamReader` buffer from 64 KB to 16 MB when spawning Claude Code. Per-line try/except logs and continues if the new ceiling is ever hit.
- ✅ **Download filename convention** — Studio suggests `Firstname-Lastname_Resume_Organization` for both Print/PDF and Download .md. Falls back gracefully if resume profile or org aren't populated.
- ✅ **Queue: account-scoped cooldowns + long-window usage limits** — `_handle_rate_limit` parses "resets at 3:00 PM" / "in 5 hours" patterns for Claude Pro's 5-hour window, caps cooldowns at 12h, tracks consecutive rate-limit hits in `payload.rate_limit_count`, and propagates the cooldown to every other queued task for the same user.
- ✅ **Generalized task queue** — migration 0012 adds `kind`/`label`/`payload`/`result` to `job_fetch_queue`. Worker is a dispatcher keyed on `kind` — fetch + score + tailor + humanize + org_research handlers wired.
- ✅ **Project skills junction with `usage_notes`** (migration 0014) — new `project_skills` table mirrors `work_experience_skills` / `course_skills`. Endpoints at `GET/POST/DELETE /api/v1/history/projects/{id}/skills`.
- ✅ **Preferred locations with per-location radius** (migration 0015) — `preferred_locations` JSON column on `job_preferences`. Multi-row editor with city autocomplete + per-row 0–200 mi slider.
- ✅ **Contact-link picker on history rows** — `RelatedItemsPanel` is on Work, Education, Courses, and Project; each can link to contacts (and every other polymorphic type) with relation + note.
- ✅ **Organization FK on Achievement / Certification / Publication / VolunteerWork** (migration 0013) — each has an optional `organization_id` FK. The history panels use the same `OrganizationCombobox` as Jobs/Work/Education.
- ✅ **Skills catalog: full attachment-detail side view** — click a skill row to open a right-side panel showing evidence notes + every attached Work, Course, and polymorphic EntityLink.
- ✅ **`not_interested` job status** — added to `JOB_STATUSES` on both sides; zinc-grey styled badge; counts toward `date_closed` auto-stamp.
- ✅ **Company research without a job link** — Organizations page gained a Research button per row.
- ✅ **UTF-8 mojibake fix** — child subprocess runs with `LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8`. No more `rÃ©sumÃ©` round-trips.
- ✅ **Settings stubs**: AI Persona has full CRUD + activate/deactivate. Data Export / Import is wired up via `/api/v1/admin/export` + `/api/v1/admin/import`.
- ✅ **Sidebar collapse / mobile layout**: drawer-style sidebar on viewports below `md`.
- ✅ **CORS / port flexibility** — `next.config.mjs` proxies `/api/*` and `/health/*` through the web origin.
- ✅ **Circular link reverse view** — `GET /history/links?either_type=X&either_id=N` returns links where the entity is on either side, normalized so the queried entity is always the `from_*` side.
- ✅ **OAuth debug-file cleanup** — `_prune_old_debug_files` runs at the start of every `claude setup-token` session; deletes `.bin` files older than 7 days while keeping the most recent 10.

## R7 — Job Leads ingest

- ✅ **Job sources + leads inbox** (migration 0019). `job_sources` and `job_leads` tables. Adapters for Greenhouse / Lever / Ashby / Workable / generic RSS / YC + Bright Data LinkedIn / Glassdoor (paid). Background poller fans out on a per-source schedule (`poll_interval_hours`) and writes deduped `JobLead` rows; leads expire after `lead_ttl_hours` if untouched. Bulk inbox UI at `/leads` lets the user **Add to tracker** (always lands at `to_review` so the review queue gates new rows) or **Dismiss**. Filters (title regex, location regex, remote-only) apply at ingest. Per-source `max_leads_per_poll` cap (migration 0022, default 100) keeps Bright Data / RSS volume bounded.
- ✅ **API key vault** — `ApiCredential` CRUD endpoints at `/api/v1/auth/credentials` + Settings panel. AES-256-GCM-encrypted at rest, list endpoint returns only last 4 chars. Used by Bright Data adapter today.
- ✅ **RSS Cloudflare bypass** — full Chrome-style User-Agent, `expect="feed"` checks for HTML interstitials, retries on transient transport errors, `/app/logs/source_errors.jsonl` log so the Companion can `tail -n 50` and diagnose silent 0-lead returns.
- ✅ **Promote = queue a fetch task** — lead promotion enqueues a `fetch` task on the lead's source_url instead of creating a TrackedJob immediately. Fetch handler updates the existing row when given `tracked_job_id` (enrich mode) and back-links the lead via `lead_id` payload.
- ✅ **Auto-chain follow-on tasks** — fetch completion enqueues a `score` task (JD analyze) and (if missing) an `org_research` task. New `org_research` queue handler shares `run_org_research_pipeline` with the HTTP endpoint.

## R8 — Deterministic fit-score

- ✅ **Replace the Companion-driven `fit_score` with a pure-Python weighted average** (migration 0020). Score is reproducible, free, and recomputed on every job create / update / JD-analyze. `app/scoring/fit.py` produces a `FitResult` with a per-component breakdown.
- ✅ **Eight built-in components**: salary, remote_policy, location, experience_level, employment_type, **skills** (matched required + 0.5× nice-to-have), travel, hours. Default weights editable per-user via `JobPreferences.builtin_weights`.
- ✅ **JobCriterion.weight** is first-class 0-100. Weight 0 = informational only. Weight 100 + tier=unacceptable + JD match = hard veto.
- ✅ Built-in components produce vetoes when the JD's value lands in the user's `..._unacceptable` lists.
- ✅ Persisted onto `tracked_jobs.fit_summary` as `{score, vetoed, veto_reason, breakdown[], summary, scored_by:"deterministic"}`.
- ✅ Endpoints: `POST /jobs/{id}/recompute-fit-score`, `POST /jobs/recompute-fit-score-all`.
- ✅ **Preferences page**: `BuiltinWeightsCard` with sliders + number inputs; criteria list rows with inline tier dropdown + 0-100 weight slider (🚫 indicator when veto-eligible). "Recompute fit scores" button on Criteria tab and Tracker toolbar.
- ✅ **Job detail**: `FitScoreBreakdownPanel` shows score, veto reason, per-component table. + Add on SkillsAnalysis triggers an immediate recompute.

## R9 — Email ingest

- ✅ **Paste-an-email → classify → suggest status change** (migration 0021). `parsed_emails` table logs every email run through the classifier with the Claude output, the matched tracked job (if any), and whether the suggestion was applied.
- ✅ Endpoints: `/api/v1/email-ingest/parse`, `/reparse`, `/apply`, `/dismiss`, list, delete.
- ✅ Classifier prompt produces a strict JSON shape: `intent` ∈ rejection / interview_invite / take_home_assigned / offer / withdrew / status_update / ghosted / unrelated, confidence, matched_job_id (verified to belong to the user before persist), suggested_status + suggested_event_type, key_dates, summary.
- ✅ Dedupes re-pastes via SHA-1 of from + subject + received_at + body.
- ✅ `/inbox` page: paste form on top, parsed-email list with state filters, review panel with override controls before clicking Apply.
- ✅ Apply persists an ApplicationEvent with the email's from / subject + a quoted-thread-stripped body snippet, then re-runs the deterministic fit-score.

## Cross-cutting features (across R7–R9)

- ✅ **Pagination on long lists** — reusable `<Paginator>` + `usePagination` hook (10 / 30 / 100 / All, default 30, per-page choice in localStorage). Wired into Tracker, Organizations, Skills.
- ✅ **Fetch queue trim + dismiss** — `done` rows on FetchQueuePanel + Companion Activity capped at the most recent 20. New "Dismiss completed" / "Dismiss errored" buttons.
- ✅ **Cmd-K command palette** — `CommandPalette` mounted at the app layout. ⌘/Ctrl+K opens. Hydrates jobs / orgs / docs / skills on first open, ranks substring + fuzzy matches.
- ✅ **Accessibility pass** — global `:focus-visible` ring, skip-to-content link, `aria-current="page"` and `aria-label` on the sidebar nav, `aria-modal` on the command palette, `<kbd>` styling.
- ✅ **Search jobs on the tracker page** — free-text filter input above the table.
- ✅ **Bulk status change on tracker** — labeled "Status" group in the multi-select bar with a status dropdown that PUTs every selected row.
- ✅ **Keyboard shortcuts on the review queue** — `1` = interested, `2` = not interested, `3` = skip, `j`/`k` = next/prev. Apply queue mirrored.
- ✅ **Salary expectation vs. listing comparison** — green/amber/red salary badge on tracker rows.
- ✅ **Commute / location fit badge** — fit / remote ok / outside-radius badge on tracker rows.
- ✅ **Skill-match heatmap on tracker** — sortable Skills column with bar + N/total + %.
- ✅ **Document tags** (migration 0017) — `tags` JSON array on `GeneratedDocument`, editable in the Studio with chip filter.
- ✅ **Resume version comparison** — Studio editor's diff panel has a left-side version picker.
- ✅ **Batch humanize on Studio** — multi-select bar + "Humanize all".
- ✅ **PDF export with proper page breaks** — `@page` rules + `page-break-after: avoid` on headings, `page-break-inside: avoid` on bullets/blockquotes/tables, orphans/widows on paragraphs.
- ✅ **Cover letter library** (migration 0018) — `cover_letter_snippets` table + CRUD + `/cover-letter-library` page filterable by kind.
- ✅ **Periodic gap audit + skill-stack suggestions** — Skills page has an "Applied / interview only" toggle on the missing-from-jobs audit and a "Skill stacks worth learning together" section.
- ✅ **Tracked-job archiving** — `POST /api/v1/jobs/auto-archive` (with preview) flips stale rows to archived (60d / 90d / 30d windows).
- ✅ **Application-to-response funnel by source** — `GET /api/v1/metrics/funnel-by-source` and a Dashboard table.
- ✅ **Browser extension stub** — Chromium MV3 scaffold under `apps/extension/`. Posts captured tab content as a `to_review` job.
- ✅ **Refined fetch pipeline** — JD fetch and company research both rewritten to "one direct httpx download → one no-tool Claude parse" instead of giving Claude WebFetch + WebSearch and watching it issue 20+ tool calls per posting.

## Documentation

- ✅ **README** — rewritten through R9 with links to `to-do.md` + `CHANGELOG.md`.
- ✅ **CHANGELOG.md** — Keep-a-Changelog style, organized by R-tag.
