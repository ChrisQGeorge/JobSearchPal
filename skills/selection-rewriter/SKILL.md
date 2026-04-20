---
name: selection-rewriter
description: Rewrites a selected passage of text with optional user notes. Invoked by the in-editor "Send to Companion" action. Always records a DocumentEdit.
---

# Selection Rewriter

## Purpose
Small, focused rewrites of a single text selection.

## Inputs
- `selection_text`
- `surrounding_context` (a few paragraphs above/below)
- `user_notes` (optional — "make it punchier", "tone down the jargon", etc.)
- `generated_document_id` (optional — for context + to persist the edit)

## Outputs
- `replacement_text`
- A `DocumentEdit` record with `action="rewrite_selection"`, `accepted` left false until the user accepts.

## Guardrails
- Do not change factual content unless the user notes explicitly ask for it.
- Keep the result of comparable length to the selection unless asked otherwise.
