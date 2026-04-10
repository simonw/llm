# Work Action — Reference

> Companion file to `work.md`. Contains the orchestrator checklist, error handling table, progress reporting template, and common mistakes. Extracted to keep the main action file focused on procedural steps.

## Orchestrator Checklist (per request)

```
□ Step 1: Find next request (read CHECKPOINT.md if exists, crash recovery, validate frontmatter, pick first pending)
□ Step 2: Claim request (mkdir -p working/, move REQ, update status & claimed_at)
□ Step 3: Triage (decide route, append ## Triage, read original if addendum)
□ Step 3.5: Handle Open Questions (mark - [~] with D-XX numbered decisions)
□ Step 4: Plan (Route C: spawn Plan agent + validate plan / Routes A & B: note skipped)
□ Step 5: Explore (Routes B & C: spawn Explore agent, include prime file lessons)
□ Step 5.5: Scope Declaration (Routes B & C: declare files + acceptance criteria in REQ)
□ Step 5.75: Pre-Flight Check (Routes B & C: git clean, test baseline, dependencies)
□ Step 6: Implement (spawn agent with lessons + TDD mode if set, log decisions as D-XX)
□ Step 6.25: Implementation Summary (append file manifest — mandatory for all routes)
□ Step 6.3: Qualify (orchestrator verifies: files exist, substantive, wired, flowing, requirements traced, P-A-U audit)
□ Step 6.5: Test (run relevant tests, load debug rules on attempt 2+, verify TDD evidence if tdd:true)
□ Step 7: Review (spawn review action — gate on acceptance: Pass→archive, Fail→remediate with debug rules)
□ Step 7.5: Lessons Learned (append section, update prime files, skip for Route A if no surprises)
□ Step 8: Archive (update status, classify failures, triage discovered tasks, cycle-check follow-ups, queue follow-ups, move to archive/)
□ Step 9: Commit (stage explicit files, commit if git repo, write hash to REQ in separate metadata commit)
□ Step 10: Loop or Exit (context wipe + contamination check if looping, else write CHECKPOINT.md with depth + cleanup)
```

## Common Mistakes

- Spawning implementation agent without first moving file to `working/`
- Letting spawned agents handle file management (only the orchestrator moves/archives files)
- Forgetting to update status in frontmatter (only two transitions: `claimed` at Step 2, final status at Step 8)
- Archiving a UR folder before all its REQs are complete
- Forgetting Planning status note for Routes A/B ("Planning not required")
- Using `git add -A` instead of staging specific files
- Using `--no-verify` to bypass a failing pre-commit hook instead of fixing the issue
- Committing without validating Implementation Summary file list against staged files
- Implementation Summary that only lists `do-work/` paths (means the REQ wasn't actually implemented — exception: `domain: ui-design` design artifacts placed in project directories like `docs/design/`)
- Creating follow-ups for every `- [~]` item instead of only UX-affecting decisions

## Error Handling

| Phase | Action |
|-------|--------|
| `pending-answers` REQs remain after queue is empty | Report them to the user: list each REQ and its unresolved questions. Suggest `do work clarify` to batch-review. |
| Plan agent fails (Route C) | Classify failure (Intent/Spec/Code/Environment), create follow-up REQ if applicable, archive as failed |
| Explore agent fails (B/C) | Proceed to implementation with reduced context — builder can explore on its own |
| Implementation fails | Classify failure (Intent/Spec/Code/Environment), create follow-up REQ if applicable, archive as failed |
| Tests fail repeatedly | After 3 fix attempts, classify as Code failure, create follow-up REQ with test failure details, archive as failed |
| Review: Acceptance = Fail | Return to Step 6 for ONE remediation attempt, then re-review. If still failing: archive as `completed-with-issues` with follow-up REQs |
| Review work agent fails | Skip review, note it in the REQ file, continue to archive — review failure is not a gate |
| Commit fails | Investigate the error (usually a pre-commit hook failure). Fix the underlying issue, re-stage, and retry as a **new** commit. Do NOT use `--no-verify` to skip hooks or `--no-gpg-sign` to bypass signing — fix the root cause. If unfixable, report the error to the user and continue to next request — changes remain uncommitted but archived. |
| Unrecoverable error | Stop loop, report clearly, leave queue intact for manual recovery |

## Progress Reporting

Keep the user informed with this format:

```
Processing REQ-003-dark-mode.md...
  Triage: Complex (Route C)
  Open Questions: 2 found → builder decided (follow-ups queued)
  Planning...     [done]
  Scope...        [done] 4 files declared
  Exploring...    [done]
  Implementing... [done]
  Summary...      [done] 3 files changed
  Qualifying...   [done] ✓ files verified, requirements traced
  Testing...      [done] ✓ 12 tests passing
  Reviewing...    [done] 92% — 0 follow-ups
  Archiving...    [done]
  Committing...   [done] → abc1234

Processing REQ-004-fix-typo.md...
  Triage: Simple (Route A)
  Implementing... [done]
  Summary...      [done] 1 file changed
  Qualifying...   [done] ✓ verified
  Testing...      [done] ✓ 3 tests passing
  Reviewing...    [done] 88% — 0 follow-ups
  Archiving...    [done]
  Committing...   [done] → def5678

All 2 requests completed:
  - REQ-003 (Route C) → abc1234 [review: 92%]
  - REQ-004 (Route A) → def5678 [review: 88%]
```

## What This Action Does NOT Do

- Create new request files (use the capture requests action)
- Make architectural decisions beyond what's in the request
- Run without user present (this is supervised automation)
- Modify already-completed requests
- Allow external modification of files in `working/` or `archive/`
