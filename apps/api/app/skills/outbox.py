"""Sol outbox: publish approved jobs to a private GitHub repo for the Sol
application agent, and read Sol's status records back.

Contract (docs/sol-outbox-contract.md, summarised):
  main    — written ONLY by us: jobs/<slug>/{job.json, resume.pdf,
            cover-letter.pdf, cover-letter.txt, withdrawn.json},
            applicant.json, README.md, .gitattributes. Add, never delete,
            never rewrite history, never force-push. One commit per job.
  status  — written ONLY by Sol: status/<slug>.json. We fetch it and read
            it with ls-tree / show; we never check it out or commit to it.

One sync = four phases, and NO database connection is held across the
slow git/network work (browsing must never stall):
  1. DB:  housekeeping (auto-approve, auto-withdraw), gather what to write.
  2. git: fetch, reset the local clone to origin/main, read origin/status.
  3. git: write + commit each job, pull --rebase, push. Jobs Sol already
          has a status record for are never rewritten.
  4. DB:  apply Sol's records (applied wins), mark what was published,
          store the report + last status-branch SHA.

The token lives in ApiCredential (provider "github_outbox") and reaches
git only through GIT_CONFIG_* environment variables — never argv, the
remote URL, .git/config, logs or error text (redacted defensively)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.models.documents import GeneratedDocument
from app.models.jobs import ApplicationEvent, Organization, TrackedJob
from app.models.outbox import OutboxConfig, OutboxJob

log = logging.getLogger(__name__)

PROVIDER = "github_outbox"
OUTBOX_ROOT = Path(os.environ.get("JSP_OUTBOX_DIR", "/app/uploads/outbox"))
SYNC_SECONDS = 300
GIT_TIMEOUT_SECONDS = 180
MAX_FILE_BYTES = 10 * 1024 * 1024  # Sol's upload limit
STATUS_FILE_MAX_BYTES = 64 * 1024
MAX_STATUS_RECORDS = 5000
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
STATUS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}\.json$")
JOB_REF_RE = re.compile(r"^jsp(\d{1,18})$")
SOL_STATUSES = ("applied", "skipped", "closed")

# Local statuses Sol's records may move a job out of. Anything at or past
# `applied` (responded, interviewing, offer, lost, …) is never touched.
PRE_APPLY = {
    "to_review", "reviewed", "watching", "interested", "contacted_by_recruiter",
    "awaiting_human", "in_progress", "not_interested", "archived",
}
# Moving an outboxed job here in JobSearchPal (before Sol acts) withdraws it.
WITHDRAW_ON = {"not_interested", "withdrawn", "archived", "lost"}

GITATTRIBUTES = "*.pdf binary\n*.docx binary\n"
README = """# JobSearchPal outbox

Approved jobs from JobSearchPal for the Sol application agent.

- `main` is written only by JobSearchPal: `jobs/<slug>/` holds `job.json`
  (schema v1), `resume.pdf`, optional `cover-letter.pdf` /
  `cover-letter.txt`, and `withdrawn.json` once a job is pulled back —
  skip any job that has it. `applicant.json` holds reusable form answers.
- `status` is written only by Sol: one `status/<slug>.json` per job
  (`schema_version`, `job_id`, `slug`, `status` = applied | skipped |
  closed, `at`, optional `confirmation` ≤200 chars, `note` ≤500 chars).
  JobSearchPal reads it on every sync; `applied` wins.

