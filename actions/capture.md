# Capture Requests Action

> **Part of the do-work skill.** Invoked when routing determines the user is adding a request. Creates a `do-work/` folder in your project for request tracking.

A fast-capture system for turning ideas into structured request files. Speed over perfection — minimal interaction when intent is clear.

## Core Rules

Every invocation produces exactly two things, always paired:

1. **A UR folder** at `do-work/user-requests/UR-NNN/` with `input.md` containing the full verbatim input
2. **One or more REQ files** at `do-work/REQ-NNN-slug.md`, each linked via `user_request: UR-NNN` in frontmatter

Never create one without the other. A REQ without `user_request` is orphaned. A UR without REQs is pointless. The verify requests action depends on this linkage.

**Principles:**
- Represent, don't expand — if the user says 5 words, write a 5-word request (with structure)
- The building agent solves technical questions — you're capturing intent, not making architectural decisions
- **Validated artifacts** — captured REQs are not drafts. They are user-validated statements of intent. During capture, ambiguities are resolved with the user, RED/GREEN proofs are confirmed, and the resulting REQ reflects what the user actually wants. Downstream agents treat REQs as the authoritative expression of user intent.
- Never be lossy — for complex inputs, preserve ALL detail in the UR's verbatim section
- After capture, **STOP** — do not start processing the queue or transition into the work action unless the user explicitly asked for both (e.g., "add this and start working")

### First-Run Bootstrap

If `do-work/` doesn't exist yet (first invocation in a project):

1. Create `do-work/` and `do-work/user-requests/`
2. Do **not** pre-create `working/` or `archive/` — those are created by the work action on demand
3. Start numbering at REQ-001 and UR-001

## Simple vs Complex

| Mode | When | Approach |
|------|------|----------|
| **Simple** | Short input (<200 words), 1-2 features, no detailed constraints | Lean format, minimal UR |
| **Complex** | 3+ features, detailed requirements/constraints/edge cases, dependencies between features, or user says "spec"/"PRD"/"requirements" | Full preservation with detailed REQ sections |

**When uncertain, treat as complex.** Over-preserving is better than losing requirements.

## File Locations

- `do-work/` root — ONLY for pending `REQ-*.md` files (the queue)
- `do-work/user-requests/UR-NNN/` — verbatim input (`input.md`) and assets (`assets/`)
- **NEVER write to** `do-work/working/` or `do-work/archive/` — those belong to the work action

### Immutability Rule

Files in `working/` and `archive/` are **immutable**. If someone wants to add to an in-flight or completed request, create a new addendum REQ that references the original via `addendum_to` in frontmatter. **The new addendum REQ always goes to `do-work/` root** — never into `working/` or `archive/` — so the work loop picks it up on the next run. A new UR is also created (verbatim input of the addendum) paired with the new REQ.

**Exception:** The review work action may append a `## Review` section to archived files — review annotations are post-work metadata, not content changes. See `review-work.md`.

## File Naming

- **REQ files:** `REQ-[number]-[slug].md` in `do-work/` root
- **UR folders:** `do-work/user-requests/UR-[number]/` containing `input.md` and optional `assets/`
- **Assets:** `do-work/user-requests/UR-NNN/assets/REQ-[num]-[descriptive-name].png`

To get the next REQ number, check existing `REQ-*.md` files across `do-work/`, `do-work/working/`, and `do-work/archive/` (including inside `do-work/archive/UR-*/`), then increment from the highest. For the next UR number, check `do-work/user-requests/UR-*/` and `do-work/archive/UR-*/`. REQ and UR use separate numbering sequences. If no existing files are found anywhere, start at 1.

### Backward Compatibility

Legacy REQ files (pre-UR system) may lack `user_request` and reference `CONTEXT-*.md` files or `do-work/assets/` instead. This is fine — the work action handles both patterns. New REQs always get `user_request`.

## Request File Formats

### Simple REQ

