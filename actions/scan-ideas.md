# Ideate Action

> **Part of the do-work skill.** Generates ideas for what to build, improve, or explore next. Turns codebase analysis and project context into actionable suggestions the user can capture as requests.

**Read-only** — this action does NOT modify any files. It produces a structured report of ideas.

## Philosophy

- **Grounded, not generic.** Every idea must reference something concrete in the codebase or project history — a file, a pattern, a gap, a completed REQ. No "you should add tests" without pointing at what's untested and why it matters.
- **Product thinking, not just code.** Go beyond refactoring. Think about what users would want, what's missing from the experience, what would make the project more valuable.
- **Effort-aware.** Tag every idea with a rough size so the user can pick what fits their time budget.
- **Feed the pipeline.** Ideas should be concrete enough to paste straight into `do work capture request:`.

## Input

`$ARGUMENTS` determines the focus:

- Empty → open exploration (scan everything available)
- A topic or theme (e.g., "performance", "onboarding", "mobile") → focused brainstorm
- A directory path (e.g., "src/api/") → ideas scoped to that area
- `around [topic]` → brainstorm variations and extensions around a theme

## Steps

### Step 1: Gather Context

Build a picture of the project before generating ideas:

1. **Prime files**: Glob for `**/prime-*.md` — these describe the architecture, entry points, and conventions. Read them.
2. **Recent work**: Check `do-work/archive/` for completed URs/REQs (most recent 5-10). Read their titles and summaries to understand what's been built and what direction the project is moving.
3. **Queue**: Check `do-work/queue/` for pending REQs — avoid suggesting ideas that are already captured.
4. **Codebase survey**: Detect languages, frameworks, project structure. Identify the primary areas of the codebase.
5. **Signals**: Scan for indicators of opportunities:
   - `TODO`, `FIXME`, `HACK`, `XXX` comments
   - Empty or stub implementations
   - `README.md` or docs that mention planned/future features
   - Test coverage gaps (directories with source but no test files)
   - Configuration files that hint at unused capabilities (e.g., installed but unused dependencies)

If `$ARGUMENTS` specifies a focus topic or directory, narrow the scan accordingly.

### Step 2: Generate Ideas

Produce ideas across these categories. Not every category needs entries — only include categories where you found genuine opportunities.

| Category | What to look for |
|----------|-----------------|
| **Features** | New capabilities users would want. Look at what exists and ask "what's the natural next step?" |
| **Improvements** | Enhancements to existing features — better UX, more options, edge case handling |
| **Performance** | Bottlenecks, unnecessary work, caching opportunities, lazy loading candidates |
| **Developer Experience** | Missing scripts, poor error messages, confusing APIs, setup friction |
| **Reliability** | Error handling gaps, missing validation, unhandled edge cases, monitoring blind spots |
| **Integrations** | External services, APIs, or tools the project could connect to based on its domain |
| **Documentation** | Missing guides, outdated docs, undocumented features or APIs |

For each idea, record:
- **Title** — a concise name (suitable for `capture request:`)
- **Category** — from the table above
- **Why** — 1-2 sentences grounding the idea in something concrete (a file, pattern, gap, or user need)
- **Size** — `S` (< 1 hour), `M` (1-4 hours), `L` (4+ hours)
- **Confidence** — `high` (clearly needed), `medium` (good idea, depends on priorities), `low` (speculative but interesting)

### Step 3: Rank and Present

Sort ideas by a combination of confidence and impact. Present the top ideas first.

## Output Format

```
IDEATION REPORT — [focus or "open exploration"]

  Context: [1-2 sentences about the project and what informed the ideas]

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ## Features

  1. [Title]                                                    [S/M/L] [confidence]
     [Why — grounded in something concrete]

  2. [Title]                                                    [S/M/L] [confidence]
     [Why]

  ## Improvements

  3. [Title]                                                    [S/M/L] [confidence]
     [Why]

  ...

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Summary: [N] ideas ([X] high confidence, [Y] medium, [Z] low)

  To capture any idea:
    do work capture request: [paste or rephrase the title + why]
```

Aim for 8-15 ideas total. Fewer is fine if the codebase is small or focused. More than 15 dilutes signal — prioritize harder instead.

## Rules

- **No duplicates.** Check the queue and recent archive before suggesting. If an idea overlaps with pending or recent work, skip it.
- **No generic advice.** "Add more tests" is not an idea. "Add unit tests for the date parsing functions in `src/utils/dates.ts` which handle 6 format variants with zero coverage" is.
- **Grounded in evidence.** Every idea must point at something real — a file, a pattern, a TODO, a gap, a user-facing behavior. If you can't point at evidence, drop the idea.
- **Respect the focus.** If `$ARGUMENTS` specifies a topic or directory, stay in scope. Don't pad the list with off-topic suggestions.
- **Read-only.** Do not create files, modify code, or capture requests. The user decides what to act on.
