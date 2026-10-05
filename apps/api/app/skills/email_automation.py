"""Gmail auto-import + automation rules for the email inbox.

Flow:
  1. A background poller (run_forever, started in main.lifespan) logs
     into the user's Gmail over IMAP with a Google *app password*
     (stored encrypted as ApiCredential provider "gmail_imap") and pulls
     messages newer than the last seen UID — read-only, BODY.PEEK, so
     nothing is marked read or moved.
  2. A free pre-filter drops obvious non-job mail (no model call): the
     message must mention a tracked company or contain hiring language,
     and job-alert digests / our own notifications are skipped.
  3. Survivors become ParsedEmail rows (state "queued") plus an
     `email_classify` queue task, so classification shares the worker's
     parallelism, rate-limit parking and activity feed.
  4. After classification, `run_automation` applies the user's per-intent
     rules: e.g. rejection → set the matched job to "lost"; interview
     invite / assessment request → email the user's personal address
     (Gmail SMTP, same app password). Every email also stays in the
     inbox for manual review; automatic actions are recorded on the
     row's classification["automation"].

Settings live in /root/.claude/jsp-email-automation.json (claude_config
volume), keyed by user id; the password never touches that file.
"""
from __future__ import annotations

import asyncio
import email
import email.policy
import hashlib
import imaplib
import json
import logging
import re
import smtplib
import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

PROVIDER = "gmail_imap"
NOTIFY_HEADER = "X-JSP-Notification"
NOTIFY_SUBJECT_PREFIX = "[Job Search Pal]"
_PATH = Path("/root/.claude/jsp-email-automation.json")
_LOCK = threading.Lock()
TICK_SECONDS = 60
MAX_PER_POLL = 50
IMAP_TIMEOUT = 30

INTENTS = (
    "rejection", "interview_invite", "take_home_assigned", "offer",
    "withdrew", "ghosted", "status_update",
)
INTENT_LABELS = {
    "rejection": "Rejection",
    "interview_invite": "Interview / screening request",
    "take_home_assigned": "Assessment / take-home request",
    "offer": "Offer",
    "withdrew": "Withdrawal confirmation",
    "ghosted": "Closed without interview",
    "status_update": "Status update",
}
# Never auto-move a job out of these — a stray rejection-looking
# email shouldn't undo an accepted offer.
PROTECTED_STATUSES = {"won", "withdrawn"}

DEFAULT_RULES: dict[str, dict[str, bool]] = {
    "rejection": {"set_status": True, "notify": False},
    "interview_invite": {"set_status": False, "notify": True},
    "take_home_assigned": {"set_status": False, "notify": True},
    "offer": {"set_status": False, "notify": True},
    "withdrew": {"set_status": False, "notify": False},
    "ghosted": {"set_status": False, "notify": False},
    "status_update": {"set_status": False, "notify": False},
}

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "username": "",
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 465,
    "folder": "INBOX",
    "poll_minutes": 10,
    "lookback_days": 3,
    "notify_to": "",
    "min_confidence_status": 0.8,
    "min_confidence_notify": 0.5,
    "app_url": "",
}


# ---- Settings store --------------------------------------------------------


def _load_all() -> dict:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _save_all(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_PATH)


def get_settings(user_id: int) -> dict:
    raw = _load_all().get(str(user_id)) or {}
    out = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    rules = raw.get("rules") if isinstance(raw.get("rules"), dict) else {}
    out["rules"] = {
        i: {
            "set_status": bool((rules.get(i) or {}).get("set_status", DEFAULT_RULES[i]["set_status"])),
            "notify": bool((rules.get(i) or {}).get("notify", DEFAULT_RULES[i]["notify"])),
        }
        for i in INTENTS
    }
    out["state"] = raw.get("state") if isinstance(raw.get("state"), dict) else {}
    return out


def save_settings(user_id: int, patch: dict) -> dict:
    with _LOCK:
        data = _load_all()
        cur = data.get(str(user_id)) or {}
        mailbox_before = (cur.get("username"), cur.get("folder"), cur.get("imap_host"))
        for k in DEFAULTS:
            if k in patch and patch[k] is not None:
                cur[k] = patch[k]
        # Pointing at a different mailbox restarts UID tracking (UIDs
        # are per-mailbox) with a fresh lookback window.
        if (cur.get("username"), cur.get("folder"), cur.get("imap_host")) != mailbox_before:
            st = dict(cur.get("state") or {})
            st.pop("last_uid", None)
            st.pop("uidvalidity", None)
            cur["state"] = st
        if isinstance(patch.get("rules"), dict):
            cur["rules"] = {
                i: {
                    "set_status": bool((patch["rules"].get(i) or {}).get("set_status")),
                    "notify": bool((patch["rules"].get(i) or {}).get("notify")),
                }
                for i in INTENTS
            }
        data[str(user_id)] = cur
        _save_all(data)
    return get_settings(user_id)


