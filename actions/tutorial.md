# Tutorial Action

> **Part of the do-work skill.** Interactive tutorials that teach users how the skill works. Four modes cover different learning styles — from hands-on walkthrough to reference cheat sheet.

## Modes

| Mode | Trigger | What it does |
|------|---------|-------------|
| **Quick Start** | `do work tutorial quick-start` | Hands-on walkthrough: capture one task, run it, review it. ~5 minutes. |
| **Concepts** | `do work tutorial concepts` | Explains the mental model: URs, REQs, pipeline stages, trail of intent. Non-interactive. |
| **Recipes** | `do work tutorial recipes` | Workflow cheat sheet: common scenarios mapped to exact commands. |
| **Interactive Tour** | `do work tutorial tour` | Menu-driven — pick a topic, get a self-contained explanation with examples. |

## Input

`$ARGUMENTS` determines the mode:

- `quick-start`, `quick start`, `quickstart` → Quick Start
- `concepts`, `mental model`, `how it works` → Concepts
- `recipes`, `workflow`, `workflows`, `cheat sheet` → Recipes
- `tour`, `interactive`, `explore` → Interactive Tour
- Empty or `help` → ask the user which mode they want

## Step 1: Mode Selection (no arguments)

When invoked with no arguments, present the four modes and wait for the user to reply:

```
do-work tutorial — learn how the skill works

  1. Quick Start        Capture a task, run it, review it — hands-on in ~5 min
  2. Concepts           Mental model: URs, REQs, pipeline, trail of intent
  3. Recipes            Common scenarios → exact commands (cheat sheet)
  4. Interactive Tour   Pick a topic, get a self-contained deep dive

Which tutorial? (1-4, or name):
```

Print the menu and stop. Wait for the user's reply. Accept a number (1-4) or mode name. Then proceed to the matching mode below.

---

## Quick Start Mode

A guided walkthrough that creates real files. The user follows along.

### Step QS-1: Explain the Core Loop

Print:

```
THE CORE LOOP

  capture → run → review

  1. You describe what you want (capture)
  2. The skill builds it autonomously (run)
  3. You review what was built (review)

Let's try it with a tiny example task.
```

### Step QS-2: Guided Capture

Ask the user to type a simple request, or offer a default:

```
Type a small request to practice with, or press Enter to use this default:

  "Add a hello-world endpoint that returns { message: 'Hello, world!' }"
```

Then explain what `do work capture request: ...` does:
- Creates a UR folder with the verbatim input
- Creates a REQ file with structured fields (what, why, done-when)
- Links the REQ back to the UR

Do NOT actually run capture — this is explanatory. Show what the resulting file structure would look like:

```
do-work/
  user-requests/
    UR-001/
      input.md          ← your exact words, preserved verbatim
  queue/
    REQ-001.md          ← structured task: what, why, acceptance criteria
```

### Step QS-3: Explain Run

Explain what `do work run` does:
- Picks the next REQ from the queue
- Triages it (simple fix? feature? refactor?)
- Plans the implementation
- Builds it — writes code, runs tests
- Self-reviews before marking complete
- Moves the REQ to the archive

### Step QS-4: Explain Review

Explain what `do work review work` does:
- Checks requirements against the original request
- Reviews the code for quality
- Runs acceptance tests
- Produces a pass/fail verdict

### Step QS-5: Wrap Up

```
That's the core loop! Here are the commands:

  do work capture request: [describe what you want]
  do work run
  do work review work

When you're ready for the real thing:
  do work capture request: [your actual task]
```

---

## Concepts Mode

Non-interactive explainer. Print all sections, then stop.

### Step C-1: The Big Picture

```
WHAT IS DO-WORK?

A task queue for AI coding agents. You describe what you want in plain
language. The skill breaks it into structured tasks, builds them one at
a time, and tracks everything in files you can read and audit.

It works with any agentic coding tool that can read/write files and run
shell commands — no special APIs needed.
```

### Step C-2: URs and REQs

```
URs AND REQs

  UR (User Request)  — Your exact words, preserved verbatim in a folder.
                       One UR can produce multiple REQs.

  REQ (Requirement)  — A structured task with: what, why, acceptance
                       criteria, and a status that moves through the
                       pipeline. Each REQ links back to its parent UR.

  Example: "Fix the search and update the header" (1 UR) →
           REQ-001: Fix search performance
           REQ-002: Fix header alignment
```

### Step C-3: The Pipeline

```
THE PIPELINE

  capture → verify → run → review → present

  capture    Turn plain language into UR + REQ files
  verify     Quality-check: did capture get it right?
  run        Triage → plan → build → test → self-review (per REQ)
  review     Human-facing review: requirements + code + acceptance
  present    Client-facing deliverables (optional)

  "do work pipeline [request]" runs all stages end-to-end.
  Or run each stage individually for more control.
```

### Step C-4: Trail of Intent

```
TRAIL OF INTENT

Every REQ is a living document. As it moves through the pipeline, each
stage appends its decisions:

  Original intent (capture) → triage route → plan → implementation
  notes → test results → review findings → lessons learned

This trail is the skill's primary value — code is the side effect.
You can always trace back from the final code to the original "why."
```

