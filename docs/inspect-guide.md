# Inspect

Read-only examination of uncommitted changes. Explains what changed, why, traces to REQs, and assesses commit readiness. Safe to run anytime — never modifies files or stages changes.

## Three modes

| Mode | Command | What it inspects |
|------|---------|-----------------|
| All changes | `do work inspect` | Everything uncommitted in the working tree |
| REQ scope | `do work inspect REQ-005` | Files from that REQ's Implementation Summary |
| UR scope | `do work inspect UR-003` | Files from all REQs under that UR |

## What it reports

For each group of changes:

- **What** — which files changed and how
- **Why** — the reasoning behind the changes, traced to REQs where possible
- **Readiness** — verdict per group

## Readiness signals

| Signal | What it checks |
|--------|---------------|
| Completeness | TODOs, debug code, placeholder values |
| Test Coverage | Whether test files exist for changed code |
| REQ Traceability | Traced / in-progress / untraced |
| Coherence | Conflicting or contradictory changes |
| Safety | Secrets, credentials, sensitive data |
| Improvement Hints | Light observations (1-2 sentences, not a full code review) |

## Verdicts

- **Ready** — clean, traced, no issues
- **Needs Attention** — minor concerns worth reviewing
- **Not Ready** — blocking issues found
- **Committed** — already committed (shown in REQ/UR scope mode)

## Output

Hybrid narrative + table format. Each change group gets a What/Why explanation, then a summary table with Status and Verdict columns.

## Usage

```
do work inspect
do work inspect REQ-005
do work inspect UR-003
do work explain changes
do work what changed
do work show changes
```
