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
- [ ] Timeline: optional grouping by role vs. kind.
- [ ] Optional: upgrade Achievement / Certification / Publication / VolunteerWork issuer / venue fields to use the `OrganizationCombobox` (schema change + migration; deferred because free-text is fine for now).
- [ ] Timeline: highlight entities with unresolved gaps (e.g., Work with no highlights).

### R2 — Job Tracking polish (medium)
- [ ] **Inline action buttons** on Job Detail header (Research Company / draft outreach email). JD Analyze + resume/cover-letter tailoring are already wired through tabs.

### R3 — Skills MVP (big — the main remaining work)
Project skill definitions already exist at `/skills/<name>/SKILL.md`. Wire them through the API → DB → UI so the user (and Companion) can invoke them.
- ✅ **jd-analyzer** — `POST /jobs/{id}/analyze-jd` wired; panel on Job Detail Overview.
- ✅ **resume-tailor / cover-letter-tailor / generic tailor** — all three now go through the unified `POST /documents/tailor/{job_id}` endpoint (the two legacy specific routes remain). Documents tab shows version list + viewer (copy / download-as-md / edit), Document Studio at `/studio` lists across all jobs.
  - [ ] Chain through `writing-humanizer` when R4 ships.
- ✅ **email-drafter** — the unified tailor endpoint handles `outreach_email`, `thank_you`, and `followup` doc types with a purpose-specific email prompt.
- ✅ **company-researcher** — `POST /organizations/{id}/research` populates research_notes / tech_stack_hints / reputation_signals (engineering culture, work-life balance, layoffs, recent news, red/green flags). UI on Job Detail Overview and the Organizations edit form.
- [ ] **application-tracker** skill: conversational ingestion of "I just applied to X" — proposes `TrackedJob` + `ApplicationEvent` diffs, writes on user confirmation.
- [ ] **history-interviewer** skill for filling gaps in user history.
- [ ] **companion-persona** wrapper — pass the active `Persona` into every skill invocation.
- [ ] Surface **skill invocations inline** in Companion chat — show "invoked: resume-tailor" pills with cost/duration.
- [ ] Stream Companion responses (`--output-format stream-json`) so the UI shows tokens as they arrive.
- [ ] Rich **`GeneratedDocument` editor** (inline edit, diff against previous version, one-click re-tailor-with-changes). Current viewer is read-only + copy/download.

### R4 — Humanization & Studio (big)
- ✅ **Writing Samples Library** CRUD page: paste-in, tag, `.txt`/`.md` upload. (`.pdf`/`.docx` extraction still pending — requires adding pypdf / python-docx deps.)
- [ ] **writing-humanizer** skill wired to the backend; default-on for cover letters and emails. Should read from `/documents/samples` and pick matching-tag samples as reference corpus.
- ✅ **Document Studio** (basic): `/studio` browses every GeneratedDocument with type/job filters, inline markdown edit, PDF/image preview, link back to job.
  - [ ] Regenerate / humanize / diff controls and `parent_version_id` threading (R4 proper).
- [ ] **Global editor "Send to Companion → rewrite selection"** — `selection-rewriter` skill, triggered from any rich-text editor, records `DocumentEdit` rows.
- [ ] **Interview Artifacts: file upload** — the Artifacts tab accepts pasted-text content + `file_url` today. Still missing: actual file upload into `/app/uploads` + mime sniffing so the user can drop a whiteboard photo / take-home .pdf in directly.

### R5 — Analytics, Preferences, Personas (medium-big)
- ✅ **Dashboard charts** — live KPI tiles (active apps, response rate, offers won, applied this week + 30-day), status-distribution bar chart, pipeline funnel, and a 30-day activity sparkline. Hand-rolled SVG, no chart lib dependency.
- [ ] **Preferences & Identity** forms (three panels): `JobPreferences` (three-tier scalars), `JobCriterion` list, `WorkAuthorization`, `Demographics` with per-field share policies.
- [ ] **job-fit-scorer** skill — compute `fit_summary` on every `TrackedJob`. Surface dealbreakers prominently in Job Tracker list.
- [ ] **application-autofiller** skill with placeholder substitution (no demographic data in LLM prompts).
- [ ] **Persona editor + gallery** in Settings; apply active persona globally.
- [ ] **interview-prep** and **interview-retrospective** skills. Interview-prep button on each `InterviewRound`.
- [ ] **job-strategy-advisor** reading from `MetricSnapshot`.
- [ ] `MetricSnapshot` materialization job (cron / on-demand).

## Known minor issues

- [ ] **UTF-8 mojibake** in Companion responses (e.g., `résumé` → `rÃ©sumÃ©`). ASCII is fine. Suspect double-encoding somewhere between subprocess stdout → FastAPI → JSON.
- [ ] **Organization soft-delete references**: the timeline/history still show the stale name when an org is soft-deleted (by design), but there's no "reassign or hard-delete" workflow yet.
- [ ] **Settings stubs**: "AI Persona" and "Data Export / Reset" placeholders still say Coming Soon.
- [ ] **Spend cap** (SRS REQ-COST-002): enforce a per-month LLM spend ceiling.
- [ ] **Observability** (SRS §3.3.5): `/metrics` Prometheus endpoint, structured JSON logs with PII scrubbing.
- ✅ **Sidebar collapse / mobile layout**: drawer-style sidebar on viewports below `md`, with a fixed hamburger top bar. Desktop layout unchanged.
- [ ] **Accessibility pass** (WCAG 2.1 AA per SRS §3.1.1): keyboard traversal audit, ARIA labels on charts (once charts exist), focus indicators in the combobox.
- [ ] **Streaming output** in the Companion — long replies drop as a single 5-second wait + full message.
- [ ] **Circular link cleanup**: no UI for "linked from" — if A links to B there's no reverse view on B.
- [ ] `/tmp/jsp-login-debug/*.bin` files inside the container's `claude_config` volume accumulate from OAuth runs; add a cleanup task.

## Non-code housekeeping

- [ ] Update the README's "What works" section to match reality.
- [ ] Add a proper `CHANGELOG.md` (SRS §3.5.10).
- [ ] Commit + tag `v0.1.0` once R3 skill wiring lands.
- [ ] Remove or rotate the seeded test user (`chris@example.com`) before first real use.
