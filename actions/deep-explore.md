# Deep-Explore Action

> **Part of the do-work skill.** Explores a concept in depth through multi-round structured dialogue between specialized subagents — a Free Thinker (divergent generation), a Grounder (convergent evaluation), and a Writer (neutral synthesis). Produces idea briefs and a consolidated vision document.

**Self-contained** — this action does not depend on any external skills or plugins.

**Companion file:** Read `actions/deep-explore-reference.md` for subagent persona prompts, convergence rubric, source capture procedure, state file schema, and error handling.

## Philosophy

A single agent combining generation and evaluation in one pass produces mediocre output — it self-censors during creation and gets attached during evaluation. This action separates cognitive modes across distinct subagent roles:

- **Free Thinker** — generates without evaluating. Creative range is the goal.
- **Grounder** — evaluates without generating. Winnows, challenges, redirects.
- **Writer** — synthesizes without advocating. No perspective to protect.
- **Explorer** (optional) — researches without creating. Reports facts only.

The separation is enforced by spawning each role as a separate subagent with its own persona prompt. Each subagent reads the prior rounds' output files and writes its own output to a new file. The orchestrator (you) coordinates rounds, evaluates progress, and decides when to converge.

**Sub-agent note:** This document uses "spawn agent" language. Use your platform's subagent mechanism when available. If your tool doesn't support subagents, run phases sequentially in the same session and label outputs clearly: "I am now in Free Thinker mode — generating without evaluating." The cognitive separation still applies — do not evaluate during generation or generate during evaluation, even in single-session mode.

## When to Use This vs `do work scan-ideas`

| `do work scan-ideas` | `do work deep-explore` |
|----------------------|------------------------|
| Quick scan of existing codebase | In-depth exploration of a concept |
| Output: ranked list of tasks | Output: vision document + idea briefs |
| Grounded in files, TODOs, gaps | Grounded in the seed idea and project context |
| Single pass, minutes | Multi-round dialogue, extended session |
| "What should I work on next?" | "I have a seed idea — develop it" |

## Input

`$ARGUMENTS` determines the session mode:

- A concept description → new session exploring that concept
- A file path → read the file as the concept seed
- A topic keyword (e.g., "performance", "onboarding") → explore that theme in the project context
- `continue <path-or-keyword>` → resume a previous session (see Continue Mode below)
- Empty → gather project context and ask the user what to explore

---

## Session Mode Detection

### New Mode (default)

Triggered whenever `$ARGUMENTS` does **NOT** start with "continue". Proceed to Step 1.

### Continue Mode

Triggered when `$ARGUMENTS` starts with **"continue"**.

**Resolving the session directory:**

1. **Path given and exists** — use it directly as the session directory.
2. **Keyword given (not a path)** — search the project root for directories matching `deep-explore-*<keyword>*`:
   - **Single match** → use it directly.
   - **Multiple matches** → present matches to the user and let them choose.
   - **No matches** → ask the user for clarification.
3. **Nothing found** — stop and ask.

**Once resolved:**

1. Read `session/state.json` to understand session state.
2. Read existing artifacts: `session/VISION_*.md`, `session/briefs/*.md`, `session/ideation-graph.md`, `session/sources/manifest.md`.
3. Skip Steps 1-2 (context and directory creation — already done).
4. Still assess research needs (Step 3) — the user may have new research questions.
5. Resume from the step indicated by state.json, or start new rounds with prior context.
6. When spawning subagents, include prior context: *"This is a continuation of a previous session. Here are the prior vision and briefs. Build on this work — do not start from scratch."*

---

## Step 1: Gather Context and Read the Seed

Build a picture of the project and the concept before exploring:

1. **Prime files**: Glob for `**/prime-*.md` — understand the architecture, entry points, conventions. Summarize the project landscape in 2-3 sentences.
2. **Recent work**: Check `do-work/archive/` for the most recent 5 completed URs. Note the trajectory — what direction has recent work been heading?
3. **Queue state**: Check `do-work/queue/` for pending REQs — known gaps that may inform exploration.
4. **The seed**: Read `$ARGUMENTS` carefully. Understand not just the stated idea but the intent behind it — what problem is the user trying to solve, what excites them about it, what tensions exist in their thinking.

If `$ARGUMENTS` is empty, present the project context to the user and ask: "What concept would you like to explore? Here's where the project has been heading: [summary]." Wait for their response.

If `$ARGUMENTS` is a file path, read the file as the seed.

---

## Step 2: Create Session Directory and Capture Sources

### Create the directory

Each session gets a unique, timestamped directory at the project root:

```bash
SESSION_DIR="deep-explore-$(echo '<concept-slug>' | tr ' ' '-' | tr '[:upper:]' '[:lower:]')-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$SESSION_DIR"/session/sources "$SESSION_DIR"/session/idea-reports "$SESSION_DIR"/session/briefs "$SESSION_DIR"/session/research
```

### Capture sources

Follow the source capture procedure in `deep-explore-reference.md`. Copy all input materials (files, URLs, images) into `session/sources/` with a manifest.

### Initialize state

Write `session/state.json` with the initial state. See the state file schema in `deep-explore-reference.md`.

Store the resolved session output path — all subagents need it in their prompts.

---

## Step 3: Assess Research Needs

After capturing sources, decide whether the **Explorer** subagent is needed.

**Decide one of three modes:**

