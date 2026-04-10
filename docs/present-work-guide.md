# Present Work

Transforms completed work into client-facing deliverables — briefs, architecture diagrams, video scripts, and interactive explainers.

## Two modes

### Detail mode (single work item)

Generates a full set of artifacts for one UR or REQ:

1. **Client Brief** — plain-language writeup: What We Built, How It Works, Architecture, Data Flow, Key Decisions, Value Delivered, What's Next
2. **Remotion Video** — 4-scene interactive video (Problem → Solution → Architecture → Value), generated as source code previewed via `npx remotion studio`
3. **Interactive Explainer** — single-file HTML with Tailwind CSS, zero build steps, Before/After toggle or step-by-step walkthrough, dark mode support

### Portfolio mode (all completed work)

Scans the archive and generates a portfolio summary with cumulative value proposition across all completed URs.

## Where artifacts go

All deliverables are saved to `do-work/deliverables/`.

## Depth calibration

Effort scales with the work:

- Config change → brief only
- Single feature → brief + explainer
- Multi-feature / architectural → brief + architecture diagram + video + explainer

## Principles

- Educate first, sell second
- Technical accuracy in plain language (no code snippets in client-facing docs)
- Honest value — no fabricated metrics
- Pointers to files over prose

## Usage

```
do work present work             # most recent completed UR
do work present UR-003           # specific UR
do work present REQ-005          # specific REQ
do work present all              # portfolio summary
do work present portfolio        # same as all
do work showcase
```