def _update_state(user_id: int, **fields) -> None:
    with _LOCK:
        data = _load_all()
        cur = data.get(str(user_id)) or {}
        st = cur.get("state") or {}
        st.update(fields)
        cur["state"] = st
        data[str(user_id)] = cur
        _save_all(data)


def enabled_user_ids() -> list[int]:
    out = []
    for k, v in _load_all().items():
        if isinstance(v, dict) and v.get("enabled") and v.get("username"):
            try:
                out.append(int(k))
            except ValueError:
                pass
    return out


# ---- Pre-filter ------------------------------------------------------------

_HIRING_RE = re.compile(
    r"\b(application|applied|applying|candidacy|candidate|interview|"
    r"recruit(er|ing)|hiring (team|manager)|position|the role|"
    r"phone screen|screening|assessment|take[- ]home|coding (challenge|test)|"
    r"hackerrank|codility|codesignal|karat|offer letter|job offer|"
    r"unfortunately|not (be )?moving forward|other candidates|"
    r"next steps|availability|schedule (a|your) (call|time|chat))\b",
    re.I,
)
_DIGEST_RE = re.compile(
    r"(job alert|jobs? (you may|for you|matching)|new jobs|recommended jobs|"
    r"is hiring|people are viewing|top job picks|your job search|"
    r"newsletter|webinar|unsubscribe from (job|these) alerts)",
    re.I,
)


def is_job_related(msg: dict, org_names: list[str], own_address: str) -> tuple[bool, str]:
    """Cheap gate before any model call. Returns (keep, reason)."""
    if msg.get("is_notification"):
        return False, "our own notification"
    subj = msg.get("subject") or ""
    if subj.startswith(NOTIFY_SUBJECT_PREFIX):
        return False, "our own notification"
    head = f"{subj}\n{(msg.get('body') or '')[:4000]}"
    sender = (msg.get("from") or "").lower()
    org_hit = next(
        (o for o in org_names if len(o) >= 3 and re.search(
            r"(?<![a-z0-9])" + re.escape(o.lower()) + r"(?![a-z0-9])",
            f"{sender}\n{head.lower()}",
        )),
        None,
    )
    if _DIGEST_RE.search(subj) and not org_hit:
        return False, "job-alert digest"
    if org_hit:
        return True, f"mentions tracked company '{org_hit}'"
    if _HIRING_RE.search(head):
        return True, "hiring language"
    return False, "no job signal"


# ---- IMAP ------------------------------------------------------------------


def _body_text(m: email.message.EmailMessage) -> str:
    part = m.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        text = payload.decode("utf-8", errors="replace")
    if part.get_content_type() == "text/html":
        from app.sources._common import html_to_md

        text = html_to_md(text)
    return text.strip()


