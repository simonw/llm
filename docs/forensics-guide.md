# Forensics

Pipeline diagnostics — detects stuck work, hollow completions, orphaned URs, scope contamination, and other health issues. Read-only and safe to run anytime.

## What it checks

| Check | What it detects |
|-------|----------------|
| **Stuck work** | REQs in `working/` claimed >1hr (warning) or >24hr (critical) |
| **Hollow completions** | Completed REQs with no Implementation Summary or file changes |
| **Missing qualifications** | REQs lacking `## Qualification` section (post-v0.38.0) |
| **Orphaned URs** | UR folders in `user-requests/` where all REQs are archived but UR wasn't moved |
| **Scope contamination** | Files modified by 3+ unrelated REQs, or overlapping files within same UR |
| **Failed without follow-up** | Failed REQs missing error classification or follow-up REQ |
| **Stale pending-answers** | REQs waiting for user input for >7 days |
| **Git divergence** | Files from completed REQs later modified or deleted without tracking |
| **Stranded finished REQs** | Terminal-status REQs left in queue root or `working/` instead of archived |

## Output

Markdown report organized by severity:

- **Critical Findings** — needs immediate attention
- **Warnings** — should be addressed soon
- **Info** — awareness items

Each finding includes a suggested fix. Sections with no findings are omitted.

## Key rules

- Read-only — reports findings, never auto-fixes
- User decides what to act on

## Usage

```
do work forensics
do work diagnose
do work health check
do work health
```
