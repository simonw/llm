# Review Work

Post-build quality gate: requirements check, code review, acceptance testing. Runs automatically after each work loop item, or manually on demand.

## Three review phases

### Phase 1: Requirements Check

Extracts all requirements from the REQ and original UR, then verifies each:

- **Delivered** — implemented and visible in the diff
- **Partially delivered** — some aspects implemented, others missing
- **Not delivered** — no evidence in the diff

### Phase 2: Code Review

Evaluates the diff across four dimensions:

| Dimension | What it checks |
|-----------|---------------|
| **Code Quality** (0-100%) | Patterns, naming, readability, error handling, diff hygiene |
| **Test Adequacy** (0-100%) | Meaningful tests exist, right tests run, red-green validation |
| **Scope Discipline** (0-100%) | Stayed focused, no feature creep, files touched match declared scope |
| **Risk** (Critical/Low/None) | Security, performance, data integrity, regression risk |

### Phase 3: Acceptance Testing

Actually runs the code to verify it works end-to-end:

- Happy path first, then edge cases
- For bug fixes, confirms the original bug no longer reproduces
- Checks for regressions in adjacent features

Result: **Pass** / **Partial** / **Fail** / **Untested**

## Scoring

Averages the percentage dimensions with qualitative modifiers:

| Range | Meaning |
|-------|---------|
| 90-100% | Ship-ready |
| 75-89% | Minor issues, not worth blocking |
| 50-74% | Needs attention |
| Below 50% | Significant problems |

Critical risk caps at 60%. Acceptance fail caps at 50%.

## Guardrails

Includes anti-rationalization tables, red flags (patterns that trigger extra scrutiny like "summary lists files but diff shows no changes"), and a verification checklist to ensure all scoring dimensions are filled and every requirement is walked against the diff.

## Follow-ups

Important findings generate follow-up REQ files automatically. Minor findings stay in the report only.

## Output

Structured report with scores table, requirements checklist, findings by severity, acceptance result, and suggested additional testing.

## Usage

```
do work review work              # most recent completed REQ
do work review REQ-005           # specific REQ
do work review UR-003            # all completed REQs under a UR
do work review code
```
