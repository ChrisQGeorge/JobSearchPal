# Job Search Pal — To-Do

Open punch-list. For everything already shipped see [`done.md`](done.md).
Releases use the SRS §2.6 R-tag scheme (R0–R6) plus the out-of-band
milestones the project picked up along the way (R7 leads ingest, R8
deterministic fit-score, R9 email ingest, R10/R11 browser-piped
auto-apply).

## R10 — Companion-driven browser automation (foundation)

**Shipped** ✅. Streamed Chromium service, CDP plumbing through the
api container's cookie-auth, `apply_run` queue kind, full
question-bank, application-run log, and the `/browser` /
`/applications` / `/answers` pages all landed in the R10 build.

The persistent profile volume is the moat — log into LinkedIn /
Greenhouse SSO / Workday once and stay logged in for every subsequent
application. See `done.md` for the line-item history.

## R11 — Auto-apply scope expansion

**Shipped (initial cut):**

- [x] **Generic agent loop** — DOM read → Claude action → click /
  type / select / check / upload / screenshot → repeat. 50 action /
  5 min wall-clock cap. Pauses to user on novel questions.
- [x] **Greenhouse-aware template** — deterministic field-fill for
  first/last/email/phone/location/linkedin/github/portfolio. Falls
  through to the generic loop for everything else (custom
  questions, EEO, demographics).
- [x] **Server-side PDF render** — markdown-it-py → HTML →
  `page.pdf()` via the chromium service. New
  `POST /api/v1/documents/{id}/render-pdf` endpoint plus
  `kind=upload` action that picks the most recent tailored doc
  for the tracked job and attaches its PDF to a file input.
- [x] **Auto-apply queue** — `auto_apply_settings` table per user,
  background poller (5 min tick) that scans `interested` jobs and
  fires `apply_run` rows respecting daily cap, fit-score floor,
  pause window, and known-ATS-only mode. New `/auto-apply` page +
  `/api/v1/auto-apply/{settings,preview,run-now,today}` endpoints.
- [x] **Ask-user banner** — sticky top-of-page alert on every
  `(app)` route that polls for `state=awaiting_user` runs and
  fires desktop Web Notifications on rising-edge so the user gets
  pinged when the tab isn't focused.
- [x] **Re-application guard** — `apply_run` start refuses jobs
  whose status is already past `to_review`.

**Still open:**

- [ ] **Lever-aware apply path** — same shape as Greenhouse.
- [ ] **Ashby-aware apply path** — same shape.
- [ ] **Workable-aware apply path** — same shape.
- [ ] **Hard-coded Greenhouse smoke test** against one current
  posting once an active job-search session has provided one.
- [ ] **Cost cap per run** (default $1) so a runaway agent loop
  can't drain credits / Pro budget. Pairs with the SRS spend-cap
  carry-over.

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