- **Pre-session research** — The seed requires investigation before the thinkers can start productively. Examples: the user gives a URL with no other context, or the concept references a domain that needs background. In this mode, spawn the Explorer first, wait for its report, then proceed to Step 4 with the report as additional context.

- **On-demand research** — There's enough context to start, but research questions may arise during rounds. In this mode, skip the Explorer for now. If a Free Thinker or Grounder round output contains questions like "does this already exist?" or "what's the standard approach?", spawn the Explorer between rounds and include its report in the next round's input.

- **No research needed** — The concept seed is self-contained. Skip the Explorer entirely.

Record your decision in state.json (`research_mode` field).

**If pre-session research:** Spawn a subagent with the Explorer persona from `deep-explore-reference.md`. Input: the concept seed + specific research questions. The Explorer writes its report to `session/research/RESEARCH_<slug>.md`. Wait for completion before proceeding.

---

## Step 4: Round 1 — Free Thinker (Diverge)

Spawn a subagent with the Free Thinker persona from `deep-explore-reference.md`.

**Context to pass:**
- The concept seed
- Project context (primes summary, recent work trajectory, queue state)
- Any Explorer research report (if pre-session research was done)
- The Round 1 suffix instructions from the reference file

**The subagent writes to:** `{session-output}/session/idea-reports/ROUND-01-diverge.md`

Update state.json after the subagent completes.

---

## Step 5: Arbiter Evaluation 1

You (the orchestrator) read the Free Thinker's output. This is an inline evaluation — do not spawn a subagent.

**Quick check:**
- Are there at least 6 directions? If < 5, re-spawn the Free Thinker with "push further" guidance (max 1 retry). See error handling in the reference file.
- Do they show creative range (not all variations of the same idea)?
- Is there enough material for the Grounder to work with?

If satisfactory, proceed to Step 6. Record evaluation notes in state.json.

---

## Step 6: Round 2 — Grounder (Converge)

Spawn a subagent with the Grounder persona from `deep-explore-reference.md`.

**Context to pass:**
- The concept seed
- Project context
- The Free Thinker's output (Round 1 file)
- Any research reports
- The Grounder round suffix from the reference file

**The subagent writes to:** `{session-output}/session/idea-reports/ROUND-02-converge.md`

Update state.json after the subagent completes.

---

## Step 7: Arbiter Evaluation 2 — Decide More Rounds

Read the Grounder's output. Apply the convergence rubric from `deep-explore-reference.md`.

**Decision fork:**

- **More rounds needed** → proceed to Step 7a
- **Ready for Writer** → proceed to Step 8

At minimum, every session gets 1 round pair (Steps 4-6). Most benefit from 2 pairs. Hard cap at 3 pairs.

### Step 7a: Additional Round Pairs

For each additional pair:

1. **Free Thinker round** — Spawn with the Round 3+ suffix from the reference file. Input: all prior round files. Output: `session/idea-reports/ROUND-{NN}-diverge.md`.
2. **Arbiter evaluation** — Read output, quick check.
3. **Grounder round** — Spawn with round suffix. Input: all prior round files. Output: `session/idea-reports/ROUND-{NN}-converge.md`.
4. **Arbiter evaluation** — Apply convergence rubric. Loop or proceed to Step 8.

Update state.json after each round.

**On-demand research:** If any round's output contains research questions, spawn the Explorer between rounds. Include its report in the next round's subagent context.

---

## Step 8: Writer (Synthesize)

Spawn a subagent with the Writer persona from `deep-explore-reference.md`.

**Context to pass:**
- The concept seed
- Project context
- **ALL** round transcript files (every `ROUND-*.md` in `session/idea-reports/`)
- Any research reports in `session/research/`
- The Writer task suffix from the reference file (specifying all 4 outputs + template paths)

**The Writer produces:**
1. `session/ideation-graph.md` — thread evolution map
2. `session/briefs/BRIEF_<slug>.md` — one per surviving direction
3. `session/VISION_<concept>.md` — consolidated vision document (source of truth)
4. `session/SESSION_SUMMARY.md` — session recap

Update state.json: set `writer_status: "done"`, `status: "complete"`, `completed_at: <timestamp>`.

---

## Step 9: Present Results

Read the vision document and briefs. Present to the user:

```
DEEP EXPLORATION — [concept name]

  Session: [session directory path]
  Rounds: [N] ([M] diverge + converge pairs)
  Directions explored: [total] → [surviving] developed into briefs

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Developed directions:
    1. [Name] — [one-line summary]
    2. [Name] — [one-line summary]
    ...

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [Vision Document — full text]

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [Individual Briefs]
```

---

## Rules

- **Separate the modes.** Do not evaluate during diverge. Do not generate during converge. Do not advocate during synthesis. Each subagent stays in its lane. This separation is the entire value of the method.
- **Orchestrator never generates ideas.** You coordinate, evaluate, and decide convergence. You do not add your own ideas to the mix.
- **File-based communication.** Each round writes to its own file. The Writer needs the full dialogue trail — not just the final state. Never overwrite prior round files.
- **Ground in context.** Every direction should connect to something real — the project's architecture, its users, its trajectory, or the seed concept itself.
- **Read-only by default.** The session directory is the only thing created. Do not create REQs, modify code, or capture requests. The user decides what to act on after seeing the results.
- **Respect the seed.** Explore around it, through it, and beyond it — but don't abandon it for something unrelated.
- **No duplicates.** Check the queue and recent archive. If a direction overlaps with pending or completed work, note the overlap and explore what's different.