Full contract: "Jobsearchpal → Sol repo integration spec" (repo-integration-spec.md).
Nothing secret is ever committed here.
"""

APPLICANT_FIELDS = (
    "name", "email", "phone", "city_state", "work_authorization",
    "earliest_start", "salary_expectation",
)
APPLICANT_LINKS = ("linkedin", "github", "portfolio")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---- Slugs + job.json ------------------------------------------------------

def slug_part(raw: Optional[str], limit: int = 30) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (raw or "").lower()).strip("-")
    return s[:limit].strip("-")


def job_ref(tracked_job_id: int) -> str:
    return f"jsp{tracked_job_id}"


def make_slug(approved: datetime, company: Optional[str], title: Optional[str], ref: str) -> str:
    ref_part = slug_part(ref, 40) or "job"
    parts = [
        _aware(approved).astimezone(timezone.utc).strftime("%Y-%m-%d"),
        slug_part(company) or "unknown-company",
        slug_part(title) or "untitled",
        ref_part,
    ]
    slug = "-".join(parts)
    if len(slug) > 100:  # only possible with a very long ref; keep the ref
        head = "-".join(parts[:3])[: 100 - len(ref_part) - 1].strip("-")
        slug = f"{head}-{ref_part}"
    return slug


def _salary(job: TrackedJob) -> Optional[str]:
    lo, hi = job.salary_min, job.salary_max
    if lo is None and hi is None:
        return None
    cur = (job.salary_currency or "").upper()
    sym = "$" if cur in ("", "USD") else ""
    tail = "" if cur in ("", "USD") else f" {cur}"
    fmt = lambda v: f"{sym}{float(v):,.0f}"  # noqa: E731
    if lo is not None and hi is not None and float(lo) != float(hi):
        return f"{fmt(lo)}-{fmt(hi)}{tail}"
    return f"{fmt(lo if lo is not None else hi)}{tail}"


def _https(url: Optional[str]) -> Optional[str]:
    u = (url or "").strip()
    return u if u.lower().startswith("https://") and len(u) <= 2048 else None


def build_job_json(ob: OutboxJob, job: TrackedJob, company: Optional[str], has_cover: bool) -> dict:
    out: dict[str, Any] = {
        "schema_version": 1,
        "id": ob.job_ref,
        "slug": ob.slug,
        "title": job.title,
        "company": company or "Unknown company",
        "apply_url": _https(job.source_url),
    }
    optional = {
        "source": job.source_platform,
        "location": job.location,
        "workplace": job.remote_policy if job.remote_policy in ("remote", "hybrid", "onsite") else None,
        "employment_type": (job.employment_type or "").replace("_", "-") or None,
        "salary": _salary(job),
        "description": (job.job_description or "")[:100_000] or None,
    }
    out.update({k: v for k, v in optional.items() if v})
    out["approved_at"] = _aware(ob.approved_at).isoformat()
    out["files"] = {
        "resume": "resume.pdf",
        "cover_letter": "cover-letter.pdf" if has_cover else None,
    }
    if (ob.notes or "").strip():
        out["notes"] = ob.notes.strip()
    return out


def build_applicant(raw: Optional[dict]) -> Optional[dict]:
    """applicant.json from the saved form — whitelisted fields only, so a
    secret can't ride along. None when nothing is filled in."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {"schema_version": 1}
    for k in APPLICANT_FIELDS:
        v = str(raw.get(k) or "").strip()
        if v:
            out[k] = v[:300]
    links = raw.get("links") if isinstance(raw.get("links"), dict) else {}
    links = {k: str(links.get(k) or "").strip()[:500] for k in APPLICANT_LINKS}
    links = {k: v for k, v in links.items() if v}
    if links:
        out["links"] = links
    if isinstance(raw.get("needs_sponsorship"), bool):
        out["needs_sponsorship"] = raw["needs_sponsorship"]
    vd = raw.get("voluntary_disclosures")
    out["voluntary_disclosures"] = vd if vd in ("ask", "decline") else "ask"
    if len(out) <= 2 and out["voluntary_disclosures"] == "ask":
        return None
    return out


