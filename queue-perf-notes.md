# Companion-task queue — performance punch list

Deferred work from the queue-speed audit (after commit `1a7906e`,
which shipped the prep handler + status-gated panels). Ordered by
impact-per-effort. Each item names the file + line range so you (or
a future agent) can drop into the right spot.

---

## 1. Filter `_build_candidate_profile_block` by JD relevance

- **Impact:** HIGH (biggest single token win)
- **Effort:** MEDIUM
- **Where:** [`apps/api/app/api/v1/documents.py:821-1320`](apps/api/app/api/v1/documents.py)
- **What's wrong:** The resume tailor dumps the *entire* user history
  — every skill, every project, every degree, every cert — into the
  prompt regardless of relevance to the target role. For a populated
  history that's ~1500 tokens of bloat per tailor task. The prompt
  template then references the block multiple times, so model
  attention is also being burned on irrelevant material.
- **Fix shape:**
  - Skills section: keep only skills appearing in
    `job.required_skills` or `job.nice_to_have_skills` (or aliasing
    a JD term). Hide the rest behind a one-line "+ N other skills".
  - Work roles: prioritize roles with overlapping tech / domain
    keywords from the JD; truncate roles older than ~10 years to a
    one-liner unless the user explicitly pinned them.
  - Education: drop GPA when < 3.5 and the JD doesn't ask for it.
    Drop coursework lists for any degree past the most recent.
  - Projects: cap to top N by recency, prefer ones with technologies
    overlapping the JD.
- **Expected savings:** 40–60% of the candidate profile block.
  ~1000 tokens per tailor / cover-letter task.

## 2. Stop embedding tailor/humanize prompts in the queue payload

- **Impact:** MEDIUM
- **Effort:** MEDIUM
- **Where:**
  - [`apps/api/app/api/v1/documents.py:1554-1560`](apps/api/app/api/v1/documents.py) (tailor)
  - [`apps/api/app/api/v1/documents.py:2805-2812`](apps/api/app/api/v1/documents.py) (humanize)
- **What's wrong:** The full 2–10 KB prompt is built at request time
  and stuffed into `JobFetchQueue.payload.prompt`. Every tailor task
  bloats the queue row, the activity feed pulls it on every refresh,
  Excel exports of the queue table ship MB of dead prompt strings,
  and any history change between enqueue + run is ignored because the
  baked-in prompt is frozen.
- **Fix shape:** Payload stores only `{tracked_job_id, doc_type,
  extra_notes, persona_id}`. Move prompt construction into the
  handler (call the same `_build_*` helper at handler time). The
  source-of-truth user history is read freshly right before the
  Claude subprocess spawns.
- **Bonus benefit:** Fix #1 (relevance filtering) becomes easier
  because the build happens inside the worker, where loading skills
  + tracked-job is already cheap.

## 3. Cache the humanize prompt across fix-passes

- **Impact:** MEDIUM (per-task)
- **Effort:** LOW
- **Where:** [`apps/api/app/skills/queue_worker.py`](apps/api/app/skills/queue_worker.py) — `_handle_humanize` fix-pass loop, `_MAX_FIX_PASSES = 2`.
- **What's wrong:** When the validator catches AI-tells and queues
  fix-pass #1 / #2, the full prompt is rebuilt from scratch each
  time. The source body + writing samples haven't changed.
- **Fix shape:** Hoist the prompt-build call out of the retry loop;
  the fix prompt just appends a violations block to the same base.

## 4. Slim the prep + score handler's `Organization.name` lookup

- **Impact:** LOW (a few ms per task)
- **Effort:** LOW
- **Where:** `_handle_prep` in [`apps/api/app/skills/queue_worker.py`](apps/api/app/skills/queue_worker.py) (the org-name fetch is a separate query right after the job is loaded).
- **Fix shape:** Use `selectinload(TrackedJob.organization)` on the
  initial job fetch so the org row hydrates in the same round trip.
  Same opportunity exists in `_handle_score`.

## 5. Slim `_JD_PREP_PROMPT` further

- **Impact:** LOW
- **Effort:** MEDIUM
- **Where:** [`apps/api/app/api/v1/jobs.py`](apps/api/app/api/v1/jobs.py) — `_JD_PREP_PROMPT` (~350 words, just shipped).
- **What's wrong:** Still verbose. The big-picture instructions could
  probably get to ~200 words without losing fidelity, especially the
  curl examples (Claude doesn't need a literal sample command if the
  endpoint paths are listed).
- **Note:** Don't slim too aggressively — `prep` is the place where
  the output actually needs to be rich enough to drive resume tailor
  and cover letter generation. Trim *instructions*, not output
  budgets.

---

## Out of scope but adjacent

- **Polling cadence (`POLL_INTERVAL_SECONDS=5`).** Already correct
  for the workload — handlers serialize against the Claude CLI to
  respect rate limits, so faster polling wouldn't gain anything in
  practice. Don't touch unless / until queue depth is the constraint.
- **Batched `_claim_next`.** Same — the bottleneck is Claude
  inference, not DB round trips.
- **Parallelizing different task kinds.** Possible but complicates
  rate-limit handling and the shared bus. Defer until there's a
  concrete instance where serial dispatch is the bottleneck.

---

When you're ready, pick a number and tell me which to implement.
