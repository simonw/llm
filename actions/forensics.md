# Forensics Action

> **Part of the do-work skill.** Invoked when routing determines the user wants pipeline diagnostics. Read-only — examines the state of the do-work system without modifying anything.

A diagnostic tool for when the work pipeline feels broken, stuck, or produces confusing results. Reads git history, file system state, and archived REQs to detect problems and report findings.

## Core Rules

- **Read-only.** This action never modifies files, moves REQs, updates frontmatter, or creates commits. It only reads and reports.
- **Safe to run anytime.** No side effects. Can be run mid-session, between sessions, or when troubleshooting.
- **Report, don't fix.** Findings include what's wrong and a suggested fix, but the user decides what to act on.

## Checks

Run all checks in order. Skip any check that doesn't apply (e.g., skip git checks if not a git repo).

### 1. Stuck Work

Look inside `do-work/working/` for any `REQ-*.md` files.

For each found:
- Read `claimed_at` from frontmatter
- Calculate how long it's been there
- **Warning** if claimed >1 hour ago (likely a crashed session)
- **Critical** if claimed >24 hours ago (definitely abandoned)

Report: file name, title, route, how long stuck, last known phase (check which `##` sections exist — Triage, Plan, Exploration, Implementation Summary, etc.)

**Suggested remediation:** Run `do work cleanup` — Pass 0 will sweep any REQ with a terminal status. For a truly stuck `claimed` REQ (still in-progress, not terminal), manually reset `status: pending`, remove `claimed_at` and `route` from frontmatter, strip incomplete sections, and move the file back to `do-work/` root, then run `do work cleanup`.

### 2. Hollow Completions

Scan `do-work/archive/` (including `UR-*/` subdirectories) for REQs with `status: completed` or `status: completed-with-issues`.

For each, check:
- Does `## Implementation Summary` exist?
- Does the `**Files changed:**` section list any non-`do-work/` paths?
- If both are missing or empty: **Critical** — this REQ was marked complete but has no evidence of implementation

Exception: REQs with `builder_decided: true` or containing "No changes needed" in Implementation section are legitimate completions without code changes.

### 3. Missing Qualifications

Scan archived REQs for those missing a `## Qualification` section.

- **Info** for REQs completed before v0.38.0 (no `## Qualification` section expected)
- **Warning** for REQs completed after v0.38.0 that lack it (qualification may have been skipped)

Heuristic: if the REQ has `## Scope` or `## Pre-Flight` sections, it's post-v0.38.0 and should have `## Qualification`.

### 4. Orphaned URs

List all UR folders in `do-work/user-requests/`. For each:
- Read the `requests` array from `input.md` frontmatter
- Check if ALL referenced REQs exist in `do-work/archive/` (either at root or inside `archive/UR-NNN/`)
- If all REQs are archived but the UR is still in `user-requests/`: **Warning** — this UR should have been moved to `archive/`

### 5. Scope Contamination

Collect all `## Implementation Summary` sections from archived REQs. Parse the file lists.

Build a map: `file path → [list of REQ IDs that modified it]`

For any file modified by 3+ unrelated REQs (different `user_request` values): **Warning** — potential scope contamination or architectural hotspot.

For any file modified by 2+ REQs within the same UR where the REQs are not linked by `addendum_to`: **Info** — possible overlap in requirement decomposition.

### 6. Failed Without Follow-Up

Scan archived REQs with `status: failed`.

For each, check:
- Does `error_type` exist in frontmatter? If not: **Warning** — failure not classified (pre-v0.38.0 or skipped)
- For `error_type: intent`, `spec`, or `code`: does a follow-up REQ exist with `addendum_to` pointing to this REQ? If not: **Warning** — failure has no recovery path

### 7. Stale Pending-Answers

Scan `do-work/` root for REQs with `status: pending-answers`.

For each, check `created_at`:
- **Info** if 3-7 days old
- **Warning** if >7 days old — these questions are going stale and may no longer be relevant

### 8. Git Divergence (git repos only)

Check for git with `git rev-parse --git-dir 2>/dev/null`. If not a git repo, skip.

For recently archived REQs (last 10 with `commit` in frontmatter):
- Read the `## Implementation Summary` file list
- For each file listed as `(new)` or `(modified)`: check if it still exists and if it was modified after the REQ's commit (`git log --since` on the file)
- **Info** if files were modified by later commits (expected for active development)
- **Warning** if files listed as `(new)` no longer exist (may have been deleted without tracking)

### 9. Stranded Finished REQs

Scan `do-work/REQ-*.md` (root, not archive) AND `do-work/working/REQ-*.md` for REQs with any terminal status: `completed`, `completed-with-issues`, `failed`, or non-standard variants like `done`, `finished`, `closed`.

**Queue root findings:** Group by `user_request` frontmatter field. For each UR group:
- **Warning**: "UR-NNN has N completed REQs stranded in queue root awaiting archive: REQ-NNN, REQ-NNN, ..."
- REQs without a `user_request` field are grouped separately as "unlinked."

**Working directory findings:** For each terminal-status REQ in `do-work/working/`:
- **Warning**: "REQ-NNN is in working/ with terminal status '{status}' — finished but never moved out"

**Suggested fix** for all: `do work cleanup` (Pass 0 sweeps finished REQs to archive)

## Output Format

```markdown
# Forensics Report

**Scan date:** [timestamp]
**Queue:** [N pending, N completed/done (awaiting archive), N pending-answers]
**Archive:** [N completed, N completed-with-issues, N failed]
**Working:** [N in-progress]

## Critical Findings

- **[Stuck Work]** REQ-042 has been in `working/` for 3 days (claimed 2026-03-27T10:00:00Z). Last phase: Implementation Summary exists, no Testing section. Likely crashed during test execution.
  **Suggested fix:** Move back to `do-work/` root with `status: pending` and strip incomplete sections, or investigate and complete manually.

- **[Hollow Completion]** REQ-015 is `status: completed` but has no Implementation Summary. No files were changed.
  **Suggested fix:** Review the archived REQ — was this a legitimate no-op, or was it incorrectly marked complete?

## Warnings

- **[Failed Without Follow-Up]** REQ-031 failed with no `error_type` and no follow-up REQ. Failure reason: "Tests fail repeatedly."
  **Suggested fix:** Classify the failure and create a follow-up REQ with context from the original.

- **[Stale Pending-Answers]** REQ-025 has been pending-answers for 12 days. Questions may no longer be relevant.
  **Suggested fix:** Run `do work clarify` to review, or discard if the questions are stale.

## Info

- **[Scope Contamination]** `src/utils/auth.ts` was modified by REQ-003, REQ-015, and REQ-031 (3 different URs). This file is a hotspot.
- **[Git Divergence]** `src/components/Header.tsx` (from REQ-020) was modified by 2 later commits.

## Summary

[N] critical, [N] warnings, [N] info items found.
[1-2 sentence recommendation based on findings]
```

Omit sections with no findings. If everything is clean, report:

```
# Forensics Report

**Scan date:** [timestamp]
**Queue:** [N pending, N completed/done (awaiting archive), N pending-answers]
**Archive:** [N completed, N failed]

All clear — no issues detected.
```

## When to Run

- After a session crash or unexpected termination
- When REQs seem to be "disappearing" or producing unexpected results
- Before starting a large batch of work (health check)
- When onboarding to a project that already has `do-work/` history
- Periodically, as a quality audit
