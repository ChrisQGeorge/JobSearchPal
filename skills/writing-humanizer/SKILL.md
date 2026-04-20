---
name: writing-humanizer
description: Rewrites AI-generated text to match the user's voice using WritingSample records as reference. Invoked implicitly by other generation skills and directly by selection-rewriter.
---

# Writing Humanizer

## Purpose
Bring AI-generated text into the user's voice.

## Inputs
- `text`: the draft to humanize.
- Optional: `sample_tag_filter` (only draw from samples tagged X), `target_register` (formal/casual), `preserve_structure` (bool).

## Outputs
- Humanized text.
- References to the `WritingSample` IDs used as signal.

## Guardrails
- Preserve factual content. This skill rewords; it does not change what is claimed.
- If no writing samples exist, return the input unchanged and emit a warning.
