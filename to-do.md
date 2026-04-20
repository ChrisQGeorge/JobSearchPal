# Job Search Pal — To-Do

Snapshot of what's built vs. what's left, organized by the SRS §2.6 release plan. Items ordered roughly by value × how-much-they-unlock.

## Done

- ✅ **R0 — Infra.** Docker stack (`db` / `api` / `web`), `setup.sh` secret generation, Alembic migrations (`0001` + `0002`), Argon2 auth + JWT cookie, AES-GCM credential encryption, isolated `claude_config` volume, Claude Code CLI installed inside the `api` container.
- ✅ **R0 — Claude Code auth.** Full in-UI OAuth flow: *Launch login* button spawns `claude setup-token` under a PTY (proper `200×50` + `xterm-256color` so Ink renders cleanly), streams via SSE, captures the code via stdin, auto-extracts + persists the long-lived token, runner injects `CLAUDE_CODE_OAUTH_TOKEN` on every subprocess call. Settings page has auth status + Reset button. Paste-token fallback for when the flow misbehaves.
- ✅ **R1 — Four history entities** (Work / Education / Skills / Achievements) with full CRUD.
- ✅ **R1 — Organizations.** Monarch-style combobox, typeahead + create-on-enter, shared across Work / Education / (future) Jobs / Contacts. Usage counts per org.
- ✅ **R1 — Career Timeline.** Horizontal roadmap-style view with year axis, color-coded lanes per kind, parallel events stacked via greedy first-fit, single-date events rendered as markers, "present" markers for ongoing work, legend toggles.
- ✅ **R3 — Companion Chat.** Two-pane UI (conversations list + active chat), multi-turn threading via `--resume <claude_session_id>`, auto-title from first user message, error surfacing, delete conversation. End-to-end verified.

## What's left

### R1 — History polish (small-medium)
- [ ] UI forms for the remaining history entities already in the schema: **Courses** (under Education), **Certifications**, **Projects**, **Publications**, **Presentations**, **Volunteer Work**, **Languages**, **Contacts**, **Custom Events**. Backend models exist; just need routers + UI tabs in the History Editor and corresponding timeline entries.
- [ ] Timeline enhancements: date-range zoom/filter, "fit to content" button, optional grouping by role vs. kind.
- [ ] Let the Achievement / Certification / Publication / VolunteerWork forms use the Organization combobox for their issuer/venue fields (schema already supports).

### R2 — Job Tracking (big)
- [ ] **Job Tracker** list page: sortable/filterable table with status chips, bulk-add from URL, status filter pills.
- [ ] **Job Detail** page with tabs: Overview / Interview Rounds / Interview Artifacts / Contacts / Documents / Activity.
- [ ] **InterviewRound** + **InterviewArtifact** CRUD — schedule, record outcome, attach files (take-home, notes, feedback, offer letters).
- [ ] Inline action buttons in Job Detail (Generate Resume / Cover Letter / Email / JD Analysis / Company Research) that open a side-panel editor. Most of these wait on R3 skill wiring.
- [ ] `ApplicationEvent` timeline per job.
- [ ] Status-change history + stats feeding Dashboard metrics (R5).

