"""Server-side markdown-to-PDF rendering for tailored resumes / cover
letters. Uses the chromium service that R10 already provisioned —
opens a `data:` URL of the rendered HTML on a headless tab,
calls `page.pdf()`, writes the bytes under `/app/uploads/documents/`,
and returns the URL.

This is what the apply_run handler uses to attach files without
round-tripping to the user's browser. Also exposed via a regular
`/api/v1/documents/{id}/render-pdf` endpoint so the user can grab a
PDF straight from Studio.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.documents import GeneratedDocument
from app.skills.apply_run import _resolve_ws

log = logging.getLogger(__name__)

# Print stylesheet — single column, conservative margins, nothing
# fancy. Mirrors the web Studio print view enough that the user sees
# the same shape; any tweaks should land here too.
_PRINT_CSS = """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.45;
  color: #111;
  margin: 0;
  padding: 0;
}
main { padding: 0.5in 0.6in; }
h1 { font-size: 18pt; margin: 0 0 0.15em 0; }
h2 { font-size: 13pt; border-bottom: 1px solid #ccc;
     padding-bottom: 2pt; margin: 1em 0 0.4em 0; }
h3 { font-size: 11.5pt; margin: 0.8em 0 0.2em 0; }
p { margin: 0.3em 0; }
ul { margin: 0.2em 0 0.6em 1.2em; padding: 0; }
li { margin: 0.15em 0; }
a { color: #1a5fb4; text-decoration: none; }
hr { border: none; border-top: 1px solid #ccc; margin: 0.8em 0; }
table { border-collapse: collapse; }
td, th { padding: 0.2em 0.4em; }
"""


def _md_to_html(md: str) -> str:
    """Convert markdown to HTML. Lazy-imports markdown-it-py so the
    module can still be imported when the dep isn't installed yet
    (early in dev or before requirements are pulled)."""
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        # Fallback: pre-format as <pre> so we still produce a
        # rendered PDF, just an ugly one. Better than failing.
        escaped = (
            md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        return f"<pre>{escaped}</pre>"
    md_engine = MarkdownIt("commonmark", {"html": False, "breaks": False, "linkify": True})
    return md_engine.render(md)


def _wrap_html(body_html: str, title: str) -> str:
    safe_title = (title or "Document").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8" />
<title>{safe_title}</title>
<style>{_PRINT_CSS}</style>
</head><body><main>
{body_html}
</main></body></html>"""


def _safe_filename(s: str) -> str:
    """Sanitize a string for use as a filename. Strips slashes,
    NUL, control chars; collapses whitespace; trims to 80 chars."""
    cleaned = re.sub(r"[^\w\s.\-]", "_", s).strip().replace(" ", "_")
    return cleaned[:80] or "document"


async def render_markdown_to_pdf(
    *, markdown_text: str, title: str, out_path: Path
) -> Path:
    """Render markdown to PDF at `out_path`. Returns the path on
    success; raises on failure.

    Connects to the same chromium service the apply_run handler uses
    (CDP via the chromium-cdp-proxy sidecar). Uses a fresh isolated
    BrowserContext so the user's interactive browser session is
    untouched.
    """
    from playwright.async_api import async_playwright

    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = _wrap_html(_md_to_html(markdown_text), title)

    async with async_playwright() as p:
        ws = await _resolve_ws()
        if not ws:
            raise RuntimeError(
                "PDF render: chromium CDP not reachable. Is the chromium service up?"
            )
        browser = await p.chromium.connect_over_cdp(
            ws, headers={"Host": "localhost"},
        )
        try:
            ctx = await browser.new_context()
            try:
                page = await ctx.new_page()
                # Use set_content so we don't rely on a hosted URL.
                await page.set_content(html, wait_until="domcontentloaded", timeout=15_000)
                pdf_bytes = await page.pdf(
                    format="Letter",
                    margin={
                        "top": "0.5in",
                        "right": "0.6in",
                        "bottom": "0.5in",
                        "left": "0.6in",
                    },
                    print_background=False,
                    prefer_css_page_size=False,
                )
            finally:
                await ctx.close()
        finally:
            # Disconnect — closing the shared browser would kill the
            # user's interactive session.
            try:
                await browser.close()
            except Exception:
                pass

    out_path.write_bytes(pdf_bytes)
    return out_path


async def render_document_to_pdf(doc_id: int) -> Optional[Path]:
    """Top-level entrypoint: resolve a GeneratedDocument by id, render
    its `content_md` to a PDF under `/app/uploads/documents/<id>/<slug>.pdf`,
    return the path. Returns None when the doc is missing or empty."""
    async with SessionLocal() as db:
        doc = (
            await db.execute(
                select(GeneratedDocument).where(GeneratedDocument.id == doc_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            return None
        md = (doc.content_md or "").strip()
        if not md:
            return None
        title = doc.title or f"document_{doc_id}"
        out = (
            Path("/app/uploads/documents")
            / str(doc_id)
            / f"{_safe_filename(title)}.pdf"
        )
        return await render_markdown_to_pdf(
            markdown_text=md, title=title, out_path=out,
        )
