# Verify Requests

Quality-check captured REQs against the original user input before building. Catches lost requirements, dropped UX details, missing intent signals, and incomplete coverage.

## When to use

- After capturing a complex request (validation gate before building)
- When you suspect the capture missed nuances
- Before starting the work loop on important requests

## What it checks

Each REQ is scored on five dimensions:

| Dimension | What it measures |
|-----------|-----------------|
| **Requirements Coverage** | Are all requirements from the original input captured? Specific values, constraints, edge cases preserved? |
| **UX/Interaction Details** | Interaction behaviors, visual/layout requirements, state transitions |
| **Intent Signals** | Certainty level (exploratory vs. firm), scope cues ("keep it simple"), tone |
| **Red-Green Proof** | Concrete RED case, why it's RED today, what turns it GREEN (testable requests only) |
| **Batch Context** | Cross-cutting constraints, sequencing, shared design principles (multi-REQ batches only) |

## Scoring

| Range | Meaning |
|-------|---------|
| 90-100% | Excellent — ready to build |
| 75-89% | Good — minor gaps, fix if convenient |
| 50-74% | Needs attention — important details missing |
| Below 50% | Significant gaps — needs rework |

## Gap severity

- **Important** — firm requirements completely dropped or significantly under-captured
- **Minor** — clear details over-summarized or soft preferences missed
- **Nit** — passing mentions or stylistic preferences (won't affect build)
- **Ambiguous** — the original input itself is unclear (only the user can resolve)

Ambiguous gaps are surfaced as questions with concrete options. You can resolve them on the spot, defer to the builder, or leave them open.

## Output

- Overall confidence score
- Per-REQ score table across all dimensions
- Gaps organized by severity
- Specific actionable recommendations

## Usage

```
do work verify requests          # most recent UR
do work verify UR-003            # specific UR
do work check REQ-018            # specific REQ (finds its UR)
do work evaluate
```