def md_to_text(md: str) -> str:
    """Cover letter markdown → plain text for form text boxes."""
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", md)
    s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(?<![\w*])[*_](?!\s)(.+?)(?<!\s)[*_](?![\w*])", r"\1", s)
    s = re.sub(r"^\s*[-*]\s+", "- ", s, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", s).strip() + "\n"


def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


# ---- Status records (untrusted) ---------------------------------------------

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(v: Any, limit: int) -> Optional[str]:
    if not isinstance(v, str):
        return None
    v = _CTRL.sub("", v).strip()
    return v[:limit] or None


def _parse_at(v: Any) -> Optional[datetime]:
    if not isinstance(v, str) or len(v) > 40:
        return None
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(dt)


def parse_status_record(name: str, raw: bytes) -> tuple[Optional[dict], Optional[str]]:
    """(record, None) or (None, why-skipped). Unknown fields are ignored;
    strings are control-stripped and capped."""
    if not STATUS_NAME_RE.match(name):
        return None, "file name is not <slug>.json"
    if len(raw) > STATUS_FILE_MAX_BYTES:
        return None, f"file is over {STATUS_FILE_MAX_BYTES // 1024} KB"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"not valid JSON ({str(exc)[:120]})"
    if not isinstance(data, dict):
        return None, "not a JSON object"
    if data.get("schema_version") != 1:
        return None, "schema_version is not 1"
    job_id = _clean(data.get("job_id"), 40)
    if not job_id:
        return None, "job_id missing"
    status = data.get("status")
    if status not in SOL_STATUSES:
        return None, "status is not applied / skipped / closed"
    at = _parse_at(data.get("at"))
    if at is None:
        return None, "at is not an ISO 8601 timestamp"
    slug = _clean(data.get("slug"), 120)
    if not slug:
        return None, "slug missing"
    return {
        "file": name,
        "job_id": job_id,
        "slug": slug,
        "status": status,
        "at": at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "at_dt": at,
        "confirmation": _clean(data.get("confirmation"), 200),
        "note": _clean(data.get("note"), 500),
    }, None


# ---- git -----------------------------------------------------------------------

class GitError(RuntimeError):
    pass


def remote_url(repo: str) -> str:
    """HTTPS remote for `owner/name` — tests point this at a local bare repo."""
    return f"https://github.com/{repo}.git"


class Git:
    def __init__(self, workdir: Path, token: str, author: tuple[str, str]):
        self.dir = workdir
        self._secrets = [s for s in (token,) if s]
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        self._secrets.append(basic)
        env = dict(os.environ)
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": "",
                "SSH_ASKPASS": "",
                # Token only via env-supplied config: no argv, no .git/config.
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
                "GIT_CONFIG_KEY_1": "credential.helper",
                "GIT_CONFIG_VALUE_1": "",
                "GIT_AUTHOR_NAME": author[0],
                "GIT_AUTHOR_EMAIL": author[1],
                "GIT_COMMITTER_NAME": author[0],
                "GIT_COMMITTER_EMAIL": author[1],
            }
        )
        self.env = env

    def redact(self, text: str) -> str:
        for s in self._secrets:
            if s:
                text = text.replace(s, "***")
        return text

    async def raw(self, *args: str, check: bool = True) -> tuple[int, bytes, str]:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(self.dir),
            env=self.env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), GIT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise GitError(f"git {args[0]} timed out after {GIT_TIMEOUT_SECONDS}s")
        err_s = self.redact(err.decode("utf-8", "replace")).strip()
        if check and proc.returncode != 0:
            raise GitError(f"git {args[0]} failed (exit {proc.returncode}): {err_s[-1500:]}")
        return proc.returncode, out, err_s

    async def run(self, *args: str, check: bool = True) -> str:
        _, out, _ = await self.raw(*args, check=check)
        return out.decode("utf-8", "replace").strip()

    async def ok(self, *args: str) -> bool:
        rc, _, _ = await self.raw(*args, check=False)
        return rc == 0


def clone_dir(user_id: int) -> Path:
    return OUTBOX_ROOT / str(user_id) / "repo"


async def prepare_clone(git: Git, url: str) -> bool:
    """Fetch and reset the local clone to origin/main (or an empty orphan
    `main` when the repo has none yet). Returns whether origin/main exists.
    Local state is disposable: anything not pushed is rebuilt from the DB."""
    git.dir.mkdir(parents=True, exist_ok=True)
    if (git.dir / ".git").is_dir():
        current = await git.run("remote", "get-url", "origin", check=False)
        if current != url:
            shutil.rmtree(git.dir, ignore_errors=True)
            git.dir.mkdir(parents=True, exist_ok=True)
    if not (git.dir / ".git").is_dir():
        await git.run("init", "-q")
        await git.run("remote", "add", "origin", url)
    await git.run("fetch", "-q", "--prune", "origin")
    has_main = await git.ok("rev-parse", "--verify", "-q", "refs/remotes/origin/main^{commit}")
    if has_main:
        await git.run("checkout", "-q", "-f", "-B", "main", "refs/remotes/origin/main")
        await git.run("reset", "-q", "--hard", "refs/remotes/origin/main")
    else:
        await git.run("symbolic-ref", "HEAD", "refs/heads/main")
        await git.raw("update-ref", "-d", "refs/heads/main", check=False)
        await git.run("read-tree", "--empty")
    await git.run("clean", "-q", "-f", "-d", "-x")
    return has_main


