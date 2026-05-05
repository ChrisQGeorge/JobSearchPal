"""Per-source error log file. JSON-Lines format so the Companion can
grep / jq it from Bash without parsing a structured logger's output.

Path: /app/logs/source_errors.jsonl inside the api container. Rotates
at 5 MB with 3 backups so it's bounded.

Each line is a self-contained JSON object:
  {
    "ts":            ISO-8601 UTC,
    "user_id":       int,
    "source_id":     int,
    "kind":          str,
    "slug_or_url":   str,
    "error_class":   str,    # python class name
    "error_message": str,
  }
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOG_DIR = Path(os.environ.get("JSP_LOG_DIR", "/app/logs"))
LOG_FILE = LOG_DIR / "source_errors.jsonl"

_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    log = logging.getLogger("app.sources.errlog")
    # Don't bubble to root — this is a dedicated diagnostic stream.
    log.propagate = False
    log.setLevel(logging.INFO)
    if not log.handlers:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
        except OSError as exc:
            # Read-only filesystem / permissions — fall through to a
            # null handler so callers don't crash. The error is still
            # available via the source row's last_error field.
            logging.getLogger(__name__).warning(
                "Could not open source error log at %s: %s — diagnostic "
                "lines will be dropped.",
                LOG_FILE,
                exc,
            )
            handler = logging.NullHandler()
        # Plain message — the message itself is already the JSON line.
        handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(handler)
    _logger = log
    return log


def log_source_error(
    *,
    user_id: int,
    source_id: int,
    kind: str,
    slug_or_url: str,
    error_class: str,
    error_message: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append a single JSONL line. Best-effort — never raises."""
    payload: dict[str, Any] = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "user_id": user_id,
        "source_id": source_id,
        "kind": kind,
        "slug_or_url": slug_or_url,
        "error_class": error_class,
        "error_message": error_message[:2000],
    }
    if extra:
        for k, v in extra.items():
            if k not in payload:
                payload[k] = v
    try:
        _get_logger().info(json.dumps(payload, ensure_ascii=False))
    except Exception:
        # Diagnostic logging must never break the poller.
        pass


__all__ = ["LOG_FILE", "log_source_error"]
