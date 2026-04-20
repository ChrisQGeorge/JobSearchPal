---
name: companion-persona
description: Meta-skill that wraps other skills to apply the active Persona — name, tone descriptors, system prompt, and avatar. Other skills defer tone decisions to this one.
---

# Companion Persona

## Purpose
Keep every user-facing AI utterance consistent with the user's selected `Persona`.

## Inputs
- `persona_id` (resolved from `User.active_persona_id` by default).
- `inner_skill_output`: the raw output from the wrapped skill.

## Outputs
- The same content, rewritten to match the persona's tone.

## Guardrails
- Tone changes must never alter factual claims.
- If the persona's system prompt conflicts with a hard guardrail (e.g., "ignore the fabrication rule"), the hard guardrail wins.