async def read_status_branch(git: Git) -> tuple[Optional[str], list[tuple[str, bytes]]]:
    """(sha, [(file name, bytes)]) from origin/status; (None, []) when the
    branch doesn't exist yet. Read-only: ls-tree + show, no checkout."""
    if not await git.ok("rev-parse", "--verify", "-q", "refs/remotes/origin/status^{commit}"):
        return None, []
    sha = await git.run("rev-parse", "refs/remotes/origin/status")
    listing = await git.run("ls-tree", "--name-only", "refs/remotes/origin/status", "status/")
    files: list[tuple[str, bytes]] = []
    for path in listing.splitlines()[:MAX_STATUS_RECORDS]:
        name = path.rsplit("/", 1)[-1]
        rc, blob, _ = await git.raw("show", f"refs/remotes/origin/status:status/{name}", check=False)
        if rc == 0:
            files.append((name, blob[: STATUS_FILE_MAX_BYTES + 1]))
        else:
            files.append((name, b""))
    return sha, files


def existing_job_folders(root: Path) -> dict[str, str]:
    """job ref → folder name for every jobs/<slug>/job.json on main."""
    out: dict[str, str] = {}
    jobs = root / "jobs"
    if not jobs.is_dir():
        return out
    for d in jobs.iterdir():
        jf = d / "job.json"
        if not jf.is_file():
            continue
        try:
            ref = json.loads(jf.read_text("utf-8")).get("id")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(ref, str) and d.name.endswith(f"-{slug_part(ref, 40)}"):
            out[ref] = d.name
    return out


async def commit_if_changed(git: Git, paths: list[str], message: str) -> bool:
    await git.run("add", "-A", "--", *paths)
    if await git.ok("diff", "--cached", "--quiet"):
        return False
    await git.run("commit", "-q", "-m", message)
    return True


# ---- Sync -------------------------------------------------------------------------

@dataclass
class Item:
    """One outbox job's planned write, gathered in phase 1."""
    ob_id: int
    ref: str
    slug: str
    published: bool
    published_files: dict
    sol_status: Optional[str]
    withdrawn: Optional[dict] = None  # {"withdrawn_at", "reason"} to publish
    job_json: Optional[dict] = None
    sources: dict[str, dict] = field(default_factory=dict)  # file → {hash, md, title, kind}
    error: Optional[str] = None


async def _render_pdf_default(title: str, md: str) -> bytes:
    from app.api.v1.documents import _render_doc_pdf_sync

    return await asyncio.to_thread(_render_doc_pdf_sync, title, md)


render_pdf: Callable[[str, str], Awaitable[bytes]] = _render_pdf_default


def _session_factory():
    from app.core.database import BgSessionLocal

    return BgSessionLocal


async def latest_docs(db, user_id: int, job_ids: list[int]) -> dict[tuple[int, str], GeneratedDocument]:
    """Newest resume / cover letter WITH text per job (an empty newest
    version is still generating — fall back to the previous one)."""
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(GeneratedDocument)
            .where(
                GeneratedDocument.user_id == user_id,
                GeneratedDocument.tracked_job_id.in_(job_ids),
                GeneratedDocument.deleted_at.is_(None),
                GeneratedDocument.doc_type.in_(("resume", "cover_letter")),
            )
            .order_by(GeneratedDocument.version.desc(), GeneratedDocument.id.desc())
        )
    ).scalars().all()
    out: dict[tuple[int, str], GeneratedDocument] = {}
    for d in rows:
        if (d.content_md or "").strip():
            out.setdefault((d.tracked_job_id, d.doc_type), d)
    return out


def eligibility(job: TrackedJob, has_resume: bool) -> Optional[str]:
    """Why a job can't be sent, or None."""
    if not has_resume:
        return "Needs a resume tailored to this job (with text) first."
    if not _https(job.source_url):
        return "Needs an https:// posting / apply URL."
    return None


