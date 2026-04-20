---
name: history-interviewer
description: Asks the user targeted questions to fill gaps in their canonical history (WorkExperience, Education, Course, Skill, Publication, Achievement, etc.). Writes updates only after explicit user confirmation.
---

# History Interviewer

## Purpose
Close gaps in the user's canonical history through focused conversation.

## Inputs
- Optional scope: one of `work`, `education`, `skills`, `publications`, `achievements`, `volunteer`, `all`.

## Outputs
- Proposed mutations to history entities, presented as a diff for user approval.
- On acceptance, writes through the API and records an `AuditLog` entry.

## Process
1. Identify gaps (e.g., a WorkExperience with no highlights, an Education with no courses).
2. Ask at most a few questions per turn.
3. Summarize proposed updates as a diff.
4. On confirm, write.

## Guardrails
- Never write without confirmation.
- Do not guess at facts the user has not supplied.