```markdown
---
id: REQ-001
title: Brief descriptive title
status: pending
created_at: 2025-01-26T10:00:00Z
user_request: UR-001
domain: frontend  # choose one: frontend, backend, ui-design, or general
prime_files: []  # list paths to relevant prime-*.md files, or leave empty
tdd: false  # set true when test-first approach applies (see heuristic below)
---

# [Brief Title]

## What
[1-3 sentences describing what is being requested]

## AI Execution State (P-A-U Loop)
- [ ] **[PLAN]:** (Agent: Read listed `prime_files` and agent rules. Write brief technical approach here. Do not write code yet.)
- [ ] **[APPLY]:** (Agent: Code written exactly as planned. Scope strictly limited to planned files.)
- [ ] **[UNIFY]:** (Agent: Run `git diff --stat` and review every changed file. Run native project linters. Verify no debug artifacts in diff. List each file you verified and what you checked.)

## Why (if provided)
[User's stated reasoning — omit if not provided]

## Context
[Additional context, constraints, or details mentioned]

## Red-Green Proof
**RED prompt/case:** [Minimal prompt, repro, or example that should fail or be missing today]
**Why RED now:** [What is currently broken or absent]
**GREEN when:** [Observable result that proves the request is done]
**Validation:** [User confirmed / User adjusted / Inferred during capture]

## Assets
[Description of screenshots or links to saved files]

---
*Source: [original verbatim request]*

Think carefully before answering.
```

Include `## Red-Green Proof` when the request is behavior-changing and can be proven with a prompt, repro, or example. If `tdd: true`, this section is mandatory. The goal is proof of behavior, not implementation detail.

Treat defining the RED state as essential, high-value capture work. It is one of the most helpful things you can do for the downstream builder because it turns vague intent into a concrete failing proof target. Do not treat this as paperwork. Lean into it. Be eager to find the best RED case: the smallest, clearest prompt/repro/example that proves the behavior is missing now and will clearly turn GREEN later.

### Complex REQ (additional sections)

Complex requests use the same base format plus these sections:

```markdown
## Detailed Requirements
[Extract EVERY requirement from the original input that applies to THIS feature.
DO NOT SUMMARIZE — use the user's words. Include specific values, constraints,
conditions, edge cases, "must"/"should"/"never" statements.]

## Constraints
[Limitations, restrictions, batch-level concerns that apply to this REQ]

## Dependencies
[What this feature needs or what needs it — reference other REQ IDs]

## Builder Guidance
[Certainty level: Exploratory / Firm / Mixed. Scope cues like "keep it simple."
Any latitude given to the builder.]

## Open Questions
- [ ] [Question about ambiguity the user needs to clarify]
  Recommended: [best default based on context]
  Also: [alternative A], [alternative B]

Open Questions use checkbox syntax with recommended choices. Each question includes a `Recommended:` line (the best default if the user doesn't answer) and an `Also:` line with alternatives. The choices make questions answerable even when the question itself isn't fully understood — the user can just pick one.

`- [ ]` = unresolved, `- [x]` = answered (answer follows `→`), `- [~]` = deferred to builder (note follows `→`).

**Capture time is the optimal window for resolving these.** During capture (this action), use the ask tool if your environment provides one; otherwise use your environment's normal ask-user prompt/tool. Present Open Questions immediately. The user is here, engaged, and fleshing out the request — don't defer what you can clarify now. Only leave questions as `- [ ]` if you genuinely can't ask (e.g., batch processing, async capture).

Only add questions where the user's intent is genuinely unclear — don't add questions the builder can answer by reading the codebase.

## Full Context
See [user-requests/UR-NNN/input.md](./user-requests/UR-NNN/input.md) for complete verbatim input.
```

**Additional frontmatter for complex requests:**
- `related: [REQ-006, REQ-007]` — other REQs in this batch
- `batch: auth-system` — batch name grouping related requests
- `addendum_to: REQ-005` — if this amends an in-flight/completed request