async def approve(db, user_id: int, job: TrackedJob, notes: Optional[str] = None) -> OutboxJob:
    """Create the outbox row (idempotent). Caller commits."""
    ref = job_ref(job.id)
    ob = (
        await db.execute(select(OutboxJob).where(OutboxJob.user_id == user_id, OutboxJob.job_ref == ref))
    ).scalar_one_or_none()
    if ob is not None:
        if notes is not None and not ob.published_at:
            ob.notes = notes.strip() or None
        return ob
    company = None
    if job.organization_id:
        company = (
            await db.execute(select(Organization.name).where(Organization.id == job.organization_id))
        ).scalar_one_or_none()
    when = now_utc()
    ob = OutboxJob(
        user_id=user_id,
        tracked_job_id=job.id,
        job_ref=ref,
        slug=make_slug(when, company, job.title, ref),
        notes=(notes or "").strip() or None,
        approved_at=when,
    )
    db.add(ob)
    await db.flush()
    return ob


async def _housekeeping(db, user_id: int, cfg: dict) -> None:
    """Auto-withdraw jobs moved out of the pipeline (or deleted) before Sol
    acted; auto-approve `interested` jobs when that setting is on."""
    rows = (
        await db.execute(
            select(OutboxJob, TrackedJob.status)
            .outerjoin(TrackedJob, TrackedJob.id == OutboxJob.tracked_job_id)
            .where(OutboxJob.user_id == user_id, OutboxJob.withdrawn_at.is_(None), OutboxJob.sol_status.is_(None))
        )
    ).all()
    for ob, status in rows:
        if ob.tracked_job_id is None:
            ob.withdrawn_at, ob.withdraw_reason = now_utc(), "Job deleted in JobSearchPal."
        elif status in WITHDRAW_ON:
            ob.withdrawn_at, ob.withdraw_reason = now_utc(), f"Status changed to {status} in JobSearchPal."

    if cfg.get("auto_approve"):
        have = set(
            (await db.execute(select(OutboxJob.tracked_job_id).where(OutboxJob.user_id == user_id))).scalars()
        )
        jobs = (
            await db.execute(
                select(TrackedJob).where(TrackedJob.user_id == user_id, TrackedJob.status == "interested")
            )
        ).scalars().all()
        jobs = [j for j in jobs if j.id not in have]
        docs = await latest_docs(db, user_id, [j.id for j in jobs])
        for j in jobs:
            if eligibility(j, (j.id, "resume") in docs) is None:
                await approve(db, user_id, j)


async def _gather(db, user_id: int) -> list[Item]:
    obs = (
        await db.execute(select(OutboxJob).where(OutboxJob.user_id == user_id).order_by(OutboxJob.id))
    ).scalars().all()
    job_ids = [o.tracked_job_id for o in obs if o.tracked_job_id]
    jobs = {
        j.id: j
        for j in (
            await db.execute(select(TrackedJob).where(TrackedJob.id.in_(job_ids)))
        ).scalars().all()
    } if job_ids else {}
    org_ids = {j.organization_id for j in jobs.values() if j.organization_id}
    orgs = dict(
        (await db.execute(select(Organization.id, Organization.name).where(Organization.id.in_(org_ids)))).all()
    ) if org_ids else {}
    docs = await latest_docs(db, user_id, list(jobs))

    items: list[Item] = []
    for ob in obs:
        it = Item(
            ob_id=ob.id, ref=ob.job_ref, slug=ob.slug, published=ob.published_at is not None,
            published_files=dict(ob.published_files or {}), sol_status=ob.sol_status,
        )
        if ob.withdrawn_at is not None:
            if it.published and ob.withdrawn_published_at is None:
                it.withdrawn = {
                    "withdrawn_at": _aware(ob.withdrawn_at).isoformat(),
                    "reason": ob.withdraw_reason,
                }
                items.append(it)
            continue  # withdrawn before publishing → never published
        job = jobs.get(ob.tracked_job_id)
        if job is None:
            continue
        resume = docs.get((job.id, "resume"))
        cover = docs.get((job.id, "cover_letter"))
        why = eligibility(job, resume is not None)
        if why:
            it.error = why
            items.append(it)
            continue
        it.job_json = build_job_json(ob, job, orgs.get(job.organization_id), cover is not None)
        it.sources["job.json"] = {"hash": _sha(_dumps(it.job_json))}
        it.sources["resume.pdf"] = {
            "hash": _sha(str(resume.id), resume.title or "", resume.content_md),
            "md": resume.content_md, "title": resume.title or "Resume", "kind": "pdf",
        }
        if cover is not None:
            ch = _sha(str(cover.id), cover.title or "", cover.content_md)
            it.sources["cover-letter.pdf"] = {
                "hash": ch, "md": cover.content_md, "title": cover.title or "Cover letter", "kind": "pdf",
            }
            it.sources["cover-letter.txt"] = {"hash": ch, "md": cover.content_md, "kind": "txt"}
        if it.published and all(
            it.published_files.get(k) == v["hash"] for k, v in it.sources.items()
        ) and set(it.published_files) <= set(it.sources):
            continue  # on main and unchanged
        items.append(it)
    return items


