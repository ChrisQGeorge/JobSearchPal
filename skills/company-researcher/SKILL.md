---
name: company-researcher
description: Gathers publicly available information about a company — recent news, tech stack hints, reputation signals — and writes a summary to Company.research_notes. Use when a new TrackedJob is created or the user explicitly requests research.
---

# Company Researcher

## Purpose
Assemble a short, cited summary of a company from public sources.

## Inputs
- `company_id`
- Optional: `depth` (`quick` / `standard` / `deep`), `focus` (e.g., `culture`, `tech_stack`, `compensation`).

## Outputs
- Writes to `Company.research_notes` (narrative markdown).
- Appends to `Company.source_links` and `Company.reputation_signals`.
- Populates `Company.tech_stack_hints` when hints are found.

## Guardrails
- Only summarize publicly available information.
- Respect `robots.txt` and HTTP etiquette for outbound fetches.
- Do not include speculation — mark uncertain items `unverified`.
