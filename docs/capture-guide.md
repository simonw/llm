# Capture Requests

Fast-capture for turning ideas into structured, trackable request files. Designed for speed — minimal interaction when intent is clear.

## How it works

Every invocation produces exactly two things:

1. A **UR folder** (`do-work/user-requests/UR-NNN/`) preserving your verbatim input
2. One or more **REQ files** (`do-work/REQ-NNN-slug.md`) that enter the queue

Compound inputs are split into separate REQ files automatically. The skill asks clarifying questions during capture (while you're present) but never starts building — capture and execution are strictly separate.

## Folder structure

```
do-work/
├── user-requests/
│   └── UR-001/
│       ├── input.md          # Full, unedited user input (source of truth)
│       └── assets/           # Screenshots, attachments
├── REQ-001-dark-mode.md      # Pending queue item
├── REQ-002-export-button.md  # Another queue item
├── working/                  # (created later by work action)
└── archive/                  # (created later by work action)
```

## REQ file format

```yaml
---
id: REQ-001
title: Brief descriptive title
status: pending
created_at: 2025-01-26T10:00:00Z
user_request: UR-001
domain: frontend | backend | ui-design | general
prime_files: []
tdd: false
---
```

Key sections inside a REQ:

- **What** — 1-3 sentences describing the request
- **AI Execution State (P-A-U Loop)** — Plan, Apply, Unify checkboxes
- **Red-Green Proof** — for testable work: what fails now (RED) and what passes when done (GREEN)
- **Open Questions** — ambiguities with concrete options
- **Context / Constraints** — additional details

Complex requests add: Detailed Requirements, Dependencies, Builder Guidance, Batch Context.

## Workflow

1. **Parse** — single vs. multiple requests, simple vs. complex, domain classification, TDD assessment
2. **Deduplicate** — checks existing queue, in-flight, and archived REQs for overlaps
3. **Clarify** — asks questions while you're present (concrete options, never open-ended)
4. **Write files** — creates UR folder + REQ files, handles screenshots
5. **Report** — brief summary of what was created
6. **Commit** — stages only the new files (never `git add -A`)

## Addenda

Need to modify an in-flight or completed request? Capture creates a new REQ with `addendum_to: REQ-NNN` pointing to the original. It never modifies files in `working/` or `archive/`.

## Usage

```
do work capture request: add dark mode to settings
do work capture request: the search is slow, add export, fix the header
do work capture request: [paste meeting notes, specs, or a screenshot]
```
