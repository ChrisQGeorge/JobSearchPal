# Job Search Pal — To-Do

Open punch-list. For everything already shipped see [`done.md`](done.md).
Releases use the SRS §2.6 R-tag scheme (R0–R6) plus the out-of-band
milestones the project picked up along the way (R7 leads ingest, R8
deterministic fit-score, R9 email ingest, R10/R11 browser-piped
auto-apply).

## R10 — Companion-driven browser automation (foundation)

**Premise.** Run a single Chromium instance inside its own Docker
container. The user sees it through a streamed `/browser` page in the
web app. The Companion drives it programmatically over CDP / Playwright.
Both control planes hit the *same* browser session — same cookies, same
fingerprint — so from the website's perspective nothing distinguishes
"user driving" from "Companion driving." This is fully piped (no
extension); latency is acceptable because the workflow is "watch the
agent work, take over occasionally," not primary daily browsing.

The persistent profile volume is the moat: log into LinkedIn /
Greenhouse SSO / Workday once and stay logged in for every subsequent
application.

### R10.1 — Streamed Chromium service
- [ ] **`chromium` compose service** (`linuxserver/chromium` or
  `kasmweb/chrome`) with KasmVNC over websocket. Persistent
  `chromium_profile` volume mounted at `/config`. Not exposed to the
  host network — proxied through `api`.
- [ ] **`--remote-debugging-port=9222`** so Playwright can attach.
- [ ] **`/api/v1/browser/stream`** endpoint that proxies the noVNC
  websocket through `api`'s cookie auth + a short-lived JWT, so only
  the logged-in user can connect. Single-user only at this stage —
  multi-user wants per-user containers + a router.
- [ ] **`/browser` page** in Next that embeds the noVNC iframe + a
  status bar ("you're driving" / "Companion is driving" / paused).
  Includes a "Navigate to URL" form for ad-hoc browsing.
- [ ] **Operational guard rails**: profile volume backups (encrypted),
  per-app navigation history captured to the DB, configurable
  "max apps per day" rate limit (default 10).

### R10.2 — Companion control surface
- [ ] **Playwright tools** the Companion can call (mirrors the existing
  skill-primer tool surface):
  `browser_navigate(url)` ·
  `browser_click(selector | role | accessible-text)` ·
  `browser_type(selector, text)` ·
  `browser_screenshot()` (rate-limited; expensive) ·
  `browser_get_dom()` (accessibility tree dump for cheap reads) ·
  `ask_user(question)` (pauses run, posts to SSE bus, waits for
  answer) ·
  `record_answer(question, answer)` ·
  `submit_application(tracked_job_id)` (final action; logs
  `ApplicationEvent("submitted", source="companion")`).
- [ ] **`apply_run` queue kind** in `job_fetch_queue`. Worker pulls
  the row, navigates Chromium to the tracked job's `source_url`,
  starts the agent loop, caps at 50 actions / ~5 min wall-clock per
  run before forcing a checkpoint with the user.
- [ ] **Cost cap per run** (default $1) so a runaway loop can't drain
  credits / Pro budget.
- [ ] **Soft mutex toggles** — `POST /api/v1/browser/take-over` and
  `/release` flip a flag the agent checks each iteration; user
  keystrokes always work regardless.

### R10.3 — Question-bank
- [ ] **`question_answer` table** (migration TBD) with
  `(user_id, question_hash, question_text, answer, last_used_at,
  source)`. Unique on `(user_id, question_hash)` so the same
  question across two apps reuses the answer. `question_hash` is
  SHA-1 of normalized question text.
- [ ] **`/api/v1/question-bank` CRUD** + a `/answers` review page
  to delete / edit stored answers.
- [ ] **Pre-populate** from existing `AutofillLog` history so the
  first auto-apply doesn't start cold.
- [ ] **`ask_user` flow** writes the new answer back to the bank on
  the user's reply.

### R10.4 — Application run log
- [ ] **`application_run` table** — `(id, user_id, tracked_job_id,
  state ∈ queued|running|awaiting_user|submitted|failed,
  started_at, finished_at, transcript_path, screenshot_dir,
  cost_usd, error_message)`.
- [ ] **`application_run_step` table** — granular event log
  `(id, run_id, ts, kind ∈ navigate|fill|click|screenshot|ask_user|
  answer, payload_json, screenshot_url)`.
- [ ] **`/applications` page** mirroring `/leads`/`/queue` UX —
  list of runs by state, click a row to see transcript + screenshots
  + linked tracked job.
- [ ] **Notification surface** — desktop Web Notifications API
  opt-in on the dashboard so an `awaiting_user` state pings the
  user when the tab isn't focused.

## R11 — Auto-apply scope expansion

Each "ATS-aware" sub-bullet is the same shape as the leads adapters:
identify the ATS, drive its specific form, fall back to the generic
loop on anything else. Order chosen by hit rate against the leads
ingest population.

- [ ] **Greenhouse-aware apply path** — selector map for the
  Greenhouse application form (resume upload, cover-letter upload,
  standard demographic fields, custom-question loop). Hard-coded
  smoke test against one current Greenhouse posting before exposing
  on the tracker.
- [ ] **Lever-aware apply path** — same shape, Lever DOM.
- [ ] **Ashby-aware apply path** — same shape, Ashby DOM.
- [ ] **Workable-aware apply path** — same shape, Workable DOM.
- [ ] **Generic fallback** — agent loop with screenshot + DOM-tree
  reads only, no per-vendor selector hints. Triggers when the
  tracked job's source_url matches no known ATS.
- [ ] **Resume / cover letter PDF render** — server-side headless
  Chromium that renders Studio markdown to PDF with the existing
  print stylesheet, so the worker can attach files without
  round-tripping to the user's browser.
- [ ] **Re-application guard** — refuse to start an `apply_run` for
  a tracked job whose status is already past `to_review` (already
  applied / responded / interviewing / etc.).

## Carry-overs from earlier releases

These were low-priority before R10 and remain low-priority. Listed
here so they don't get lost.

- [ ] **Spend cap** (SRS REQ-COST-002) — enforce per-month LLM
  ceiling **only when using an API key**. OAuth Pro sessions have
  no per-turn cost, so the cap is a noop in that mode. Becomes
  more relevant once R10/R11 starts firing Computer-Use-style
  loops; should land before the generic fallback adapter.
- [ ] **Organization soft-delete reassign workflow** — soft-deleted
  orgs leave dangling references in the timeline / history.
  Reassign-or-hard-delete UI.
- [ ] **Observability** (SRS §3.3.5) — `/metrics` Prometheus
  endpoint, structured JSON logs with PII scrubbing.
- [ ] **Accessibility** — chart ARIA, combobox focus-trap polish.
  The tracker / queues / palette pass already shipped under R6.
- [ ] **Per-user spend cap on `score` tasks triggered by lead
  promotion** — defer until the parent spend-cap lands.
- [ ] **Chain tailored docs through `writing-humanizer`** — auto-run
  humanize on every fresh tailor output. The infra exists; the
  trigger is missing.

## Non-code housekeeping

- [ ] **Tag `v0.1.0`** after the next stable build cycle. Holding
  off until a real job-search session has surfaced the rough edges.
- [ ] **Rotate the seeded test user** (`chris@example.com`) before
  first real use. `setup.sh` prompts for a real account on first
  run; the seed user lingers if you skipped that.