### UR input.md

Created for every invocation. For simple requests, it's minimal:

```markdown
---
id: UR-005
title: Add keyboard shortcuts
created_at: 2025-01-26T10:00:00Z
requests: [REQ-020]
word_count: 4
---

# Add keyboard shortcuts

## Full Verbatim Input

add keyboard shortcuts

---
*Captured: 2025-01-26T10:00:00Z*
```

For complex requests, add a Summary, an Extracted Requests table, and a Batch Constraints section before the Full Verbatim Input. The verbatim section must contain the COMPLETE, UNEDITED input — never summarize or clean it up.

## Workflow

### Step 1: Parse and Assess

Read the user's input. Determine:
- **Single vs multiple requests** — look for "and also", comma-separated lists, numbered items, distinct topics
- **Simple vs complex** — apply the detection criteria above
- **Domain classification** — infer the primary technical domain of the request (e.g., frontend, backend, ui-design, or general) so the downstream builder knows which JIT rules to load.
- **TDD assessment** — determine if a test-first approach applies. Heuristic: "Can you write `expect(fn(input)).toBe(output)` before writing `fn`?" If yes (pure logic, data transformations, API handlers, utility functions) → set `tdd: true`. If no (UI layout, config changes, copy/content, glue code, refactoring) → omit or set `tdd: false`. When in doubt, leave false — the builder can still write tests without formal TDD mode.
- **Red-green proof inference** — for `tdd: true` requests and any clearly behavioral bug fix or feature, infer the smallest RED prompt/case and GREEN outcome in user-visible terms. Capture how we know the behavior is missing or failing now, and what observable result turns it GREEN later. This is not test code — it is the proof target. Treat this as essential: a strong RED state makes planning, implementation, and review dramatically easier.
- **Prime file routing** — check the project's root `CLAUDE.md` (or similar instructions) to see if there are defined prime files that match the requested utility. Note them for inclusion.

### Step 2: Check for Duplicates

**Queued requests** — read each `REQ-*.md` in `do-work/` and compare the new request's intent against the existing file's `title`, heading, and `## What` section. Slugs are lossy — a file named `REQ-042-ui-cleanup.md` may contain the exact requirement being re-submitted under different phrasing. Match on intent, not just keywords.

**In-flight and archived requests** — list filenames in `do-work/working/` and `do-work/archive/` (including inside `do-work/archive/UR-*/`). A filename scan is sufficient here since these files are immutable regardless.

If `do-work/` is freshly bootstrapped (no existing REQ files anywhere), skip duplicate checking entirely.

For each parsed request, check for similar existing ones across both tiers.

| Existing request is in... | Action | New REQ lands in |
|---------------------------|--------|-----------------|
| `do-work/` (queue) | If same: tell user, skip. If similar: ask. If enhancement: append an Addendum section to the pending file | N/A — amends the existing pending file |
| `do-work/working/` | **NEVER modify.** Create a new addendum REQ with `addendum_to` field | `do-work/` root — work loop picks it up |
| `do-work/archive/` | **NEVER modify.** Create a new addendum REQ with `addendum_to` field | `do-work/` root — work loop picks it up |

**Addendum to a queued request** — don't rewrite, append:

```markdown
## Addendum (2025-01-27)

User added: "dark mode should also affect the sidebar"

- Sidebar must also respect dark mode theme
```

**Coherence Rule (queued addenda):** After appending an Addendum section to a pending REQ, re-read the full REQ — the original What, Requirements, Constraints, and Red-Green Proof sections plus the new addendum. If the addendum **contradicts** any existing content (e.g., "add dark mode" + "remove all theming"), do not silently write the contradiction. Instead:

1. Present the conflict to the user with concrete options: "The original REQ says X. The new input says Y. These conflict. Which should win?" Use the ask tool if available.
2. If the user resolves it: update the REQ to reflect the resolved intent. Record what changed in the Addendum section: `Resolved conflict: [original] → [user's decision]`.
3. If the user cannot resolve now: append the addendum as-is but add a `- [ ]` Open Question flagging the contradiction with both options as choices.