### R3 — Skills MVP (big)
Project skills already live in `/skills/` as `SKILL.md` skeletons. Need to actually invoke them.
- [ ] Wire **resume-tailor**: endpoint takes a `tracked_job_id`, assembles a prompt from `WorkExperience`/`Skill`/etc., shells out through the runner, persists a `GeneratedDocument`.
- [ ] Wire **cover-letter-tailor** (same pattern; chains through humanizer when ready).
- [ ] Wire **jd-analyzer**: parse a posted JD into structured `jd_analysis` JSON on `TrackedJob`.
- [ ] Wire **application-tracker**: conversational ingestion of "I just applied to X" → creates/updates `TrackedJob` + `ApplicationEvent` after user confirmation (use the `diff-then-confirm` pattern).
- [ ] Wire **history-interviewer** for filling gaps in user history.
- [ ] **companion-persona** wrapper: pass the active `Persona` through to every skill invocation (Companion chat today uses Claude's default voice).
- [ ] Surface **skill invocations inline** in Companion chat — show "invoked: resume-tailor" pills with cost/duration.
- [ ] Stream Companion responses (`--output-format stream-json`) so the UI can show tokens as they arrive rather than waiting 2–5s for the final JSON.

### R4 — Humanization & Studio (big)
- [ ] **Writing Samples Library** CRUD page: upload `.txt`/`.md`/`.pdf`/`.docx`, tag, paste-in quick entry. Models exist.
- [ ] **writing-humanizer** skill wired to the backend; default-on for cover letters and emails.
- [ ] **Document Studio**: side-by-side source-history / generated-output editor, regenerate / humanize / diff controls, version history (`parent_version_id` is in the schema).
- [ ] **Global editor "Send to Companion → rewrite selection"**: the selection-rewriter skill, triggered from any rich-text editor in the app, recording `DocumentEdit` rows.

### R5 — Analytics, Preferences, Personas (medium-big)
- [ ] **Dashboard charts** (currently KPI placeholders): pie of application outcomes, funnel (applied → responded → interviewing → offer → accepted), bar by week, skills distribution, KPI tiles. Implementation: pick a charting lib (Recharts or Nivo) and feed from the read-side endpoints.
- [ ] **Preferences & Identity** forms (three panels per SRS §1.2 Pages): JobPreferences (three-tier scalars), JobCriterion list, WorkAuthorization, Demographics with per-field share policies.
- [ ] **job-fit-scorer** skill: read `JobPreferences` + `JobCriterion` + `jd_analysis`, produce `fit_summary` on every `TrackedJob`. Surface dealbreakers prominently in Job Tracker.
- [ ] **application-autofiller** skill with the placeholder-substitution rule (no demographic data in LLM prompts).
- [ ] **Persona editor + gallery** in Settings. Apply active persona globally to all skill outputs.
- [ ] **interview-prep** and **interview-retrospective** skills.
- [ ] **job-strategy-advisor** skill reading from `MetricSnapshot`.
- [ ] `MetricSnapshot` materialization job (cron / on-demand).

## Known minor issues to fix along the way

- [ ] **UTF-8 mojibake** in Companion responses (e.g., `résumé` → `rÃ©sumÃ©`). Plain ASCII is fine. Suspect double-encoding somewhere in the subprocess-stdout → FastAPI → JSON path; needs a targeted probe.
- [ ] **Organization deletion** is soft-delete and references stay. The timeline/history still show the stale name by design, but there's no "reassign or hard-delete" workflow.
- [ ] **Settings stubs**: "AI Persona" and "Data Export / Reset" placeholders still say Coming Soon.
- [ ] **Spend cap** (SRS REQ-COST-002): enforce a per-month LLM spend ceiling and refuse when exceeded. Token/cost metrics need to be surfaced on the dashboard too.
- [ ] **Observability** (SRS §3.3.5): `/metrics` Prometheus endpoint, structured JSON logs with PII scrubbing. Basic, not yet done.
- [ ] **Sidebar collapse / mobile layout.** The fixed 15-rem sidebar and centered 768-px+ layout don't play well on narrow viewports.
- [ ] **Accessibility pass** (WCAG 2.1 AA per SRS §3.1.1): keyboard traversal audit, ARIA labels on charts (once charts exist), focus indicators in the combobox.
- [ ] **Streaming output** in the Companion so long replies aren't a silent 5-second wait followed by a full-message drop. Also helps the per-skill UX.

## Non-code housekeeping

- [ ] Update the README's "What works" section to match reality after the Companion / Timeline / Organizations / auth-flow shipped.
- [ ] Add a proper `CHANGELOG.md` (SRS §3.5.10).
- [ ] Commit + tag `v0.1.0` once R1/R3 feel solid.
- [ ] Decide whether to keep `.claude-placeholder/` now that the volume is named — remove if redundant.
- [ ] Remove or rotate the seeded test user (`chris@example.com`) before first real use.