def fetch_new_messages(cfg: dict, password: str) -> dict:
    """Blocking — call via asyncio.to_thread. Returns {messages,
    last_uid, uidvalidity}. Never marks anything read."""
    st = cfg.get("state") or {}
    conn = imaplib.IMAP4_SSL(cfg["imap_host"], int(cfg["imap_port"]), timeout=IMAP_TIMEOUT)
    try:
        conn.login(cfg["username"], password)
        typ, _ = conn.select(f'"{cfg["folder"]}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f"Folder/label '{cfg['folder']}' not found")
        uidvalidity = None
        typ, resp = conn.response("UIDVALIDITY")
        if resp and resp[0]:
            uidvalidity = int(resp[0])
        last_uid = st.get("last_uid")
        if last_uid is None or st.get("uidvalidity") != uidvalidity:
            since = (datetime.now(timezone.utc) - timedelta(days=int(cfg["lookback_days"]))).strftime("%d-%b-%Y")
            typ, data = conn.uid("SEARCH", None, "SINCE", since)
            floor = 0
        else:
            typ, data = conn.uid("SEARCH", None, "UID", f"{int(last_uid) + 1}:*")
            floor = int(last_uid)
        uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) > floor)
        batch = uids[:MAX_PER_POLL]
        messages = []
        for uid in batch:
            typ, parts = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if not raw:
                continue
            m = email.message_from_bytes(raw, policy=email.policy.default)
            try:
                received = parsedate_to_datetime(m.get("Date")) if m.get("Date") else None
            except (TypeError, ValueError):
                received = None
            messages.append({
                "uid": uid,
                "from": str(m.get("From") or ""),
                "subject": str(m.get("Subject") or ""),
                "received_at": received,
                "message_id": str(m.get("Message-ID") or ""),
                "is_notification": bool(m.get(NOTIFY_HEADER)),
                "body": _body_text(m),
            })
        # Advance past what we fetched; anything beyond the batch cap is
        # picked up next tick. An empty first run keeps no baseline, so
        # the next poll simply re-checks the lookback window.
        new_last = batch[-1] if batch else (last_uid if floor else None)
        return {"messages": messages, "last_uid": new_last,
                "uidvalidity": uidvalidity, "remaining": len(uids) - len(batch)}
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def test_imap(cfg: dict, password: str) -> str:
    conn = imaplib.IMAP4_SSL(cfg["imap_host"], int(cfg["imap_port"]), timeout=IMAP_TIMEOUT)
    try:
        conn.login(cfg["username"], password)
        typ, data = conn.select(f'"{cfg["folder"]}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f"Folder/label '{cfg['folder']}' not found")
        return f"Connected — {int(data[0])} messages in {cfg['folder']}."
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# ---- SMTP ------------------------------------------------------------------


def send_email(cfg: dict, password: str, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = cfg["username"]
    msg["To"] = to
    msg["Subject"] = f"{NOTIFY_SUBJECT_PREFIX} {subject}"[:250]
    msg[NOTIFY_HEADER] = "1"
    msg.set_content(body)
    with smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=IMAP_TIMEOUT) as s:
        s.login(cfg["username"], password)
        s.send_message(msg)


# ---- Polling ---------------------------------------------------------------


def dedupe_hash(sender: str, subject: str, received: Optional[datetime], body: str, message_id: str) -> str:
    if message_id:
        return hashlib.sha1(message_id.strip().lower().encode()).hexdigest()
    from app.api.v1.email_ingest import _dedupe_hash

    return _dedupe_hash(sender, subject, received, body)


async def poll_user(user_id: int) -> dict:
    """One poll for one user. Returns counts; records state + errors."""
    from sqlalchemy import select

    from app.api.v1.api_credentials import get_user_secret
    from app.core.database import SessionLocal
    from app.models.emails import ParsedEmail
    from app.models.jobs import JobFetchQueue, Organization, TrackedJob

    cfg = get_settings(user_id)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    async with SessionLocal() as db:
        password = await get_user_secret(db, user_id, PROVIDER)
    if not password:
        _update_state(user_id, last_poll_at=now_iso, last_error="No Gmail app password saved.")
        return {"error": "No Gmail app password saved."}
    try:
        got = await asyncio.to_thread(fetch_new_messages, cfg, password)
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"[:500]
        _update_state(user_id, last_poll_at=now_iso, last_error=msg)
        log.warning("Gmail poll failed for user %s: %s", user_id, msg)
        return {"error": msg}

    queued = skipped = dupes = 0
    async with SessionLocal() as db:
        org_names = [
            n for (n,) in (
                await db.execute(
                    select(Organization.name)
                    .join(TrackedJob, TrackedJob.organization_id == Organization.id)
                    .where(TrackedJob.user_id == user_id, TrackedJob.deleted_at.is_(None))
                    .distinct()
                )
            ).all() if n
        ]
        for m in got["messages"]:
            keep, _why = is_job_related(m, org_names, cfg["username"])
            if not keep:
                skipped += 1
                continue
            h = dedupe_hash(m["from"], m["subject"], m["received_at"], m["body"], m["message_id"])
            exists = (
                await db.execute(
                    select(ParsedEmail.id).where(
                        ParsedEmail.user_id == user_id, ParsedEmail.dedupe_hash == h
                    )
                )
            ).first()
            if exists:
                dupes += 1
                continue
            row = ParsedEmail(
                user_id=user_id,
                from_address=m["from"][:320] or None,
                subject=m["subject"][:512] or None,
                received_at=m["received_at"],
                body_md=m["body"][:60000],
                dedupe_hash=h,
                state="queued",
            )
            db.add(row)
            await db.flush()
            db.add(JobFetchQueue(
                user_id=user_id,
                kind="email_classify",
                label=f"Email: {(m['subject'] or '(no subject)')[:120]}",
                url="",
                payload={"parsed_email_id": row.id, "auto": True},
                state="queued",
            ))
            queued += 1
        await db.commit()

    counts = {"fetched": len(got["messages"]), "queued": queued,
              "skipped": skipped, "duplicates": dupes, "remaining": got["remaining"]}
    _update_state(
        user_id, last_poll_at=now_iso, last_error=None, last_counts=counts,
        last_uid=got["last_uid"], uidvalidity=got["uidvalidity"],
    )
    return counts


async def _tick() -> None:
    now = datetime.now(timezone.utc)
    for uid in enabled_user_ids():
        cfg = get_settings(uid)
        last = cfg["state"].get("last_poll_at")
        try:
            due = last is None or now - datetime.fromisoformat(last) >= timedelta(
                minutes=max(1, int(cfg["poll_minutes"]))
            )
        except ValueError:
            due = True
        # A backlog (more than MAX_PER_POLL new messages) drains on the
        # next tick instead of waiting a full interval.
        if due or (cfg["state"].get("last_counts") or {}).get("remaining"):
            await poll_user(uid)


async def run_forever() -> None:
    log.info("Gmail poller starting (tick=%ds)", TICK_SECONDS)
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("Gmail poller tick crashed; continuing")
        await asyncio.sleep(TICK_SECONDS)


# ---- Automation ------------------------------------------------------------


async def run_automation(db, row) -> dict:
    """Apply the user's per-intent rules to a freshly classified
    ParsedEmail. Caller commits. Returns the action record (also stored
    on row.classification["automation"])."""
    from sqlalchemy import select

    from app.api.v1.api_credentials import get_user_secret
    from app.api.v1.email_ingest import apply_to_job
    from app.models.jobs import Organization, TrackedJob
    from app.models.user import User

    cfg = get_settings(row.user_id)
    cls = dict(row.classification or {})
    intent = cls.get("intent") or "unrelated"
    conf = float(cls.get("confidence") or 0.0)
    rule = cfg["rules"].get(intent) or {"set_status": False, "notify": False}
    record: dict[str, Any] = {"intent": intent, "status_set": None, "notified": False, "notes": []}

    job = None
    if cls.get("matched_job_id"):
        job = (
            await db.execute(
                select(TrackedJob).where(
                    TrackedJob.id == cls["matched_job_id"],
                    TrackedJob.user_id == row.user_id,
                    TrackedJob.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    if rule["set_status"] and intent != "unrelated":
        target = cls.get("suggested_status")
        if job is None:
            record["notes"].append("status not changed: no matching tracked job")
        elif not target:
            record["notes"].append("status not changed: classifier suggested none")
        elif conf < float(cfg["min_confidence_status"]):
            record["notes"].append(
                f"status not changed: confidence {conf:.2f} < {cfg['min_confidence_status']}"
            )
        elif job.status in PROTECTED_STATUSES:
            record["notes"].append(f"status not changed: job is '{job.status}'")
        else:
            user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
            prior = job.status
            await apply_to_job(
                db, row, job,
                new_status=target,
                event_type=cls.get("suggested_event_type") or "note",
                notes=(cls.get("summary") or "") + "\n\n_Applied automatically from Gmail._",
                user=user,
            )
            record["status_set"] = {"job_id": job.id, "from": prior, "to": target}

    if rule["notify"] and intent != "unrelated":
        to = (cfg.get("notify_to") or "").strip()
        if not to:
            record["notes"].append("not emailed: no personal address set")
        elif conf < float(cfg["min_confidence_notify"]):
            record["notes"].append(
                f"not emailed: confidence {conf:.2f} < {cfg['min_confidence_notify']}"
            )
        else:
            password = await get_user_secret(db, row.user_id, PROVIDER)
            org_name = None
            if job is not None and job.organization_id:
                org_name = (
                    await db.execute(select(Organization.name).where(Organization.id == job.organization_id))
                ).scalar_one_or_none()
            subject, body = _notification(cfg, row, cls, job, org_name)
            try:
                await asyncio.to_thread(send_email, cfg, password or "", to, subject, body)
                record["notified"] = True
            except Exception as exc:
                record["notes"].append(f"email failed: {type(exc).__name__}: {exc}"[:300])

    cls["automation"] = record
    row.classification = cls
    return record


def _notification(cfg, row, cls, job, org_name) -> tuple[str, str]:
    label = INTENT_LABELS.get(cls.get("intent"), "Job email")
    what = f"{job.title} @ {org_name}" if job is not None and org_name else (
        job.title if job is not None else (row.subject or "(no subject)")
    )
    lines = [f"{label}: {what}", ""]
    if cls.get("summary"):
        lines += [cls["summary"], ""]
    if cls.get("key_dates"):
        lines += ["Key dates: " + ", ".join(cls["key_dates"]), ""]
    if job is not None:
        base = (cfg.get("app_url") or "").rstrip("/")
        lines.append(f"Tracked job: {base}/jobs/{job.id}" if base else f"Tracked job id {job.id}")
    else:
        lines.append("No tracked job matched — check the Email Inbox page.")
    _, sender = parseaddr(row.from_address or "")
    lines += [
        "",
        "---- original email ----",
        f"From: {row.from_address or sender or '(unknown)'}",
        f"Subject: {row.subject or '(no subject)'}",
        f"Received: {row.received_at.isoformat() if row.received_at else '(unknown)'}",
        "",
        "\n".join((row.body_md or "").strip().splitlines()[:60]),
    ]
    return f"{label}: {what}", "\n".join(lines)