The goal is that every REQ, at every point in time, expresses a single coherent intent.

**Addendum for in-flight/completed requests** — create a new UR + REQ, both in `do-work/`:

- Create `do-work/user-requests/UR-NNN/input.md` with the addendum input verbatim (new UR, fresh number)
- Create `do-work/REQ-NNN-slug.md` linking to that new UR, with `addendum_to` pointing at the original

The `addendum_to` field is what connects the addendum to its origin. The new REQ then enters the queue normally and gets picked up by the next `do work run`.

```markdown
---
id: REQ-021
title: "Addendum: dark mode sidebar support"
status: pending
created_at: 2025-01-27T09:00:00Z
user_request: UR-006        ← new UR created for this addendum
addendum_to: REQ-005        ← links back to the original request
---

# Addendum: Dark Mode Sidebar Support

## What
Add sidebar support to the existing dark mode implementation (REQ-005).

## Context
Addendum to REQ-005, which is currently [in progress / completed].
The user wants the sidebar to also support dark mode.

## Prior Implementation
[For archived/completed originals: read the original REQ from the archive and
summarize what was built, key files modified, patterns used, and commit hash
(if available). Skip this section for in-flight originals — the builder will
encounter the work in progress naturally.]

## Requirements
- Sidebar must respect the dark mode theme
```

**Context is critical for addenda to archived/completed REQs.** When writing the addendum REQ, read the original archived REQ and include a `## Prior Implementation` section summarizing: what was built, key files modified, patterns used, and commit hash (if available). Without this, the builder wastes time re-discovering what already exists. For in-flight REQs this matters less — the builder will encounter the work in progress naturally.

**When the original UR is archived:** The original UR folder is in `archive/UR-NNN/` and is immutable. The new addendum UR goes into `do-work/user-requests/` as normal. Do not attempt to modify or re-open the archived UR folder.

**Coherence across addendum chains:** When creating an addendum REQ for an in-flight or completed request, read the original REQ's What, Requirements, and any prior addendum chain (follow `addendum_to` links). If the new addendum contradicts the original or a prior addendum, present the conflict to the user with concrete options (same protocol as the queued addenda Coherence Rule above): show what conflicts, ask which should win, and record the resolution or flag as an Open Question. The addendum REQ must state clearly how it relates to the original: extending, narrowing, replacing, or correcting.

### Step 3: Capture-Phase Clarification

**Capture is the optimal window for human interaction.** The user is present, actively thinking about the request, and expects back-and-forth. Use the ask tool if your environment provides one; otherwise use your environment's normal ask-user prompt/tool. Resolve ambiguities here — this is far cheaper than blocking the build phase later.

**When to ask:** Only when the request is genuinely ambiguous (could mean two very different things), or when a duplicate/similar request makes intent unclear. Don't ask about implementation details — that's for the building agent.

**How to ask:** Use the ask tool if available, otherwise use your environment's normal ask-user prompt/tool, and always present concrete options. Every question must present choices the user can pick from — not open-ended "what do you mean?" prompts. The choices themselves clarify the question: even if the user doesn't fully understand the question, selecting the closest option moves things forward.

```
Good: "Should dark mode apply to the sidebar?" — options: (yes, full app / no, main content only / builder decides)
Bad:  "Can you clarify the scope of dark mode?"
```

**What NOT to ask about:** Implementation details, architecture, file locations, naming conventions — these belong to the builder agent during the work phase.

**Special case — RED/GREEN proof:** For `tdd: true` requests and other behavior-changing work that can be proven with a prompt/repro/example, infer the likely RED case before writing the REQ and validate it with the user during capture. Use the ask tool if available for this validation so the user can confirm or correct the proof target in a structured way.

