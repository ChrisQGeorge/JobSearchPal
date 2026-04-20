---
name: job-strategy-advisor
description: Reviews the user's tracked jobs, response rates, and history to recommend search-strategy adjustments — targeting, resume positioning, and skill gaps. Use when the user asks "how am I doing" or "what should I change".
---

# Job Strategy Advisor

## Purpose
A higher-level advisor that looks at the whole funnel and suggests changes.

## Inputs
- Optional: `window_days` (default 30), `focus` (`targeting`, `positioning`, `skills`, `all`).

## Outputs
- A short markdown brief with observations, hypotheses, and 3–5 concrete recommendations.

## Guardrails
- Use `MetricSnapshot` where available rather than recomputing.
- Distinguish recommendations backed by data from intuitions.
