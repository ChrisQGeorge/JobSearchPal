# Job Search Pal

*A Claude Code–based companion for navigating your job search with ironic corporate flair.*

Job Search Pal helps you maintain a rich career history, track jobs through their full lifecycle, tailor application materials with AI, and keep the whole process lighthearted with a configurable persona. See [Job Search Pal  SRS.md](<Job Search Pal  SRS.md>) for the full design document.

## Stack

- **Backend**: FastAPI (Python 3.12) + SQLAlchemy 2 async + Alembic
- **Database**: MySQL 8
- **Frontend**: Next.js 15 (App Router) + React 19 + TypeScript + Tailwind CSS
- **AI runtime**: Claude Code CLI installed inside the API container and invoked as a subprocess. Auth comes from your existing `claude login` session (bind-mounted from the host's `~/.claude`), so no separate Anthropic API key is required.
- **Delivery**: Docker Compose; single `setup.sh` to bootstrap

## Quick start

Prerequisites: Docker Engine ≥ 24, Docker Compose v2, `bash`, and Claude Code installed and logged in on the host (`claude login`). If you'd rather use pay-per-token API access instead, you can provide `ANTHROPIC_API_KEY` — see the auth section below.

```bash
# One-time setup: generate secrets, discover your Claude Code config, build, launch.
./setup.sh

# Force API-key auth instead of Claude Code OAuth (optional):
ANTHROPIC_API_KEY=sk-ant-... ./setup.sh
```

Once containers are healthy:

- Web UI: http://localhost:3000
- API:   http://localhost:8000
- API docs: http://localhost:8000/docs

Shut down or uninstall:

```bash
docker compose down        # stop, keep data
./setup.sh --uninstall     # stop, prompt about volumes and .env
```

## Repository layout

```
.
├── Job Search Pal  SRS.md   # Software Requirements Specification
├── README.md                # this file
├── setup.sh                 # bootstrap script
├── docker-compose.yml
├── .env.example
├── apps/
│   ├── api/                 # FastAPI backend
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── alembic/         # migrations (initial at 0001_initial)
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── core/        # config, database, security, deps
│   │   │   ├── models/      # SQLAlchemy models (all 36 SRS schemas)
│   │   │   ├── schemas/     # Pydantic request/response models
│   │   │   └── api/v1/      # routers: auth, history
│   │   └── scripts/start.sh
│   └── web/                 # Next.js frontend
│       ├── Dockerfile
│       ├── package.json
│       └── src/
│           ├── app/
│           │   ├── layout.tsx
│           │   ├── globals.css
│           │   ├── login/page.tsx
│           │   ├── register/page.tsx
│           │   └── (app)/               # route group with sidebar
│           │       ├── layout.tsx
│           │       ├── page.tsx         # Dashboard
│           │       ├── timeline/
│           │       ├── history/
│           │       ├── jobs/
│           │       ├── studio/
│           │       ├── samples/
│           │       ├── companion/
│           │       ├── preferences/
│           │       └── settings/
│           ├── components/
│           └── lib/
└── skills/                  # Claude Code skill definitions (SKILL.md each)
    ├── README.md
    ├── resume-tailor/
    ├── cover-letter-tailor/
    ├── email-drafter/
    ├── jd-analyzer/
    ├── company-researcher/
    ├── history-interviewer/
    ├── application-tracker/
    ├── writing-humanizer/
    ├── interview-prep/
    ├── interview-retrospective/
    ├── job-strategy-advisor/
    ├── job-fit-scorer/
    ├── application-autofiller/
    ├── selection-rewriter/
    └── companion-persona/
```

## What works in this build

R0–R6 of the SRS plus three out-of-band milestones (R7 leads ingest,
R8 deterministic fit-score, R9 email inbox). See [`to-do.md`](to-do.md)
for the granular punch-list and [`CHANGELOG.md`](CHANGELOG.md) for the
release history.

### Core foundations (R0–R1)
- Docker stack (`db` + `api` + `web`) with healthy startup ordering and a one-shot `setup.sh` bootstrap.
- 36+ SQLAlchemy models, all migrations idempotent through `0021_parsed_emails`.
- Auth: register / login / logout, Argon2id passwords, HTTP-only JWT session cookie, bearer-token path for skills, in-UI Claude Code OAuth flow with `claude setup-token`.
- AES-256-GCM at-rest encryption for `ApiCredential` rows; HKDF-SHA256 key derivation from `MASTER_SECRET`.
- All 13 history entity types (Work / Education / Course / Skill / Cert / Language / Project / Publication / Presentation / Achievement / VolunteerWork / Contact / CustomEvent) with full CRUD.
- Polymorphic `entity_links` graph + dedicated skill-link tables with `usage_notes`.
- Career Timeline (greedy lane assignment, by-org + by-kind grouping, gap warnings).
- Resume profile + Demographics + Job Preferences + Work Authorization + Job Criteria, all with full UI.

### Job lifecycle (R2)
- Job Tracker with status pills, inline status change, multi-select bulk-status + bulk-tailor + auto-archive.
- Salary / location-fit / skill-match heatmap badges per row.
- Review Queue + Apply Queue with `1`/`2`/`3` and `j`/`k` keyboard shortcuts.
- Job detail tabs: Overview, Interview Rounds, Artifacts, Contacts, Documents, Activity.
- Excel bulk-import + URL-fetch (Claude WebFetch + WebSearch) → 30-field autofill.
- Background `job_fetch_queue` worker with rate-limit-aware backoff.

### Companion + skills (R3)
- Companion chat with Claude Code subprocess + `--resume`-based threading, SSE streaming, attachment uploads, cost / duration / turns metadata, persona gallery + active persona injection.
- 15 project skills mounted at `/app/skills/` and discovered by the CLI.
- jd-analyzer, resume-tailor, cover-letter-tailor, email-drafter, company-researcher, application-autofiller, interview-prep, interview-retrospective, job-strategy-advisor wired end-to-end.

### Document Studio (R4)
- `/studio` Studio editor with selection-based AI (rewrite / answer / new doc), parent-version threading, any-vs-any version diff, batch humanize, free-text tags, PDF page-break aware print stylesheet.
- Writing Samples Library (paste / .txt / .md upload, tags, full editor).
- Cover Letter Library (reusable hooks / bridges / closes / anecdotes / value-props).

### Analytics (R5)
- Dashboard with KPI tiles, status distribution, pipeline funnel, 30-day activity sparkline, application-to-response funnel by source, job-strategy-advisor.
- MetricSnapshot materialization, on-demand strategy briefings.

### Source ingest (R7)
- `/leads` page polls Greenhouse / Lever / Ashby / Workable / RSS / YC feeds on a per-source schedule, dedupes leads, surfaces them as a triage inbox. Bulk-promote interesting leads to TrackedJob (auto-queues a fit-score task).
- Per-source regex filters at ingest (title include / exclude, location include / exclude, remote-only).
- `/cover-letter-library` and the browser extension stub (`apps/extension/`, MV3) cover the offline ingest paths.

### Deterministic fit-score (R8)
- Pure-Python scoring engine in `app/scoring/fit.py` produces a 0-100 score with a per-component breakdown — no Claude call in the score path.
- Seven built-in components (salary, remote_policy, location, experience_level, employment_type, travel, hours) with default weights editable per-user.
- `JobCriterion.weight` is first-class 0-100; weight 100 + tier=unacceptable + matched JD = hard veto.
- Job detail surfaces a `FitScoreBreakdownPanel` showing why each row got the score it did.

### Email inbox (R9)
- `/inbox` page: paste an email body, the Companion classifies it (rejection / interview_invite / offer / take_home / status_update / unrelated), matches it to one of the user's tracked jobs, and proposes a status change + ApplicationEvent.
- User confirms (or overrides) before anything mutates a TrackedJob.
- Dedupes re-pastes via SHA-1 of from + subject + received + body.

### Cross-cutting
- Cmd-K command palette across jobs / orgs / docs / skills.
- Auto-memory: jobs / leads / emails recompute fit-score on any input change.
- Accessibility pass: skip-to-content, focus rings, sidebar `aria-current`, keyboard shortcuts on the queues.

## What's still on the punch list

Tracked in [`to-do.md`](to-do.md). Highlights:

- **Spend cap** (SRS REQ-COST-002) — gated on API-key billing; not needed for OAuth Pro sessions.
- **Observability** (SRS §3.3.5) — `/metrics` Prometheus endpoint, structured JSON logs with PII scrubbing.
- **Org soft-delete reassign workflow** — currently soft-deleted orgs leave dangling references in the timeline / history.
- README / CHANGELOG / `v0.1.0` tag — being chipped at; this paragraph itself was the README update.

## Development

### Backend

```bash
# Exec into the API container
docker compose exec api bash

# Run migrations manually
alembic upgrade head

# Create a new migration after editing models
alembic revision --autogenerate -m "describe change"
```

### Frontend

```bash
# Exec into the web container
docker compose exec web sh

# Or run locally outside Docker
cd apps/web
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

### Running without Docker

You can run the pieces directly — useful for fast iteration:

```bash
# API
cd apps/api
pip install -r requirements.txt
export $(cat ../../.env | xargs)
alembic upgrade head
uvicorn app.main:app --reload

# Web
cd apps/web
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Claude Code authentication

The API container has the Claude Code CLI installed (`@anthropic-ai/claude-code`) and stores its config in an isolated named Docker volume (`claude_config`). **It does not touch your personal `~/.claude` on the host** — no skills or sessions leak in either direction. You authenticate the container's own Claude Code session once.

Two options (pick one):

1. **Claude Code OAuth (recommended — uses your Claude subscription).** After the stack is up, run:

   ```bash
   docker compose exec -it api claude login
   ```

   The CLI prints the standard OAuth URL; open it in a browser, complete the flow, and the credentials persist in the container's config volume across restarts. Use `claude logout` inside the container to revoke.

2. **Anthropic API key (pay-per-token).** Set `ANTHROPIC_API_KEY` in `.env` and recreate the `api` container (`docker compose up -d api`). The runner propagates the key to the CLI subprocess. No login step needed.

Verify:

```bash
curl http://localhost:8000/health/claude
# {"claude_cli_available":true,"authenticated":true,"has_oauth_session":true,...}
```

The Companion page shows an inline banner if the container isn't authenticated yet, with the exact login command.

## Security notes

- **Secrets**: `setup.sh` generates random 48-character secrets for `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`, `SESSION_SECRET`, and `MASTER_SECRET`, then writes `.env` with mode 0600.
- **At-rest encryption**: `ApiCredential.encrypted_secret` is AES-256-GCM. Do not change `MASTER_SECRET` after data has been written — you will lose access to the encrypted rows.
- **Cookies**: session cookie is `HttpOnly` and `SameSite=Lax`. Set `COOKIE_SECURE=true` when serving behind TLS.
- **Demographic data** (per SRS 3.6.3 DEMO-003): values are never transmitted to the LLM as free text. The `application-autofiller` flow uses local placeholder substitution after LLM processing.

## License

Personal use. No warranty, express or implied. Obviously.
