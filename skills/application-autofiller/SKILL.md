---
name: application-autofiller
description: Produces answers to application-form fields — personal info, work authorization, voluntary demographics — from User, WorkAuthorization, and Demographics. Respects DemographicSharePolicy. Use when the user asks to fill out application fields.
---

# Application Autofiller

## Purpose
Emit values for common application fields while honoring the user's share-policy controls.

## Inputs
- `fields_requested`: list of canonical field names (e.g., `legal_name`, `pronouns`, `veteran_status`, `race_ethnicity`, `work_authorization_status`, `requires_sponsorship`).
- `tracked_job_id` (optional, for logging).

## Outputs
- A structured response with `{ field_name, value, policy_applied, source }` entries.
- An `AutofillLog` row recording exactly what was shared.
- A post-autofill summary shown to the user.

## Guardrails (hard rules)
- **Never** include demographic or identity values in the LLM prompt as free text. The backend templates names like `{{demographics.veteran_status}}` and fills them locally after LLM processing.
- `never_share` fields are omitted entirely.
- `always_share` fields are filled without prompting.
- `ask_each_time` / `share_on_request` fields require explicit user confirmation per invocation.
- `override_value` (if set on `DemographicSharePolicy`) replaces the canonical value in the response.