async def _write_item(git: Git, it: Item, folder: Path, only: Optional[set[str]] = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, src in it.sources.items():
        if only is not None and name not in only:
            continue
        if name == "job.json":
            data = _dumps(it.job_json).encode("utf-8")
        elif src["kind"] == "pdf":
            data = await render_pdf(src["title"], src["md"])
        else:
            data = md_to_text(src["md"]).encode("utf-8")
        if len(data) >= MAX_FILE_BYTES:
            raise GitError(f"{name} is {len(data) / 1e6:.1f} MB — over Sol's 10 MB limit")
        (folder / name).write_bytes(data)
    # A cover letter that was deleted since: drop its stale files.
    for stale in ("cover-letter.pdf", "cover-letter.txt"):
        if stale not in it.sources and (folder / stale).exists():
            (folder / stale).unlink()


async def _publish(git: Git, items: list[Item], applicant: Optional[dict], acted: set[str], has_main: bool, report: dict) -> dict[int, dict]:
    """Phase 3. Returns ob_id → result for phase 4. Nothing is reported as
    published unless the push succeeded."""
    root = git.dir
    results: dict[int, dict] = {}
    commits = 0

    for name, body in (("README.md", README), (".gitattributes", GITATTRIBUTES)):
        if not (root / name).exists():
            (root / name).write_text(body, "utf-8")
    if await commit_if_changed(git, ["README.md", ".gitattributes"], "repo: add contract files"):
        commits += 1

    ap = root / "applicant.json"
    if applicant is not None:
        ap.write_text(_dumps(applicant), "utf-8")
        if await commit_if_changed(git, ["applicant.json"], "applicant: update"):
            commits += 1
    elif ap.exists():
        ap.unlink()
        if await commit_if_changed(git, ["applicant.json"], "applicant: remove"):
            commits += 1

    folders = existing_job_folders(root)
    for it in items:
        if it.error:
            results[it.ob_id] = {"error": it.error}
            continue
        try:
            existing = folders.get(it.ref)
            if it.withdrawn is not None:
                if existing is None:
                    results[it.ob_id] = {"withdrawn_published": True}
                    continue
                wf = root / "jobs" / existing / "withdrawn.json"
                if not wf.exists():
                    wf.write_text(_dumps(it.withdrawn), "utf-8")
                    if await commit_if_changed(git, [f"jobs/{existing}"], f"job: withdraw {existing}"):
                        commits += 1
                        report["withdrawn"].append(existing)
                results[it.ob_id] = {"withdrawn_published": True}
                continue

            if existing is not None and not it.published:
                # On main already (an earlier push whose DB write was lost):
                # adopt it as-is rather than adding a duplicate.
                results[it.ob_id] = {"published": True, "slug": existing,
                                     "files": {k: v["hash"] for k, v in it.sources.items()}}
                continue
            if existing is None:
                folder = root / "jobs" / it.slug
                await _write_item(git, it, folder)
                if await commit_if_changed(git, [f"jobs/{it.slug}"], f"job: add {it.slug}"):
                    commits += 1
                    report["added"].append(it.slug)
                results[it.ob_id] = {"published": True, "slug": it.slug,
                                     "files": {k: v["hash"] for k, v in it.sources.items()}}
                continue
            # Published and changed: rewrite only while Sol hasn't acted.
            if it.sol_status or it.ref in acted:
                continue
            changed = {k for k, v in it.sources.items() if it.published_files.get(k) != v["hash"]}
            await _write_item(git, it, root / "jobs" / existing, only=changed)
            if await commit_if_changed(git, [f"jobs/{existing}"], f"job: update {existing}"):
                commits += 1
                report["updated"].append(existing)
            results[it.ob_id] = {"published": True, "slug": existing,
                                 "files": {k: v["hash"] for k, v in it.sources.items()}}
        except GitError as exc:
            # Drop this job's half-written files; earlier commits stay.
            results[it.ob_id] = {"error": str(exc)}
            await git.raw("reset", "-q", "--hard", check=False)
            await git.raw("clean", "-q", "-f", "-d", check=False)

    if commits:
        if has_main:
            await git.run("pull", "-q", "--rebase", "origin", "main")
        await git.run("push", "-q", "origin", "main")
        report["pushed_commits"] = commits
    return results


async def _apply_records(db, user_id: int, records: list[dict], report: dict) -> None:
    """Phase 4a: Sol's records → local status. Idempotent; applied wins."""
    if not records:
        return
    obs = {
        o.job_ref: o
        for o in (
            await db.execute(select(OutboxJob).where(OutboxJob.user_id == user_id))
        ).scalars().all()
    }
    for rec in records:
        ob = obs.get(rec["job_id"])
        if ob is None:
            report["skipped_records"].append({"file": rec["file"], "reason": f"no outbox job with id {rec['job_id']}"})
            log.warning("outbox: user %s status/%s skipped — no outbox job %r", user_id, rec["file"], rec["job_id"])
            continue
        if ob.sol_status == rec["status"] and ob.sol_status_at == rec["at"]:
            continue  # already applied
        if ob.sol_status == "applied" and rec["status"] != "applied":
            continue  # applied wins
        ob.sol_status = rec["status"]
        ob.sol_status_at = rec["at"]
        ob.sol_confirmation = rec["confirmation"]
        ob.sol_note = rec["note"]
        report["status_applied"].append({"slug": ob.slug, "status": rec["status"]})

        job = await db.get(TrackedJob, ob.tracked_job_id) if ob.tracked_job_id else None
        if job is None or job.user_id != user_id:
            continue
        target = {"applied": "applied", "skipped": "not_interested", "closed": "archived"}[rec["status"]]
        movable = PRE_APPLY if target == "applied" else PRE_APPLY - {"not_interested", "archived"}
        prev = job.status
        if prev in movable and prev != target:
            job.status = target
            if target == "applied" and job.date_applied is None:
                job.date_applied = rec["at_dt"].date()
        bits = [f"Sol reported `{rec['status']}`"]
        if prev != job.status:
            bits.append(f"moved from `{prev}` to `{job.status}`")
        if rec["confirmation"]:
            bits.append(f"confirmation: {rec['confirmation']}")
        if rec["note"]:
            bits.append(f"note: {rec['note']}")
        db.add(
            ApplicationEvent(
                tracked_job_id=job.id,
                event_type="status_change" if prev != job.status else "note",
                event_date=rec["at_dt"],
                details_md=" — ".join(bits),
            )
        )


def _new_report() -> dict:
    return {
        "at": now_utc().isoformat(), "ok": True, "status_branch": None,
        "added": [], "updated": [], "withdrawn": [], "pushed_commits": 0,
        "status_applied": [], "skipped_records": [], "job_errors": [], "error": None,
    }


_LOCKS: dict[int, asyncio.Lock] = {}
_RERUN: set[int] = set()
_TASKS: dict[int, asyncio.Task] = {}


def is_running(user_id: int) -> bool:
    lock = _LOCKS.get(user_id)
    return bool(lock and lock.locked())


async def sync_user(user_id: int, session_factory=None) -> Optional[dict]:
    """Run one full sync for a user. Returns the report (None if the
    outbox isn't connected). Never raises for git/network failures — they
    land in the report (verbose) and the next sync tries again."""
    lock = _LOCKS.setdefault(user_id, asyncio.Lock())
    async with lock:
        return await _sync_locked(user_id, session_factory or _session_factory())


async def _sync_locked(user_id: int, Session) -> Optional[dict]:
    from app.api.v1.api_credentials import get_user_secret

    report = _new_report()
    # Phase 1 — DB.
    async with Session() as db:
        row = await db.get(OutboxConfig, user_id)
        cfg = dict(row.config) if row else {}
        repo = cfg.get("repo")
        token = await get_user_secret(db, user_id, PROVIDER) if repo else None
        if not repo or not token:
            return None
        await _housekeeping(db, user_id, cfg)
        await db.commit()
        items = await _gather(db, user_id)
        last_sha = (row.state or {}).get("last_status_sha")
        applicant = build_applicant(cfg.get("applicant"))
        login = cfg.get("login") or "jobsearchpal"
        author = (
            (cfg.get("author_name") or "JobSearchPal").strip()[:100],
            (cfg.get("author_email") or f"{login}@users.noreply.github.com").strip()[:200],
        )
        await db.commit()

    git = Git(clone_dir(user_id), token, author)
    records: list[dict] = []
    status_sha: Optional[str] = None
    results: dict[int, dict] = {}
    try:
        # Phase 2 — fetch + status branch.
        has_main = await prepare_clone(git, remote_url(repo))
        status_sha, files = await read_status_branch(git)
        if status_sha is None:
            report["status_branch"] = "missing"
        elif status_sha == last_sha:
            report["status_branch"] = "unchanged"
        else:
            report["status_branch"] = status_sha[:12]
        acted: set[str] = set()
        for name, blob in files:
            rec, why = parse_status_record(name, blob)
            if rec is None:
                report["skipped_records"].append({"file": name[:140], "reason": why})
                if status_sha != last_sha:  # log once per new status commit
                    log.warning("outbox: user %s status/%s skipped — %s", user_id, name[:140], why)
                continue
            acted.add(rec["job_id"])
            if status_sha != last_sha:
                records.append(rec)
        # Phase 3 — publish.
        results = await _publish(git, items, applicant, acted, has_main, report)
    except GitError as exc:
        report["ok"] = False
        report["error"] = git.redact(str(exc))
        log.warning("outbox: user %s sync failed: %s", user_id, report["error"])
        results = {k: v for k, v in results.items() if "error" in v}
    except Exception as exc:  # pragma: no cover — keep the loop alive
        report["ok"] = False
        report["error"] = git.redact(f"{type(exc).__name__}: {exc}")
        log.exception("outbox: user %s sync crashed", user_id)
        results = {}

    # Phase 4 — DB.
    async with Session() as db:
        if records:
            await _apply_records(db, user_id, records, report)
        now = now_utc()
        for ob_id, res in results.items():
            ob = await db.get(OutboxJob, ob_id)
            if ob is None:
                continue
            if res.get("error"):
                ob.last_error = res["error"][:2000]
                report["job_errors"].append({"slug": ob.slug, "error": res["error"][:500]})
                continue
            ob.last_error = None
            if res.get("published"):
                ob.slug = res["slug"]
                ob.published_files = res["files"]
                if ob.published_at is None:
                    ob.published_at = now
            if res.get("withdrawn_published"):
                ob.withdrawn_published_at = now
        row = await db.get(OutboxConfig, user_id)
        if row is not None:
            st = dict(row.state or {})
            if status_sha is not None and report["error"] is None:
                st["last_status_sha"] = status_sha
            st["last_sync_at"] = report["at"]
            st["last_report"] = report
            row.state = st
            flag_modified(row, "state")
        await db.commit()
    return report


def kick(user_id: int) -> None:
    """Start a background sync now (coalesced: one queued rerun at most)."""
    t = _TASKS.get(user_id)
    if t is not None and not t.done():
        _RERUN.add(user_id)
        return

    async def _run() -> None:
        while True:
            _RERUN.discard(user_id)
            try:
                await sync_user(user_id)
            except Exception:
                log.exception("outbox: kicked sync crashed for user %s", user_id)
            if user_id not in _RERUN:
                return

    _TASKS[user_id] = asyncio.create_task(_run(), name=f"outbox-sync-{user_id}")


async def run_forever() -> None:
    log.info("Outbox sync loop starting (every %ds)", SYNC_SECONDS)
    await asyncio.sleep(30)
    while True:
        try:
            async with _session_factory()() as db:
                users = list((await db.execute(select(OutboxConfig.user_id))).scalars())
            for uid in users:
                if is_running(uid):
                    continue
                await sync_user(uid)
        except Exception:
            log.exception("Outbox sync tick crashed; continuing")
        await asyncio.sleep(SYNC_SECONDS)
