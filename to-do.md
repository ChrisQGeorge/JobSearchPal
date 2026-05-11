# Job Search Pal — To-Do

Open punch-list. For everything already shipped see [`done.md`](done.md).
Releases use the SRS §2.6 R-tag scheme (R0–R6) plus the out-of-band
milestones the project picked up along the way (R7 leads ingest, R8
deterministic fit-score, R9 email ingest, R10/R11 browser-piped
auto-apply).

## R10 / R11 — Companion-driven browser + auto-apply

**Status: parked.** The full R10/R11 work (streamed Chromium service,
apply_run agent loop, ATS templates, auto-apply poller, /browser /
/applications / /answers / /auto-apply pages, ask-user banner,
server-side PDF render) was stripped from `main` because the
constant polling on the panel + heartbeat + preview was visibly
slowing the rest of the app. The full implementation is preserved
on the `auto-apply-experiment` branch — `git checkout
auto-apply-experiment` to get it back, then re-merge once it's
re-architected to be cheaper at idle.

Migrations 0023 (browser_automation), 0024 (auto_apply_settings),
and 0025 (auto_apply_heartbeat) remain applied on existing
databases. The tables (application_run / application_run_step /
question_answer / auto_apply_settings) are orphans now — harmless,
and re-attaching to them is just restoring the matching model
file + routers from the branch.

What still needs design rework before bringing it back:

- [ ] **Cheaper idle path** — the panel polled /preview every 5s,
  fired a /heartbeat every 10s, and the background poller every
  5min. Even with no candidates the cumulative chatter slowed the
  app. Make all of it event-driven or much less frequent at idle.
- [ ] **Migration cleanup** — decide whether to drop the orphan
  tables or keep them for restore. A 0026 migration could either
  drop them or be a no-op marker.
- [ ] **Lever / Ashby / Workable templates** — the shape is in the
  branch (`apps/api/app/skills/apply_templates.py`).
- [ ] **Hard-coded Greenhouse smoke test** against one live posting.
- [ ] **Cost cap per run** (default $1).
- [ ] **HTTPS proxy stays on main** — Caddy reverse-proxies the web
  app on HTTPS_WEB_PORT with a self-signed cert generated at
  container startup. web + api are bound to 127.0.0.1 by default
  so the LAN can't reach plain HTTP.

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