This is essential, not optional polish. A well-chosen RED state is often the single most useful artifact capture can produce. It gives the builder a crisp target, keeps scope honest, and makes GREEN objectively verifiable. Be glad to do this work. Take a moment to find the best RED case you can.

The goal is agreement on:

1. What concrete prompt, repro, or example should fail or be missing today?
2. What concrete outcome makes it GREEN when the work is done?

Ask about observable proof, not how the test should be implemented.

Prefer the best RED case, not the first one:
- Minimal — the smallest prompt/repro/example that isolates the missing behavior
- Concrete — specific enough that two different builders would test the same thing
- User-visible — described in behavior/outcome terms, not internal implementation terms
- Binary — it is obvious why it is RED now and obvious what turns it GREEN
- Traceable — easy to reference later in testing and review

```text
Good: "Should RED be 'searching for invoice returns no results even though invoice-123 exists', and GREEN be 'invoice-123 appears in results'?" — options: yes / use a different failure case / not a test-first request
Bad:  "What test should we write for search?"
```

If the user adjusts your inferred RED/GREEN pair, record the user's version. If you genuinely cannot ask right now, still capture your best inferred pair and mark `Validation: Inferred during capture`.

**After capture:** Any remaining ambiguities that weren't resolved interactively go into the REQ's `## Open Questions` section with inline choices. These are exceptional — most REQs should have zero open questions after capture.

**Capture produces validated intent.** By the end of this step, every ambiguity that could be resolved has been resolved with the user present. The REQ that gets written in Step 5 is not a guess — it is a validated expression of intent. Record this validation status in the Red-Green Proof section (`Validation: User confirmed` / `User adjusted` / `Inferred during capture`) so downstream agents know how firmly the intent was established.

### Step 4: Handle Screenshots

If the user provides a screenshot:
1. Find the image using your platform's attachment mechanism or cache
2. Copy to `do-work/user-requests/UR-NNN/assets/REQ-[num]-[slug].png`
3. Reference in the REQ's Assets section
4. Write a thorough text description (what it shows, visible text, layout, problems visible) — this is the primary record for searchability

### Step 5: Write Files

Before writing, ensure `do-work/` and `do-work/user-requests/UR-NNN/` exist (create if needed).

**For all requests (simple and complex):**
1. Create `do-work/user-requests/UR-NNN/input.md` with verbatim input (leave `requests` array empty initially)
2. Create REQ-NNN-slug.md files using the appropriate format, adding user_request: UR-NNN, the inferred domain, and the prime_files array populated with any discovered paths.
3. If the request is behavior-changing and has a meaningful RED/GREEN proof target, add a `## Red-Green Proof` section. If `tdd: true`, this section is required.
4. Update the UR's `requests` array with all created REQ IDs

**Complex mode additionally:**
- Create `assets/` subfolder in the UR folder
- Extract EVERY requirement into the appropriate REQ — do not summarize
- Set `related` and `batch` fields across the batch
- Add Batch Constraints to the UR (cross-cutting concerns, scope cues, sequencing)
- Duplicate batch-level constraints into each relevant REQ's Constraints section
- Re-read the original input to verify nothing was dropped — especially UX/interaction details and intent signals (certainty level, scope cues)

### Step 6: Report Back

Brief summary of created files. If the request was meaningfully complex (complex mode, 3+ REQs, or notably long/nuanced input), add:

> That was a pretty detailed request — it's possible the capture missed some nuances. You can run `do work verify requests` to check coverage against your original input.

Always end with next step suggestions:

```
Next steps:
  do work verify requests     Check capture quality before building
  do work run                 Start processing the queue
```

Only suggest prompts that provide value given the current state. Use full action names.

### Step 7: Commit (Git repos only)

Check for git with `git rev-parse --git-dir 2>/dev/null`. If not a git repo, skip this step.

Stage only the files created during this capture — the UR folder and all new REQ files:

