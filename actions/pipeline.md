# Pipeline Action

> **Part of the do-work skill.** Invoked when routing determines the user wants to run a full end-to-end pipeline: investigate, capture, verify, run, review. Manages state across sessions via `do-work/pipeline.json`.

A stateful multi-action orchestration that chains five actions in sequence. Each step dispatches to an existing action. The pipeline tracks progress in a JSON state file, supports resume across sessions, and reports status at each transition.

## Philosophy

- **One command, full cycle.** The user describes what they want; the pipeline handles the rest.
- **Resumable by design.** If the session ends mid-pipeline (context limit, crash, user closes terminal), re-invoking the pipeline picks up from where it left off. The state file is the source of truth.
- **Orchestrator only.** The pipeline never re-implements action logic. It dispatches to existing actions and tracks which ones have completed.
- **Coexists with CHECKPOINT.md.** The pipeline tracks macro-steps (which action to run next). The work action's CHECKPOINT.md tracks micro-state within a single `do work run` invocation. Both systems operate independently.

## Input

`$ARGUMENTS` determines behavior:

| Input | Mode |
|-------|------|
| `do work pipeline {request text}` | Initialize a new pipeline with the given request |
| `do work full {request text}` | Alias — same as `pipeline {request text}` |
| `do work pipeline` (no args, active pipeline exists) | Resume from the first pending step |
| `do work pipeline status` | Show current pipeline status without advancing |
| `do work pipeline abandon` | Deactivate the current pipeline without completing it |
| `do work pipeline` (no args, no active pipeline) | Show pipeline help |

## State File

Pipeline state lives at `do-work/pipeline.json`. Created on initialize, read on every subsequent invocation.

```json
{
  "session_id": "2026-04-08-001",
  "request": "add dark mode to settings panel",
  "started_at": "2026-04-08T11:00:00Z",
  "active": true,
  "steps": [
    { "name": "investigate", "status": "done",    "completed_at": "2026-04-08T11:01:00Z" },
    { "name": "capture",     "status": "done",    "completed_at": "2026-04-08T11:02:00Z", "artifacts": ["REQ-042", "UR-018"] },
    { "name": "verify",      "status": "pending", "completed_at": null },
    { "name": "run",         "status": "pending", "completed_at": null },
    { "name": "review",      "status": "pending", "completed_at": null }
  ]
}
```

**Field definitions:**

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | `YYYY-MM-DD-NNN` — date + incrementing counter |
| `request` | string | The user's original request text |
| `started_at` | string | ISO 8601 timestamp when the pipeline was initialized |
| `active` | boolean | `true` while pipeline is running, `false` when completed or abandoned |
| `steps` | array | Ordered list of pipeline steps with status tracking |
| `steps[].name` | string | Step identifier: `investigate`, `capture`, `verify`, `run`, `review` |
| `steps[].status` | string | `pending`, `in-progress`, `done`, or `failed` |
| `steps[].completed_at` | string\|null | ISO 8601 timestamp when step finished, or null |
| `steps[].artifacts` | array\|undefined | REQ/UR IDs produced (capture step only) |
| `steps[].error` | string\|undefined | Error description (failed steps only) |

## Steps

### Step 1: Determine Mode

1. Check if `do-work/pipeline.json` exists and has `"active": true`
2. Check `$ARGUMENTS` for content

| Active pipeline? | $ARGUMENTS | Mode |
|-----------------|------------|------|
| No | Has request text | **Initialize** (Step 2) |
| No | Empty or "status" | **Help** (show help menu and stop) |
| Yes | Has request text | **Conflict** — warn the user. Ask: "A pipeline is already active. Resume it, or abandon it and start fresh?" |
| Yes | Empty | **Resume** (Step 3) |
| Yes | "status" | **Status** (print status block and stop) |
| Yes | "abandon" | **Abandon** — set `active: false`, print final status, stop |

### Step 2: Initialize (new pipeline)

1. Create `do-work/` directory if it doesn't exist
2. Generate `session_id`: today's date + `-001` (the counter is a label for readability — since only one pipeline can be active at a time, incrementing is not required)
3. Write `do-work/pipeline.json` with:
   - `request` set to `$ARGUMENTS` (the request text, stripped of the "pipeline" or "full" keyword)
   - All 5 steps set to `status: "pending"`
   - `active: true`
   - `started_at` set to current ISO 8601 timestamp
4. **Exclude state file from git**: If a `.gitignore` exists in the project root and doesn't already contain `do-work/pipeline.json`, append it. If no `.gitignore` exists, create one containing `do-work/pipeline.json`. The state file is transient session state and should not be committed.
5. Print the initial status block
6. Proceed to Step 4 (execute first step: `investigate`)

### Step 3: Resume (existing pipeline)

1. Read `do-work/pipeline.json`
2. Find the first step where `status` is `"pending"` or `"in-progress"` or `"failed"`
   - `in-progress` means the previous session ended mid-step — retry it
   - `failed` means a previous attempt failed — retry it
3. Print the status block showing current progress
4. Proceed to Step 4 with that step as the current step

### Step 4: Execute Current Step