### Step C-5: File Layout

```
FILE LAYOUT

  do-work/
    user-requests/     Original input, verbatim
      UR-001/
        input.md
    queue/             Pending REQs (ready to build)
      REQ-001.md
    active/            Currently being built
    archive/           Completed work
      UR-001/
        REQ-001.md     Full trail: intent → decisions → implementation
```

---

## Recipes Mode

Print the cheat sheet, then stop.

### Step R-1: Print Recipes

```
WORKFLOW RECIPES — common scenarios → exact commands

  "I have a feature request"
    do work capture request: [describe the feature]
    do work run

  "I have a bug report"
    do work capture request: [describe the bug and how to reproduce]
    do work run

  "I got meeting notes / a spec / a screenshot"
    do work capture request: [paste the content]
    do work verify requests
    do work run

  "I want the full hands-off pipeline"
    do work pipeline [describe what you want]

  "I want to check what was captured before building"
    do work verify requests

  "Work is done — now what?"
    do work review work
    do work present work

  "Something seems stuck"
    do work forensics

  "I want to review code quality (not a specific task)"
    do work code-review [scope]

  "I want to understand uncommitted changes"
    do work inspect

  "I want to clean up the archive"
    do work cleanup

  "What happened recently?"
    do work recap
```

---

## Interactive Tour Mode

Menu-driven. Present topics, let the user pick, explain, repeat.

### Step T-1: Show Topic Menu

```
INTERACTIVE TOUR — pick a topic to learn about

  1. Capturing requests     How tasks enter the system
  2. Running the queue      How work gets built
  3. Reviewing work         Post-build quality checks
  4. The pipeline           End-to-end automation
  5. Knowledge base (bkb)   Building a persistent wiki from sources
  6. Prime files            AI context documents for codebases
  7. Code & UI review       Standalone quality audits
  8. File structure         Where everything lives and why

  Pick a number (or "done" to exit):
```

Print the menu and stop. Wait for the user's reply. Accept a number (1-8), topic name, or "done".

### Step T-2: Topic Deep Dives

For each topic, provide a self-contained explanation (8-15 lines) with the relevant commands and a concrete example. After each explanation, show the topic menu again and wait for the user to pick another or say "done".

**Topic 1 — Capturing requests:**
Explain the UR/REQ pairing, how multi-part requests become multiple REQs, the role of the RED case / GREEN proof, and how verbatim input is preserved. Key commands: `capture request:`, `verify requests`.

**Topic 2 — Running the queue:**
Explain triage routes (A/B/C), autonomous build cycle, test-first approach, self-review, and how Open Questions work. Key commands: `run`, `continue`, `clarify`.

**Topic 3 — Reviewing work:**
Explain requirements checking, code review, acceptance testing, pass/fail, and what happens on failure (re-queue). Key commands: `review work`, `review work REQ-NNN`.

**Topic 4 — The pipeline:**
Explain the 5-stage sequence, persistent state tracking, resume behavior, and when to use pipeline vs individual commands. Key commands: `pipeline [request]`, `pipeline status`, `pipeline abandon`.

**Topic 5 — Knowledge base:**
Explain what a BKB is (Markdown wiki compiled from raw sources), the init → triage → ingest cycle, querying, and maintenance. Key commands: `bkb init`, `bkb ingest`, `bkb query [question]`.

**Topic 6 — Prime files:**
Explain what prime files are (AI context documents), when to create them, what they index, and how other actions use them for scoping. Key commands: `prime create [path]`, `prime audit`.

**Topic 7 — Code & UI review:**
Explain standalone reviews (not tied to a REQ), scoping via prime files or directories, what gets checked (security, patterns, performance, accessibility). Key commands: `code-review [scope]`, `ui-review [scope]`.

**Topic 8 — File structure:**
Walk through the `do-work/` directory: `user-requests/`, `queue/`, `active/`, `archive/`, and how files move between them. Explain frontmatter fields and status transitions. Also cover the knowledge base layout (`kb/` or `knowledge-base/`): `raw/` (inbox → capture pipeline), `wiki/` (master index, topics, concepts, entities, sources, daily logs), and `agents/` (crew role definitions).

### Step T-3: Exit

When the user says "done" or has visited all topics:

```
Tour complete! When you're ready to start:
  do work capture request: [describe what you want]
  do work help                 Full command reference
```

---

## Output Format

Each mode is self-contained — print its content and stop. Do not chain into another action after the tutorial.

## Rules

- **Read-only.** Tutorials explain — they never create URs, REQs, or modify the queue.
- **No fake files.** Show example file structures as text illustrations, not actual file creation.
- **Plain text menus.** Print the menu, then stop and wait for the user to reply. Do not use the ask-user tool for mode selection or topic selection — the menus have too many options for structured prompts. Just print and wait.
- **Stop after the tutorial.** Do not offer to start capture or run after finishing. Suggest next steps per the standard next-steps format.