```bash
# Stage the UR input and any assets
git add do-work/user-requests/UR-NNN/input.md
git add do-work/user-requests/UR-NNN/assets/  # only if assets were created

# Stage each created REQ file
git add do-work/REQ-NNN-slug.md

git commit -m "$(cat <<'EOF'
[UR-NNN] captured {title} ({N} REQs)

- REQ-NNN: {title}
- REQ-NNN: {title}

EOF
)"
```

**Format:** `[UR-NNN] captured {title} ({N} REQs)` — where `{title}` is the UR title and `{N}` is the count of REQ files created. List each REQ with its ID and title in the body.

**For addenda** (when appending to an existing pending REQ instead of creating new files), the commit message changes to: `[UR-NNN] addendum to REQ-NNN: {description}`. Stage the modified REQ file and the new UR folder.

Do not use `git add -A` or `git add .` — stage only the specific files created by this capture. Don't bypass pre-commit hooks — fix issues and retry.

## Examples

### Simple Capture

```
User: do work add keyboard shortcuts

Created:
- do-work/user-requests/UR-003/input.md
- do-work/REQ-004-keyboard-shortcuts.md
```

### Multiple Requests

```
User: do work add dark mode, also the search feels slow, and we need an export button

Created:
- do-work/user-requests/UR-004/input.md
- do-work/REQ-005-dark-mode.md
- do-work/REQ-006-search-performance.md
- do-work/REQ-007-export-button.md
```

### Addendum to In-Flight Request

```
User: do work dark mode should also affect the sidebar

[Checks existing — REQ-005-dark-mode.md is in do-work/working/]

REQ-005 is currently being worked on — creating a follow-up request instead.

Created:
- do-work/user-requests/UR-006/input.md
- do-work/REQ-021-addendum-dark-mode-sidebar.md (addendum_to: REQ-005)
```

### Addendum to Archived Request

```
User: do work dark mode should also apply to modals

[Checks existing — REQ-005-dark-mode.md is in do-work/archive/UR-003/]

REQ-005 is already completed and archived — creating a new follow-up request.

[Reads archived REQ-005 to extract: key files, patterns, commit hash (if available)]

Created:
- do-work/user-requests/UR-009/input.md         ← new UR (archived UR-003 is not touched)
- do-work/REQ-027-addendum-dark-mode-modals.md  ← new REQ in do-work/ root
  (user_request: UR-009, addendum_to: REQ-005, includes Prior Implementation summary)
```

The new REQ-027 sits in `do-work/` root with `status: pending` and will be picked up by the next `do work run`. The archived `UR-003/` folder is not modified.

### Complex Multi-Feature Request

```
User: do work [detailed auth system requirements — OAuth, profiles, sessions, password reset...]

Created:
- do-work/user-requests/UR-001/input.md (full verbatim input, 1847 words)
- do-work/REQ-010-oauth-login.md (user_request: UR-001)
- do-work/REQ-011-user-profiles.md (user_request: UR-001)
- do-work/REQ-012-session-management.md (user_request: UR-001)
- do-work/REQ-013-password-reset.md (user_request: UR-001)

That was a pretty detailed request — it's possible the capture missed some
nuances. You can run `do work verify requests` to check coverage against your original input.
```

## Edge Cases

- **Vague request ("fix the search")**: Capture what was said. The builder can clarify.
- **Behavioral request but proof is fuzzy**: Propose the smallest failing prompt/repro you can infer, ask the user to confirm or adjust it, and record the agreed RED/GREEN pair.
- **References earlier conversation**: Include that context in the request file.
- **Seems impossible or contradictory**: Capture it. Add contradictions as `- [ ]` Open Questions with recommended resolutions — and ask the user right now if they're available.
- **Requirement applies to multiple features**: Include in ALL relevant REQ files. Duplication beats losing it.
- **User changes mind mid-request**: Capture the final decision, note the evolution in the UR.
- **Mentioned once in passing**: Still a requirement. Capture it.