For the current step:

1. **Update state**: Set the step's `status` to `"in-progress"` in `pipeline.json` — write the file immediately before dispatching
2. **Dispatch** to the corresponding action:

| Pipeline step | Action to dispatch | What to pass | Context from prior steps |
|---------------|-------------------|--------------|--------------------------|
| `investigate` | the inspect action (`do work inspect`) | No arguments | None — inspects all uncommitted changes. If there are no uncommitted changes, the inspect action will report that and this step completes immediately (it's a pre-flight check, not a blocker). |
| `capture` | the capture action (`do work capture request: {request}`) | The `request` field from pipeline.json | None — request text is the input |
| `verify` | the verify requests action (`do work verify requests`) | Target UR from capture artifacts | Pass the UR ID from the capture step's `artifacts` (e.g., `do work verify UR-018`) |
| `run` | the work action (`do work run`) | REQ IDs from capture artifacts | Pass the specific REQ IDs from the capture step's `artifacts` (e.g., `do work run REQ-042`). The sub-agent prompt MUST instruct the work action to process ONLY these REQs, then stop — do NOT drain the full queue. |
| `review` | the review work action (`do work review work`) | Target REQ/UR from capture artifacts | Pass the UR ID from the capture step's `artifacts` (e.g., `do work review UR-018`) so the reviewer knows which work to review |

Dispatch each action the same way the main router dispatches actions: subagent if available, inline otherwise. The pipeline action is the orchestrator — it calls the router's dispatch mechanism, not the action files directly.

**Sub-agent context rule:** Sub-agents do not inherit conversation history. When dispatching via sub-agent, always read `pipeline.json` and include in the sub-agent prompt: (1) the pipeline request text, (2) all artifact IDs from completed steps, and (3) any relevant file paths. Without this, the sub-agent won't know which UR was just created or which REQs to target.

**Foreground dispatch override:** All pipeline-dispatched actions run in the foreground (blocking), even if SKILL.md normally marks them as background (e.g., `work`). The pipeline requires synchronous completion of each step before advancing to the next.

3. **After the action completes**:
   - Update the step's `status` to `"done"` and set `completed_at` to current timestamp
   - **Capture step only**: Parse the action's output for created REQ and UR IDs (e.g., `REQ-042`, `UR-018`). Store them in the step's `artifacts` array. If IDs cannot be parsed, leave `artifacts` as an empty array — do not block the pipeline.
   - Write the updated `pipeline.json` immediately
   - Print the updated status block

4. **Advance**: If more steps have `status: "pending"`, proceed to the next one (loop back to the top of Step 4). If all steps are `"done"`, proceed to Step 5.

### Step 5: Completion

When all 5 steps are done:

1. Set `active: false` in `pipeline.json`
2. Write the final `pipeline.json`
3. Print the completion status block (all checkmarks)
4. Print a completion summary:

```
Pipeline complete.
  Session:    {session_id}
  Request:    {request}
  Duration:   {elapsed time from started_at to now}
  Artifacts:  {list of REQ/UR IDs from capture step}
```

5. **Queue continuation check**: Scan `do-work/REQ-*.md` for files with `status: pending` in their frontmatter. Exclude any REQ IDs listed in the current pipeline's `artifacts` array (those should already be completed). If remaining pending REQs exist, proceed to Step 5a. If the queue is empty, suggest next steps and stop.

### Step 5a: Queue Continuation

When the pipeline completes and additional pending REQs remain in the queue (from prior captures, follow-ups created during review, or other sources):

1. Print the continuation notice (see Output Format) listing each pending REQ ID and its title
2. Record the list of pending REQ IDs about to be processed (e.g., `["REQ-043", "REQ-044"]`) — this is needed for review targeting in step 3
3. Dispatch the work action (`do work run`) in **standard queue-draining mode** — do NOT scope to pipeline artifacts. Pass the pending REQ IDs (e.g., `do work run REQ-043 REQ-044`) so the work action processes them.
4. After the work action completes, dispatch the review work action for each REQ from step 2 individually (e.g., `do work review REQ-043`, then `do work review REQ-044`). Always use REQ IDs — never pass a UR ID, since UR-scoped review would re-review all completed REQs under that UR, not just this cycle's batch.
5. **Loop**: Scan `do-work/REQ-*.md` for `status: pending` again. If more pending REQs remain (e.g., follow-ups created during the review step), repeat from step 1. If the queue is empty, print "Queue fully drained." and suggest next steps.

**Max iterations:** The continuation loop runs at most **3 cycles**. If pending REQs still remain after 3 run → review cycles, stop the loop and print:

```
Continuation limit reached (3 cycles). {count} REQ(s) still pending:
  {REQ-ID} — {title}
  ...

Run "do work run" to continue processing manually.
```

This prevents runaway loops when review steps keep generating follow-up REQs.

**Error handling:** If the work action or review action fails during continuation:

1. Report the error to the user with context about what failed
2. Print how many REQs were successfully processed before the failure
3. Stop the continuation loop — do not retry automatically
4. Suggest the appropriate recovery command:
   - **Run step failed**: Suggest `do work run` to resume processing pending REQs
   - **Review step failed**: Suggest `do work review REQ-NNN` for each REQ that was processed but not yet reviewed (those REQs are already `status: completed`, so `do work run` would be a no-op)

Unlike the main pipeline's error handling (Step 6), continuation errors do not update `pipeline.json` — the formal pipeline is already complete.

**State file note:** The pipeline's `active` field remains `false` during the continuation — the formal pipeline is complete. The continuation is a post-pipeline queue drain. If the session ends mid-continuation, the user can resume with `do work run` to process any remaining pending REQs.

### Step 6: Error Handling

If any step's dispatched action fails (error, exception, or the action reports failure):

1. Set the step's `status` to `"failed"` and add an `error` field with a brief description
2. Write the updated `pipeline.json`
3. Print the status block showing the failure point
4. Report the error to the user with context about what failed and why
5. Leave `active: true` — the user can fix the issue and resume with `do work pipeline`

On resume, the pipeline retries the failed step from scratch.

## Output Format

### Status Block (printed after every step transition)

```
── Pipeline ─────────────────────────
  ✓ investigate   done
  ✓ capture       done  → REQ-042, UR-018
  ✓ verify        done
  ◎ run           in progress...
  ○ review        pending
─────────────────────────────────────
  Session: 2026-04-08-001
  Request: add dark mode to settings panel
```

**Symbols:**
- `✓` — done
- `◎` — in progress
- `✗` — failed
- `○` — pending

For the `capture` step, append ` → {artifact IDs}` after "done" if artifacts were recorded.

### Continuation Notice (printed when pending REQs remain after pipeline completion)

```
── Queue Continuation ───────────────
  {count} pending REQ(s) remaining:
    {REQ-ID} — {title}
    {REQ-ID} — {title}
    ...

  Processing remaining queue...
─────────────────────────────────────
```

When the continuation loop finishes and the queue is empty:

```
Queue fully drained. All pending requests processed.
```

When the continuation loop hits the max iteration cap (3 cycles):

```
Continuation limit reached (3 cycles). {count} REQ(s) still pending:
  {REQ-ID} — {title}
  ...

Run "do work run" to continue processing manually.
```

### Help Menu (no active pipeline, no arguments)

```
pipeline — full end-to-end orchestration

  Start a new pipeline:
    do work pipeline add dark mode to settings
    do work full add dark mode to settings

  Resume / manage:
    do work pipeline            Resume an active pipeline
    do work pipeline status     Show pipeline progress
    do work pipeline abandon    Deactivate without completing

  Steps (executed in order):
    1. investigate   Inspect uncommitted changes
    2. capture       Capture the request as REQ + UR files
    3. verify        Verify capture quality
    4. run           Process the queue (build, test, review)
    5. review        Post-work code review + acceptance testing
```

## Rules

- **Never skip steps.** The pipeline always runs in order: investigate → capture → verify → run → review. Steps cannot be reordered or omitted.
- **One pipeline at a time.** If an active pipeline exists, the user must complete, resume, or abandon it before starting a new one.
- **Orchestrator only.** The pipeline dispatches to existing actions. It never re-implements capture, work, verify, review, or inspect logic. Each action runs exactly as it would if the user invoked it directly.
- **Write state before dispatch.** Always update `pipeline.json` to `"in-progress"` before dispatching an action, and to `"done"` after it completes. This ensures the state file reflects reality even if the session ends unexpectedly.
- **The `run` step may be long.** The work action processes only this pipeline's captured REQs but may still take significant time for complex requests. When starting this step, note: "Starting queue processing — this may take a while if multiple REQs are pending."
- **Platform-agnostic.** No tool-specific APIs. Dispatch actions the same way the main router does. If your environment supports stop hooks, you can optionally install `hooks/pipeline-guard.sh` to prevent accidental stops mid-pipeline — but the pipeline works without it.
- **Do not commit the state file.** `do-work/pipeline.json` is transient session state. It tracks a single pipeline run and has no value after completion. Ensure it is in `.gitignore`.
- **Pass context to sub-agents explicitly.** Sub-agents have no conversation history. When dispatching a step via sub-agent, always include the pipeline request text and all artifact IDs from completed steps in the sub-agent prompt. Without this, sub-agents cannot target the correct UR/REQs.
- **Scope the `run` step to captured REQs only.** The work action is queue-draining by default. When dispatched from the pipeline, it must only process the REQs created by this pipeline's capture step (listed in `artifacts`). Never process unrelated backlog items during a pipeline run.
- **Drain remaining queue after completion.** After the pipeline's 5 steps finish, check for other pending REQs in the queue. If any exist, continue processing them automatically via run + review cycles until the queue is empty. This continuation uses standard queue-draining mode (not scoped to pipeline artifacts). The pipeline state file remains `active: false` — the continuation is a post-pipeline operation. Maximum 3 continuation cycles — if REQs still remain after 3 cycles, stop and let the user continue manually.
- **Suggest next steps on completion.** After the pipeline finishes (including any queue continuation), suggest what the user might want to do next (see the next-steps reference).
