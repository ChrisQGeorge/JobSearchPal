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

This is the **R0–R1 slice** from the SRS release plan.

- ✅ Docker stack (`db`, `api`, `web`) with healthy startup ordering and setup.sh bootstrap.
- ✅ All 36 SQLAlchemy models from SRS §1.2 Schemas, grouped by domain. An initial Alembic migration creates every table on first boot.
- ✅ Auth: register, login, logout, `GET /auth/me`. Argon2id password hashing, HTTP-only session cookie, JWT payload signed with `SESSION_SECRET`.
- ✅ Encryption helpers: `encrypt_secret` / `decrypt_secret` using AES-256-GCM with a key derived from `MASTER_SECRET` via HKDF-SHA256 (for the `ApiCredential` table, per SRS 3.3.2 DATA-002).
- ✅ Claude Code CLI installed in the API container (Node 20 + `@anthropic-ai/claude-code`), with `/health/claude` for reachability checks and `apps/api/app/skills/runner.py` as the subprocess wrapper.
- ✅ History CRUD endpoints for **WorkExperience, Education, Skill, Achievement**, plus a unified `GET /history/timeline` endpoint that feeds the Career Timeline page.
- ✅ Frontend: login / register flows, authenticated dashboard, Career Timeline, and a working **History Editor** with tabs for Work / Education / Skills / Achievements (create, edit, soft-delete).
- ✅ All navigation pages scaffolded — Job Tracker, Document Studio, Writing Samples, Companion, Preferences & Identity, Settings — with "Pending Corporate Approval" placeholders flagged by release wave.
- ✅ All 15 skills have a `SKILL.md` skeleton with frontmatter, inputs/outputs, and hard guardrails from the SRS.

## What is intentionally stubbed (future releases)

Following the SRS §2.6 apportioning table:

- **R2 – Job Tracking**: Job Tracker list, Job Detail view with InterviewRound + InterviewArtifact management, inline action buttons for skill invocation, JD paste-import.
- **R3 – AI Skills MVP**: Claude Code subprocess runner in `apps/api/app/skills/`, Companion Chat UI, resume-tailor, cover-letter-tailor, jd-analyzer, application-tracker, companion-persona wired end-to-end.
- **R4 – Humanization & Studio**: Document Studio, Writing Samples library, writing-humanizer, selection-rewriter, in-editor "Send to Companion" flow.
- **R5 – Analytics & Polish**: Dashboard charts against MetricSnapshot, persona gallery and custom persona editor, interview-prep + interview-retrospective, job-fit-scorer, application-autofiller, full Preferences & Identity forms.

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

The API container has the Claude Code CLI installed (`@anthropic-ai/claude-code`). It calls Claude with `claude -p --output-format json` via `apps/api/app/skills/runner.py`. Auth works in one of two ways:

1. **Claude Code OAuth (recommended).** Run `claude login` once on your host. `setup.sh` then points `CLAUDE_HOME` at the resulting config directory, and `docker-compose.yml` bind-mounts it to `/root/.claude` inside the container. The container reuses your subscription session — no per-token charges.
2. **Anthropic API key.** Set `ANTHROPIC_API_KEY` in `.env`. The runner propagates it as an env var to the CLI subprocess. This uses pay-per-token billing regardless of whether you also have a subscription.

Verify the CLI is reachable:

```bash
curl http://localhost:8000/health/claude
# {"claude_cli_available":true,"cli_bin":"claude","has_anthropic_api_key":false}
```

Caveats:
- The container runs as root, so anything Claude Code writes to `/root/.claude` will be owned by root on the host too. If that bothers you, make the mount read-only in `docker-compose.yml` (but then token refreshes won't persist).
- Auth token refresh is automatic when the bind-mount is read-write. Revoke via `claude logout` on the host.

## Security notes

- **Secrets**: `setup.sh` generates random 48-character secrets for `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`, `SESSION_SECRET`, and `MASTER_SECRET`, then writes `.env` with mode 0600.
- **At-rest encryption**: `ApiCredential.encrypted_secret` is AES-256-GCM. Do not change `MASTER_SECRET` after data has been written — you will lose access to the encrypted rows.
- **Cookies**: session cookie is `HttpOnly` and `SameSite=Lax`. Set `COOKIE_SECURE=true` when serving behind TLS.
- **Demographic data** (per SRS 3.6.3 DEMO-003): values are never transmitted to the LLM as free text. The `application-autofiller` flow uses local placeholder substitution after LLM processing.

## License

Personal use. No warranty, express or implied. Obviously.
