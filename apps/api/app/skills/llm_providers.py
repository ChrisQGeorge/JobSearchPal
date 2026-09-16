"""User-configured external LLM providers (OpenAI-compatible chat API).

One implementation covers every mainstream non-Claude option, because they
all speak the same wire protocol (`POST {base_url}/chat/completions`):

  * hosted: OpenAI, DeepSeek, OpenRouter, Mistral, Groq, xAI, …
  * local:  Ollama (http://host:11434/v1), LM Studio, vLLM, llama.cpp server

Providers are stored in a JSON file on the /root/.claude volume, like the
worker/model settings — single-user, self-hosted, survives restarts. Model
settings reference them as `ext:<provider_id>/<model>`; the runner spots
that prefix and calls the provider instead of spawning the Claude CLI.

External models are TEXT-ONLY: no Bash / WebFetch / sessions. Actions whose
prompts depend on tools (score, prep, companion chat, ingest, …) are gated
to Claude via `model_settings.EXT_COMPATIBLE_ACTIONS`.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncIterator, Optional

log = logging.getLogger(__name__)

_PATH = Path("/root/.claude/jsp-llm-providers.json")

# Model-settings values referencing an external provider look like
# "ext:<provider_id>/<model>".
EXT_PREFIX = "ext:"

# Upper bound on stored providers — this is a single-user app.
_MAX_PROVIDERS = 10


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    return s[:48] or "provider"


def _sanitize(raw: object, *, prior_keys: dict[str, str]) -> list[dict]:
    """Validate + normalize a provider list. `prior_keys` maps provider id →
    previously stored api_key so an empty incoming key means "keep"."""
    out: list[dict] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return out
    for entry in raw[:_MAX_PROVIDERS]:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip()
        base_url = str(entry.get("base_url") or "").strip().rstrip("/")
        if not label or not (
            base_url.startswith("http://") or base_url.startswith("https://")
        ):
            continue
        pid = _slug(str(entry.get("id") or "").strip() or label)
        if pid in seen:
            continue
        seen.add(pid)
        models_raw = entry.get("models")
        models: list[str] = []
        if isinstance(models_raw, list):
            for m in models_raw:
                m = str(m).strip()
                if m and m not in models:
                    models.append(m)
        if not models:
            continue
        api_key = str(entry.get("api_key") or "").strip()
        if not api_key:
            api_key = prior_keys.get(pid, "")
        out.append(
            {
                "id": pid,
                "label": label,
                "base_url": base_url,
                "api_key": api_key,
                "models": models[:20],
            }
        )
    return out


def load_providers() -> list[dict]:
    """Read the provider list from disk. Returns [] on any error."""
    try:
        data = json.loads(_PATH.read_text())
        providers = data.get("providers")
        prior = {
            str(p.get("id")): str(p.get("api_key") or "")
            for p in providers
            if isinstance(p, dict)
        } if isinstance(providers, list) else {}
        return _sanitize(providers, prior_keys=prior)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def save_providers(raw: object) -> list[dict]:
    """Replace the provider list. Empty api_key on an entry keeps the
    previously stored key for that provider id (so the UI never has to
    round-trip secrets). Returns the sanitized list as persisted."""
    prior_keys = {p["id"]: p["api_key"] for p in load_providers()}
    sanitized = _sanitize(raw, prior_keys=prior_keys)
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps({"providers": sanitized}, indent=2))
    except OSError as exc:
        log.warning("Failed to persist LLM providers: %s", exc)
    return sanitized


def public_providers() -> list[dict]:
    """Provider list with secrets stripped — safe to return over the API."""
    return [
        {
            "id": p["id"],
            "label": p["label"],
            "base_url": p["base_url"],
            "models": p["models"],
            "has_api_key": bool(p["api_key"]),
        }
        for p in load_providers()
    ]


def resolve_ext_model(model: Optional[str]) -> Optional[tuple[dict, str]]:
    """Parse an `ext:<provider_id>/<model>` value into (provider, model).
    Returns None for anything else — including an ext value whose provider
    no longer exists (caller falls back to Claude)."""
    if not model or not model.startswith(EXT_PREFIX):
        return None
    body = model[len(EXT_PREFIX):]
    pid, sep, model_name = body.partition("/")
    if not sep or not model_name.strip():
        return None
    for p in load_providers():
        if p["id"] == pid:
            return p, model_name.strip()
    log.warning("Model %r references an unknown provider — ignoring.", model)
    return None


def provider_choices() -> list[tuple[str, str]]:
    """Dropdown entries for the Settings model pickers — one per
    (provider × model)."""
    out: list[tuple[str, str]] = []
    for p in load_providers():
        for m in p["models"]:
            out.append((f"{EXT_PREFIX}{p['id']}/{m}", f"{p['label']} — {m} (external)"))
    return out


# ---------------------------------------------------------------------------
# OpenAI-compatible chat call
# ---------------------------------------------------------------------------

class ExternalProviderError(RuntimeError):
    """Raised on HTTP / protocol failures from an external provider. The
    message includes the status code + body snippet so the queue worker's
    rate-limit detector (which looks for '429', 'rate limit', …) can park
    the task instead of burning retries."""


def _headers(provider: dict) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        h["Authorization"] = f"Bearer {provider['api_key']}"
    return h


async def stream_chat(
    provider: dict,
    model: str,
    prompt: str,
    *,
    timeout_seconds: int = 300,
) -> AsyncIterator[str]:
    """POST /chat/completions with stream=true; yield content deltas.

    Falls back transparently when a server ignores `stream` and answers
    with a plain JSON completion (some local servers do)."""
    import httpx

    url = f"{provider['base_url']}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    timeout = httpx.Timeout(connect=15.0, read=float(timeout_seconds), write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", url, json=payload, headers=_headers(provider)
        ) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", errors="replace")
                raise ExternalProviderError(
                    f"{provider['label']} returned HTTP {resp.status_code}: {body[:800]}"
                )
            ctype = resp.headers.get("content-type", "")
            if "text/event-stream" not in ctype:
                # Non-streaming server — one JSON body.
                body = (await resp.aread()).decode("utf-8", errors="replace")
                try:
                    data = json.loads(body)
                    text = data["choices"][0]["message"]["content"] or ""
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                    raise ExternalProviderError(
                        f"{provider['label']} returned an unparseable completion: "
                        f"{body[:500]}"
                    ) from exc
                if text:
                    yield text
                return
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    yield delta


async def chat_text(
    provider: dict,
    model: str,
    prompt: str,
    *,
    timeout_seconds: int = 300,
) -> str:
    """Convenience wrapper: run the streaming call and return the full text."""
    parts: list[str] = []
    async for delta in stream_chat(
        provider, model, prompt, timeout_seconds=timeout_seconds
    ):
        parts.append(delta)
    return "".join(parts)
