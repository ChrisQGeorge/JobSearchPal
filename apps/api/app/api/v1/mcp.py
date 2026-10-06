"""MCP (Model Context Protocol) server for external agents.

Transport: Streamable HTTP, stateless JSON mode — every JSON-RPC request
is a POST to /api/v1/mcp answered with a single application/json body
(no SSE stream, no session id), which the spec permits and every MCP
client supports. Methods: initialize, ping, tools/list, tools/call;
notifications get 202.

Auth: `Authorization: Bearer jspmcp_…` — an agent token minted on
Settings → Agent Access (app/skills/mcp_tokens.py). Tokens are scoped
"read" or "read_write"; write tools are hidden from tools/list and
refused at call time for read-only tokens.

Every tool is a thin wrapper over the app's own REST endpoints, called
in-process through httpx's ASGI transport with a short-lived user JWT.
So agents get exactly the same validation and side effects as the UI —
status changes cancel scoring tasks, URL imports go through the fetch
queue, rescoring dedupes against pending tasks — with no second copy of
business logic to drift.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.deps import get_current_user
from app.core.security import create_access_token
from app.models.user import User
from app.skills.mcp_tokens import create_token, list_tokens, resolve_token, revoke_token

log = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "job-search-pal", "version": "1.1.0"}
MAX_RESULT_CHARS = 120_000

INSTRUCTIONS = (
    "Job Search Pal: a personal job-search tracker. Tracked jobs move "
    "through statuses (to_review → interested → in_progress → applied → "
    "screening/interviewing/offer → won/lost, plus not_interested, "
    "ghosted, archived…). fit_score (0-100) comes from the TypeSafe Jev "
    "evaluator when configured. Leads are raw postings from job sources "
    "awaiting triage; promoting a lead creates a tracked job. Long-running "
    "work (URL import, scoring, document tailoring) is QUEUED and returns "
    "immediately — poll get_job / list_documents / list_queue for results."
)


# ---- Tool registry ---------------------------------------------------------

Call = Callable[..., Awaitable[Any]]


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[[Call, dict], Awaitable[Any]]
    write: bool = False


def _obj(props: dict, required: Optional[list[str]] = None) -> dict:
    s: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        s["required"] = required
    return s


_INT = {"type": "integer"}
_STR = {"type": "string"}
_BOOL = {"type": "boolean"}
_IDS = {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 200}

_JOB_FIELDS = {
    "title": _STR,
    "organization_id": _INT,
    "job_description": _STR,
    "source_url": _STR,
    "location": _STR,
    "remote_policy": {"type": "string", "enum": ["onsite", "hybrid", "remote"]},
    "salary_min": {"type": "number"},
    "salary_max": {"type": "number"},
    "salary_currency": _STR,
    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
    "status": _STR,
    "notes": _STR,
    "date_posted": {"type": "string", "format": "date"},
    "date_applied": {"type": "string", "format": "date"},
    "date_closed": {"type": "string", "format": "date"},
    "employment_type": _STR,
    "experience_level": _STR,
    "required_skills": {"type": "array", "items": _STR},
    "nice_to_have_skills": {"type": "array", "items": _STR},
}

_SUMMARY_KEYS = (
    "id", "title", "status", "organization_name", "location",
    "remote_policy", "fit_score", "salary_min", "salary_max",
    "salary_currency", "priority", "date_applied", "updated_at",
    "has_resume", "has_cover_letter", "skill_match_pct",
)


async def _list_jobs(call: Call, a: dict) -> Any:
    rows = await call("GET", "/jobs", params={
        k: v for k, v in {"status": a.get("status"), "q": a.get("query")}.items() if v
    })
    lo, hi = a.get("min_fit"), a.get("max_fit")
    out = []
    for r in rows:
        fit = r.get("fit_score")
        if lo is not None and (fit is None or fit < lo):
            continue
        if hi is not None and (fit is None or fit > hi):
            continue
        out.append({k: r.get(k) for k in _SUMMARY_KEYS if k in r})
    limit = int(a.get("limit") or 50)
    return {"total_matching": len(out), "jobs": out[:limit]}


async def _get_job(call: Call, a: dict) -> Any:
    job = await call("GET", f"/jobs/{int(a['job_id'])}")
    if a.get("include_description") is False:
        job.pop("job_description", None)
    return job


async def _set_status(call: Call, a: dict) -> Any:
    ok, failed = [], []
    for jid in a["job_ids"]:
        try:
            await call("PUT", f"/jobs/{int(jid)}", json={"status": a["status"]})
            ok.append(jid)
        except _ApiError as exc:
            failed.append({"job_id": jid, "error": str(exc)})
    return {"updated": ok, "failed": failed}


_PROMPT_KEY = {"type": "string", "description": "Prompt key from list_prompts, e.g. tailor_resume"}
_PROMPT_VARIANT_FIELDS = {
    "id": {**_STR, "description": "Existing variant id to update ('default' = built-in); omit to create"},
    "name": _STR,
    "template": {**_STR, "description": "Full prompt text with {placeholders}; {{ }} for literal braces"},
    "enabled": _BOOL,
    "weight": {"type": "number", "minimum": 0, "maximum": 100},
}


def _variant_for_put(v: dict) -> dict:
    """GET-shape variant -> PUT-shape (the built-in never sends a template)."""
    return {
        "id": "default" if v.get("builtin") else v.get("id"),
        "name": v.get("name"),
        "template": None if v.get("builtin") else v.get("template"),
        "enabled": v.get("enabled", True),
        "weight": v.get("weight", 1.0),
    }


async def _upsert_prompt_variant(call: Call, a: dict) -> Any:
    """Create or update ONE variant without touching the others: read the
    current list, merge, write the full list back."""
    key = a["key"]
    current = await call("GET", f"/prompts/{key}")
    variants = [_variant_for_put(v) for v in current["variants"]]
    vid = a.get("id")
    if vid:
        target = next((v for v in variants if v["id"] == vid), None)
        if target is None:
            raise _ApiError(f"No variant with id '{vid}' on prompt '{key}'.")
        if vid == "default":
            builtin = next(v for v in current["variants"] if v.get("builtin"))
            if a.get("template") is not None and a["template"] != builtin["template"]:
                raise _ApiError(
                    "The built-in default's text can't be changed — create a new "
                    "variant (omit id) and disable or down-weight the default."
                )
        for f in ("name", "template", "enabled", "weight"):
            if f in a and a[f] is not None and not (vid == "default" and f in ("template", "name")):
                target[f] = a[f]
    else:
        if not (a.get("template") or "").strip():
            raise _ApiError("A new variant needs a non-empty template.")
        variants.append({
            "id": None,
            "name": a.get("name") or "variant",
            "template": a["template"],
            "enabled": a.get("enabled", True),
            "weight": a.get("weight", 1.0),
        })
    return await call("PUT", f"/prompts/{key}", json={"variants": variants})


async def _import_url(call: Call, a: dict) -> Any:
    body = {"url": a["url"]}
    if a.get("status"):
        body["desired_status"] = a["status"]
    if a.get("notes"):
        body["desired_notes"] = a["notes"]
    return await call("POST", "/jobs/queue", json=body)


TOOLS: list[Tool] = [
    # -- read --
    Tool(
        "list_jobs",
        "List tracked jobs (summary fields incl. fit_score, status, pay). "
        "Optional filters: status, title prefix query, fit-score range.",
        _obj({
            "status": _STR,
            "query": {"type": "string", "description": "Title prefix search"},
            "min_fit": {"type": "integer", "minimum": 0, "maximum": 100},
            "max_fit": {"type": "integer", "minimum": 0, "maximum": 100},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
        }),
        _list_jobs,
    ),
    Tool(
        "get_job",
        "Full detail for one tracked job: description, skills, Jev analysis "
        "(jd_analysis.scores per dimension), fit_summary, dates, notes.",
        _obj({"job_id": _INT, "include_description": {**_BOOL, "default": True}}, ["job_id"]),
        _get_job,
    ),
    Tool(
        "job_status_counts", "Number of tracked jobs per status.",
        _obj({}), lambda call, a: call("GET", "/jobs/counts"),
    ),
    Tool(
        "review_queue", "Jobs awaiting review (status to_review / skipped), in queue order.",
        _obj({"scored_only": _BOOL}),
        lambda call, a: call("GET", "/jobs/review-queue",
                             params={"scored_only": "true"} if a.get("scored_only") else None),
    ),
    Tool(
        "apply_queue", "Jobs marked interested and waiting to be applied to, in queue order.",
        _obj({"scored_only": _BOOL}),
        lambda call, a: call("GET", "/jobs/apply-queue",
                             params={"scored_only": "true"} if a.get("scored_only") else None),
    ),
    Tool(
        "list_job_events", "Application timeline events for a job.",
        _obj({"job_id": _INT}, ["job_id"]),
        lambda call, a: call("GET", f"/jobs/{int(a['job_id'])}/events"),
    ),
    Tool(
        "list_interview_rounds", "Interview rounds for a job.",
        _obj({"job_id": _INT}, ["job_id"]),
        lambda call, a: call("GET", f"/jobs/{int(a['job_id'])}/rounds"),
    ),
    Tool(
        "list_documents",
        "Generated documents (tailored resumes, cover letters, …) — "
        "metadata only; use get_document for the text.",
        _obj({"job_id": _INT, "doc_type": _STR}),
        lambda call, a: call("GET", "/documents", params={
            k: v for k, v in {"tracked_job_id": a.get("job_id"),
                              "doc_type": a.get("doc_type")}.items() if v is not None
        }),
    ),
    Tool(
        "get_document", "One generated document including its markdown content.",
        _obj({"document_id": _INT}, ["document_id"]),
        lambda call, a: call("GET", f"/documents/{int(a['document_id'])}"),
    ),
    Tool(
        "list_organizations", "Organizations (companies), optional name-prefix search.",
        _obj({"query": _STR, "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50}}),
        lambda call, a: call("GET", "/organizations", params={
            k: v for k, v in {"q": a.get("query"), "limit": a.get("limit") or 50}.items() if v
        }),
    ),
    Tool(
        "get_organization", "Organization detail, including any company research.",
        _obj({"organization_id": _INT}, ["organization_id"]),
        lambda call, a: call("GET", f"/organizations/{int(a['organization_id'])}"),
    ),
    Tool(
        "list_leads",
        "Leads from job sources awaiting triage. state: new (default), "
        "promoted, dismissed, expired, or all.",
        _obj({
            "state": {**_STR, "default": "new"},
            "query": _STR,
            "remote_only": _BOOL,
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100},
        }),
        lambda call, a: call("GET", "/job-leads", params={
            k: v for k, v in {
                "state": a.get("state") or "new", "q": a.get("query"),
                "remote_only": "true" if a.get("remote_only") else None,
                "limit": a.get("limit") or 100,
            }.items() if v is not None
        }),
    ),
    Tool(
        "list_sources", "Registered job sources (ATS feeds, Bright Data queries) and their poll status.",
        _obj({}), lambda call, a: call("GET", "/job-sources"),
    ),
    Tool(
        "list_queue", "Background task queue (URL imports, scoring, tailoring) with states and errors.",
        _obj({}), lambda call, a: call("GET", "/jobs/queue"),
    ),
    Tool(
        "list_prompts",
        "Every agent-action prompt (resume, cover letter, humanize, analysis, …) with "
        "whether it's customized or running an A/B test.",
        _obj({}), lambda call, a: call("GET", "/prompts"),
    ),
    Tool(
        "get_prompt",
        "One prompt: placeholders, the built-in default and custom variants with "
        "template text, enabled flag, weight and live traffic share.",
        _obj({"key": _PROMPT_KEY}, ["key"]),
        lambda call, a: call("GET", f"/prompts/{a['key']}"),
    ),
    Tool(
        "preview_prompt",
        "Check a template without saving: renders it with «placeholder» markers and "
        "reports missing_placeholders (used by the default, absent here) and "
        "unknown_placeholders (never filled in).",
        _obj({"key": _PROMPT_KEY, "template": _STR}, ["key", "template"]),
        lambda call, a: call("POST", f"/prompts/{a['key']}/preview", json={"template": a["template"]}),
    ),
    Tool(
        "prompt_stats",
        "A/B scoreboard for a document prompt: per variant, documents written, "
        "jobs applied, and response / interview / offer rates (small samples flagged).",
        _obj({"key": _PROMPT_KEY}, ["key"]),
        lambda call, a: call("GET", f"/prompts/{a['key']}/stats"),
    ),
    Tool(
        "upsert_prompt_variant",
        "Create (omit id) or update (give id) ONE prompt variant, leaving the others "
        "untouched. The built-in default's text can't change — only enabled / weight.",
        _obj({"key": _PROMPT_KEY, **_PROMPT_VARIANT_FIELDS}, ["key"]),
        _upsert_prompt_variant, write=True,
    ),
    Tool(
        "save_prompt",
        "Replace a prompt's ENTIRE variant list. Variants you omit are DELETED — prefer "
        "upsert_prompt_variant for single changes. Include {id:'default'} to keep the built-in.",
        _obj({"key": _PROMPT_KEY, "variants": {"type": "array", "items": _obj(_PROMPT_VARIANT_FIELDS)}},
             ["key", "variants"]),
        lambda call, a: call("PUT", f"/prompts/{a['key']}", json={"variants": a["variants"]}),
        write=True,
    ),
    # -- write --
    Tool(
        "create_job", "Create a tracked job manually (title required).",
        _obj(_JOB_FIELDS, ["title"]),
        lambda call, a: call("POST", "/jobs", json=a),
        write=True,
    ),
    Tool(
        "update_job",
        "Update fields on a tracked job (only the fields given change). "
        "Status changes carry the same side effects as the UI.",
        _obj({"job_id": _INT, "fields": _obj({k: v for k, v in _JOB_FIELDS.items()})},
             ["job_id", "fields"]),
        lambda call, a: call("PUT", f"/jobs/{int(a['job_id'])}", json=a["fields"]),
        write=True,
    ),
    Tool(
        "set_job_status", "Set the status of one or more jobs (bulk).",
        _obj({"job_ids": _IDS, "status": _STR}, ["job_ids", "status"]),
        _set_status, write=True,
    ),
    Tool(
        "delete_job", "Soft-delete a tracked job.",
        _obj({"job_id": _INT}, ["job_id"]),
        lambda call, a: call("DELETE", f"/jobs/{int(a['job_id'])}"),
        write=True,
    ),
    Tool(
        "import_job_from_url",
        "Queue a job posting URL for import: the worker fetches and parses "
        "it, creates the tracked job, and scores it. Returns the queue row.",
        _obj({"url": _STR, "status": {**_STR, "description": "Initial status, default to_review"},
              "notes": _STR}, ["url"]),
        _import_url, write=True,
    ),
    Tool(
        "rescore_jobs", "Queue fresh fit scoring (Jev when configured) for the given jobs.",
        _obj({"job_ids": _IDS}, ["job_ids"]),
        lambda call, a: call("POST", "/jobs/batch-analyze-jd", json={"ids": a["job_ids"]}),
        write=True,
    ),
    Tool(
        "add_job_event", "Add an application timeline event (e.g. email_received, call, note).",
        _obj({"job_id": _INT, "event_type": _STR, "details_md": _STR,
              "event_date": {"type": "string", "format": "date-time"}},
             ["job_id", "event_type"]),
        lambda call, a: call("POST", f"/jobs/{int(a['job_id'])}/events",
                             json={k: v for k, v in a.items() if k != "job_id"}),
        write=True,
    ),
    Tool(
        "create_interview_round", "Add an interview round to a job.",
        _obj({
            "job_id": _INT, "round_number": _INT, "round_type": _STR,
            "scheduled_at": {"type": "string", "format": "date-time"},
            "duration_minutes": _INT, "format": _STR, "location_or_link": _STR,
            "outcome": _STR, "notes_md": _STR,
        }, ["job_id"]),
        lambda call, a: call("POST", f"/jobs/{int(a['job_id'])}/rounds",
                             json={k: v for k, v in a.items() if k != "job_id"}),
        write=True,
    ),
    Tool(
        "update_interview_round", "Update an interview round (outcome, notes, schedule, …).",
        _obj({"job_id": _INT, "round_id": _INT, "fields": {"type": "object"}},
             ["job_id", "round_id", "fields"]),
        lambda call, a: call("PUT", f"/jobs/{int(a['job_id'])}/rounds/{int(a['round_id'])}",
                             json=a["fields"]),
        write=True,
    ),
    Tool(
        "tailor_document",
        "Queue a tailored document for a job (resume or cover_letter). "
        "Returns a placeholder document; poll get_document until it has content.",
        _obj({"job_id": _INT, "doc_type": {**_STR, "description": "resume | cover_letter | …"},
              "prompt_variant": {**_STR, "description":
                                 "Optional: force a prompt variant id (see Settings → Prompts)"}},
             ["job_id", "doc_type"]),
        lambda call, a: call("POST", f"/documents/tailor/{int(a['job_id'])}",
                             json={k: v for k, v in {
                                 "doc_type": a["doc_type"],
                                 "prompt_variant": a.get("prompt_variant"),
                             }.items() if v}),
        write=True,
    ),
    Tool(
        "triage_leads",
        "Triage leads: action 'review' promotes them into the tracker at "
        "to_review (fetch + scoring queued); 'dismissed' drops them.",
        _obj({"lead_ids": _IDS, "action": {"type": "string", "enum": ["review", "dismissed"]}},
             ["lead_ids", "action"]),
        lambda call, a: call("POST", "/job-leads/action",
                             json={"ids": a["lead_ids"], "action": a["action"]}),
        write=True,
    ),
    Tool(
        "poll_source", "Poll one job source now (Bright Data runs may keep collecting in the background).",
        _obj({"source_id": _INT}, ["source_id"]),
        lambda call, a: call("POST", f"/job-sources/{int(a['source_id'])}/poll", json={}),
        write=True,
    ),
]
_BY_NAME = {t.name: t for t in TOOLS}


# ---- In-process REST calls -------------------------------------------------


class _ApiError(Exception):
    pass


def _make_caller(app, user_id: int) -> Call:
    token = create_access_token(str(user_id), extra={"purpose": "mcp"})

    async def call(method: str, path: str, *, params=None, json=None) -> Any:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://mcp.internal/api/v1",
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        ) as client:
            resp = await client.request(method, path, params=params, json=json)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = resp.text[:500]
            raise _ApiError(f"HTTP {resp.status_code}: {detail}")
        if resp.status_code == 204 or not resp.content:
            return {"ok": True}
        try:
            return resp.json()
        except ValueError:
            return {"text": resp.text[:MAX_RESULT_CHARS]}

    return call


# ---- JSON-RPC plumbing -----------------------------------------------------


def _rpc_result(req_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_text(payload: Any, is_error: bool = False) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str, indent=1)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n…[truncated — narrow the query or use a limit]"
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


async def _dispatch(msg: dict, app, ident: dict) -> Optional[dict]:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _rpc_error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    method = msg["method"]
    req_id = msg.get("id")
    is_notification = "id" not in msg
    params = msg.get("params") or {}

    if is_notification:
        return None  # notifications/initialized, cancelled, … — nothing to say

    can_write = ident["scope"] == "read_write"

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return _rpc_result(req_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS + (
                "" if can_write else " This token is READ-ONLY; write tools are unavailable."
            ),
        })
    if method == "ping":
        return _rpc_result(req_id, {})
    if method == "tools/list":
        return _rpc_result(req_id, {"tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.schema,
                "annotations": {
                    "readOnlyHint": not t.write,
                    "destructiveHint": t.name == "delete_job",
                },
            }
            for t in TOOLS if can_write or not t.write
        ]})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = _BY_NAME.get(name)
        if tool is None or (tool.write and not can_write):
            return _rpc_error(req_id, -32602, f"Unknown tool: {name}")
        if not isinstance(args, dict):
            return _rpc_error(req_id, -32602, "arguments must be an object")
        call = _make_caller(app, ident["user_id"])
        try:
            out = await tool.handler(call, args)
            return _rpc_result(req_id, _tool_text(out))
        except _ApiError as exc:
            return _rpc_result(req_id, _tool_text(str(exc), is_error=True))
        except (KeyError, TypeError, ValueError) as exc:
            return _rpc_result(req_id, _tool_text(f"Bad arguments: {exc}", is_error=True))
        except Exception as exc:  # pragma: no cover
            log.exception("MCP tool %s failed", name)
            return _rpc_result(req_id, _tool_text(f"Tool failed: {exc}", is_error=True))
    return _rpc_error(req_id, -32601, f"Method not found: {method}")


def _auth(request: Request) -> Optional[dict]:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    return resolve_token(auth.split(" ", 1)[1].strip())


_UNAUTH = JSONResponse(
    {"error": "Agent token required: Authorization: Bearer jspmcp_… "
              "(create one on Settings → Agent Access)."},
    status_code=401,
    headers={"WWW-Authenticate": 'Bearer realm="job-search-pal-mcp"'},
)


@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    ident = _auth(request)
    if ident is None:
        return _UNAUTH
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_rpc_error(None, -32700, "Parse error"), status_code=400)

    if isinstance(body, list):  # legacy batch support (pre-2025-06-18 clients)
        replies = [r for r in [await _dispatch(m, request.app, ident) for m in body] if r]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = await _dispatch(body, request.app, ident)
    if reply is None:
        return Response(status_code=202)
    return JSONResponse(reply)


@router.get("/mcp")
async def mcp_get() -> Response:
    # No server-initiated SSE stream in stateless mode — spec-sanctioned 405.
    return Response(status_code=405, headers={"Allow": "POST"})


# ---- Token management (browser session) ------------------------------------


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: str = Field(default="read", pattern="^(read|read_write)$")


@router.get("/mcp-tokens")
async def get_tokens(user: User = Depends(get_current_user)) -> dict:
    return {
        "tokens": list_tokens(user.id),
        "tools": [{"name": t.name, "write": t.write} for t in TOOLS],
    }


@router.post("/mcp-tokens", status_code=201)
async def post_token(
    payload: TokenIn, user: User = Depends(get_current_user)
) -> dict:
    try:
        plaintext, meta = create_token(user.id, payload.name, payload.scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # The plaintext is returned exactly once — only its hash is stored.
    return {"token": plaintext, **meta}


@router.delete("/mcp-tokens/{token_id}", status_code=204)
async def delete_token(
    token_id: str, user: User = Depends(get_current_user)
) -> Response:
    if not revoke_token(user.id, token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    return Response(status_code=204)
