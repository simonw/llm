# Clarify Questions Action

> **Part of the do-work skill.** Batch-reviews pending questions from completed work — the user confirms, overrides, or discards builder decisions.

This is the second human-attention window in the pipeline. After the work action processes requests autonomously, any ambiguities the builder encountered are surfaced here as a batch for efficient review.

## Input

Triggered by `do work clarify` (also: `answers`, `questions`, `pending`, `what's blocked`). No arguments needed.

## Steps

### Step 1: Scan the queue

Find all `REQ-*.md` files in `do-work/` with `status: pending-answers`.

### Step 2: Check for pending questions

If none found: report "No pending questions — queue is clear" and exit.

### Step 3: Present questions

For each `pending-answers` REQ, show:

```
REQ-025 — Review fix: dark mode sidebar
(follow-up to REQ-003, from review)

1. [ ] Should the sidebar use the same dark palette as the main content?
   Recommended: Yes, match main content palette
   Also: Separate sidebar palette, User-configurable

2. [ ] Should dark mode persist across sessions?
   Recommended: Yes, save to localStorage
   Also: Reset on refresh, Follow OS preference
```

### Step 4: Collect answers

If your environment has a structured question prompt (multi-question UI), batch questions in groups of **at most 4 per prompt** — chunk by question count, not by REQ. A REQ with 6 questions needs 2 prompts.

For each question, the user can:

- **Answer it** → update to `- [x] [question] → [user's answer]`
- **Confirm builder's choice** → update to `- [x] [question] → Confirmed: [builder's choice]`. Then check the REQ type:
  - *Discovered-task REQ* (has a "Should I process this as a new task?" question with recommended "Yes, add to queue"): flip `status` to `pending` so the task enters the work queue — see "Approved Discovered Task" below
  - *All other REQs* (builder-decision follow-ups): mark `status: completed` (no implementation needed — see "Builder Was Right" below)
- **Pick a different option** → update to `- [x] [question] → [user's chosen option]`
- **Skip for now** → leave as `- [ ]`, REQ stays `pending-answers`
- **Discard it** → update to `- [x] [question] → Discarded`, then mark the REQ `status: completed`, `completed_at: <timestamp>`, and archive it directly (same pattern as "Builder Was Right" — no implementation work)

### Step 5: Activate answered REQs

For each REQ that wasn't already completed or discarded: if all questions are now `[x]` or `[~]`, flip `status` from `pending-answers` to `pending`. These enter the queue for the next `do work run`.

### Step 6: Report

Summary of what was resolved and what's still pending.

## Builder Was Right / Discarded

When the user reviews a `pending-answers` follow-up and confirms that the builder's original choice was correct (i.e., no implementation change needed):

1. Update the question to `- [x] [question] → Confirmed: [builder's choice]`
2. Update frontmatter: `status: completed`, `completed_at: <timestamp>`
3. Archive the follow-up REQ directly (skip the work loop — there's nothing to build)
4. Append a brief note: `## Implementation\n\n**No changes needed.** User confirmed builder's choice from [original REQ].\n\n*Resolved via clarify questions*`

**Discarded discovered tasks:** When the user reviews a discovered-task follow-up and chooses "No, discard it", the same fast-path applies. Mark `status: completed`, archive directly, and append: `## Implementation\n\n**Discarded.** User chose not to process this discovered task from [original REQ].\n\n*Resolved via clarify questions*`

## Approved Discovered Task

When the user reviews a discovered-task follow-up (one whose question is "Should I process this as a new task?" with recommended "Yes, add to queue") and confirms the recommendation:

1. Update the question to `- [x] [question] → Confirmed: Yes, add to queue`
2. Update frontmatter: `status: pending` (NOT `completed` — this task needs to be built)
3. **Do not archive.** The REQ stays in `do-work/` and enters the normal work queue for the next `do work run`

This is distinct from "Builder Was Right" because confirming a discovered task means the user wants it *executed*, not signed off. The task has no prior implementation to confirm — it's a new piece of work that needs a full work cycle.

## Rules

- This action avoids wasting a work cycle on a REQ that just needs sign-off or rejection, while correctly routing approved discovered tasks into the build queue
- Never block the user — if they skip all questions, exit gracefully
- Always show the builder's recommended choice prominently so confirming is the fast path
