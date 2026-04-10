# Inspect Action

> **Part of the do-work skill.** Invoked when routing determines the user wants to understand uncommitted changes. Read-only — examines the working tree, explains what changed, traces changes to REQs, and assesses commit readiness. When scoped to a REQ or UR, also inspects committed files from the Implementation Summary for a complete picture.

Unlike the commit action (which stages and commits), this action only reads and reports. Use it to understand what's in your working tree before deciding whether to commit, fix, or discard.

## When This Runs

- **Manually** when the user invokes it (e.g., `do work inspect`, `do work explain changes`)

## Core Rules

- **Read-only.** This action never modifies files, creates commits, stages changes, or writes to the do-work queue. It only reads and reports.
- **Safe to run anytime.** No side effects. Can be run mid-work, between sessions, or before deciding whether to commit.
- **Explain, don't act.** The report tells the user what changed, why, and whether it's ready. The user decides what to do next.

## Input

`$ARGUMENTS` determines the scope of the inspection. Three modes:

### Mode 1: All Changes (default)

`do work inspect` — no arguments. Inspects ALL uncommitted changes in the working tree.

### Mode 2: REQ Scope

`do work inspect REQ-005` — inspects ALL files from REQ-005's Implementation Summary, both uncommitted and already committed. Uncommitted files are assessed for commit readiness; committed files are shown for informational completeness. Unassociated uncommitted files are listed as paths at the bottom of the report without full analysis.

### Mode 3: UR Scope

`do work inspect UR-003` — inspects files associated with ANY REQ under UR-003 (both uncommitted and committed). Equivalent to Mode 2 across all REQs in the UR, with a unified report.

## Workflow

```
inspect action
  │
  ├── Preflight ── not a git repo? → exit
  │                 clean tree + no REQ/UR scope? → "No uncommitted changes" → exit
  │
  ├── Read Changes ── diffs for modified, contents for new, paths for deleted
  │                    REQ/UR scope? → also read committed files from Implementation Summary
  │
  ├── Associate with REQs ── match files to REQ Implementation Summaries
  │                           REQ/UR scope? → pre-associate, skip matching
  │
  ├── Group Unassociated ── semantic clustering (1-5 files per group)
  │
  ├── Assess Readiness ── uncommitted: completeness, tests, traceability, coherence, safety, hints
  │                        committed: informational only (labelled "Committed")
  │
  └── Report ── structured output with per-file and overall verdicts
```

### Step 1: Preflight

Check for git with `git rev-parse --git-dir 2>/dev/null`. If not a git repo, report and exit.

Run `git status --porcelain` to get all uncommitted changes — staged, unstaged, and untracked.

If the working tree is clean:
- **No REQ/UR scope:** Report "No uncommitted changes" and exit.
- **REQ/UR scope:** Continue to Step 2 — committed files from the Implementation Summary will still be inspected.

Categorize each file by its status:
- **Modified** (M) — existing files with changes
- **Added** (??, A) — new or untracked files
- **Deleted** (D) — removed files

**Exclude dangerous files** from full analysis (still report them):
- `.env`, `.env.*` — environment variables
- `credentials.*`, `*credentials*` — credential files
- `*.pem`, `*.key`, `*.p12`, `*.pfx` — certificates and keys
- `*.secret`, `*secret*` — secret files

Collect excluded files for the report. Do not silently skip them.

### Step 2: Read Changes

Build a semantic understanding of each uncommitted file:

- **Modified files**: Read the `git diff` for each file. Understand what changed and why.
- **New/untracked files**: Read the file contents. Skip binary files (detect by extension: images, compiled assets, archives). For large files (>500 lines), read the first 100 lines and last 50 lines to understand purpose.
- **Deleted files**: Note the path and what the file likely was (infer from path and name).

#### Committed files (REQ/UR scope only)

When `$ARGUMENTS` specifies a REQ or UR, also collect committed files from the target REQ's Implementation Summary that are **not** in the uncommitted file list:

1. Read the target REQ file(s) and extract the file list from `## Implementation Summary`.
2. For each file in the list that has no uncommitted changes:
   - **Deleted files** (marked `(deleted)` in the Implementation Summary): Note the path and that it was deleted by this REQ. Do not attempt `git show` — there is no content to read. Mark as **committed (deleted)**.
   - **All other files**: Read content via `git show <commit>:<path>`:
     - Use the `commit:` field from the REQ's frontmatter if present.
     - Otherwise, fall back to `HEAD`.
3. Skip binary files (same extension check as above). For large files (>500 lines), read the first 100 and last 50 lines.
4. Mark these files as **committed** — they will be reported separately from uncommitted files.

The goal is to understand each file well enough to explain it and assess its readiness.

### Step 3: Associate with REQs

Skip this step entirely if no `do-work/` directory exists. The action still works — it just skips REQ tracing.

#### Scoped mode (REQ/UR specified in `$ARGUMENTS`)

When a specific REQ or UR is targeted, all files from the target REQ's Implementation Summary are **pre-associated** — skip the scanning/matching logic below and go directly to Step 5 (assessment). Both uncommitted and committed files collected in Step 2 are already associated with the target REQ.

Uncommitted files that are **not** in the target REQ's Implementation Summary remain unassociated and move to Step 4 (listed as paths at the bottom of the report without full analysis, per the scoping filter).

#### Unscoped mode (default)

Scan for REQs that might own some of the uncommitted files:

1. Glob for `do-work/archive/**/REQ-*.md` — find all archived REQs
2. For each archived REQ:
   - Read the frontmatter — check for `status: completed` or `status: completed-with-issues`
   - Read the `## Implementation Summary` section — extract the list of files created/modified
3. Also check `do-work/working/` for in-flight REQs with file lists

Match uncommitted files against these file lists by path. A file is associated with a REQ if it appears in that REQ's Implementation Summary.

**Conflict resolution:** If a file matches multiple REQs, associate it with the most recently completed one (latest `completed_at` timestamp).

**Partial matches count.** If 3 out of 5 files in a REQ's Implementation Summary are among the uncommitted files, group all 3 under that REQ.

Files that don't match any REQ remain unassociated and move to Step 4.

### Step 4: Group Unassociated Files

Cluster the remaining files into semantic groups of 1-5 files each:

1. **Use the diffs/contents** from Step 2 for each unassociated file
2. **Identify logical changes** — files that work together toward a single purpose:
   - A component and its test file
   - Multiple files in the same module touching the same feature
   - Config file changes that go together
   - Documentation updates related to the same topic
3. **Use directory proximity as a secondary signal** — files in the same directory are more likely related, but don't group unrelated changes just because they're neighbors
4. **Assign a short descriptive label** to each group (e.g., "API client error handling", "Config updates")

**When uncertain, prefer smaller groups.** Two groups of 2 files is better than one group of 4 loosely-related files.

**Single-file groups are fine.** A standalone change gets its own group.

### Step 5: Assess Readiness

For each file (or group), evaluate readiness against six signals:

#### Completeness

Scan added/modified lines for work-in-progress indicators:
- `TODO`, `FIXME`, `HACK`, `XXX`, `TEMP`, `TEMPORARY` comments
- Commented-out code blocks (3+ consecutive commented lines in added lines)
- Empty function/method bodies (`{}`, `pass`, `...`, or just a comment)
- Debug statements: `console.log`, `console.debug`, `print(`, `debugger`, `binding.pry`, `import pdb`
- Placeholder values: `"placeholder"`, `"TODO"`, `"CHANGEME"`, `"xxx"`, `lorem ipsum`

#### Test Coverage

For each source file, check whether a corresponding test file exists:
- Look for common patterns: `foo.test.ts`, `foo.spec.ts`, `tests/foo.test.ts`, `__tests__/foo.test.ts`
- Adapt to the project's test convention (check existing test file locations)
- Check whether the test file is also among the uncommitted changes (good sign if modified too)
- For deleted source files, check if the corresponding test was also deleted
- Skip for non-code files (markdown, config, assets, images)

#### REQ Traceability

Based on Step 3 results:
- **Traced (completed)** — file listed in a completed REQ's Implementation Summary
- **Traced (in-progress)** — file listed in a working REQ's file list
- **Untraced** — no matching REQ found

#### Coherence

Check whether the changes work together as a coherent whole:
- Does one file add a feature that another file's changes would break?
- Are two files implementing the same thing differently (e.g., different error handling strategies)?
- Does a config change conflict with assumptions in the code changes?
- Does a deleted file still have imports or references from other changed files?
- Only flag clear contradictions, not stylistic differences

When contradictions are found, surface them in the report under a **Contradictions** label with enough context to resolve them.

#### Safety

Scan diff content for sensitive data patterns:
- API key prefixes: `sk-`, `pk_`, `AKIA`, `ghp_`, `glpat-`
- Connection strings with passwords: `://user:pass@`
- Inline secrets: `password = "..."`, `secret = "..."`, `token = "..."`
- This is a heuristic scan. False positives are acceptable — better to flag and be wrong.

#### Improvement Hints

Flag obvious opportunities without redesigning. Only mention what jumps out:
- File exceeds ~300 lines — may benefit from splitting
- Logic duplicated from another file in the codebase — point to the existing implementation
- Missing types or type assertions where the rest of the codebase is typed
- Overly cryptic naming (single-letter variables, abbreviations that aren't project conventions)
- A simpler pattern exists in the codebase for the same task — reference it
- Dead code introduced (exports with no consumers, unreachable branches)

**Keep it light.** One or two sentences per file, only when something is clearly worth noting. Omit this section entirely for files with nothing to flag.

#### Overall Verdict

Each uncommitted file/group gets one verdict:

- **Ready** — no blocking issues, safe to commit
- **Needs attention** — minor issues (missing tests, TODOs) the user should be aware of
- **Not ready** — blocking issues (WIP code, possible secrets, incomplete implementation)

Committed files (REQ/UR scope only) get a separate label:

- **Already Committed** — already in the repository; shown for informational completeness only. The six readiness signals above are evaluated and any findings are reported, but the verdict label is always "Already Committed" regardless of findings — the user is not deciding whether to commit these files. This is a status label, not a quality judgment.

### Step 6: Report

Print the structured report. See Output Format below.

## Output Format

The report uses a **hybrid format**: narrative explanations per group (like a colleague walking you through the code), followed by a compact readiness summary table at the end for quick scanning.

```markdown
# Inspect Report

**Date:** {timestamp}
**Scope:** {All changes / REQ-NNN / UR-NNN}
**Uncommitted files:** {N} ({M modified}, {A added}, {D deleted})
**Committed files:** {N} (from Implementation Summary — REQ/UR scope only)

## REQ-Associated Changes

### REQ-NNN — {REQ title} ({status})

#### Uncommitted

**What:** Two files in `src/auth/` implement token refresh. `login.ts` adds the refresh logic with a 5-minute expiry window and `login.test.ts` covers the new flow with 3 test cases.

**Why:** Part of the token refresh requirement from REQ-NNN. 2 of 3 files from the Implementation Summary are still uncommitted.

**Hints:** `login.ts` is at 280 lines — still fine, but approaching the point where the refresh logic could be its own module.

#### Committed Files

**What:** `src/auth/types.ts` defines the `RefreshToken` interface used by the refresh logic.

**Why:** Already committed as part of REQ-NNN. Shown here for completeness — no action needed.

---

### REQ-MMM — {REQ title} ({status})

#### Uncommitted

**What:** `src/api/client.ts` adds retry logic with exponential backoff.

**Why:** Part of REQ-MMM's error handling requirements, but the Implementation Summary lists 3 files and only 1 is uncommitted.

**Contradictions:** The retry uses a fixed 3-attempt limit, but `src/config/defaults.ts` (already committed) defines `MAX_RETRIES = 5`. These should match.

#### Committed Files

**What:** `src/api/errors.ts` and `src/config/defaults.ts` provide error types and retry config.

**Why:** Already committed as part of REQ-MMM.

---

## Unassociated Changes

### Config updates

**What:** `package.json` bumps axios from 1.6.0 to 1.7.2.

**Why:** No matching REQ — likely manual dependency maintenance.

---

### Debug utility

**What:** `src/utils/debug-helper.ts` is a new 45-line file for logging request/response pairs.

**Why:** No matching REQ. Filename suggests a debugging aid, not production code.

**Hints:** Contains 3 `console.log` statements and a `// TODO: remove before commit` on line 12. Probably not meant to ship.

---

## Excluded Files

- `.env.local` — environment variables (skipped)

## Readiness Summary

| File | REQ | Status | Verdict |
|------|-----|--------|---------|
| `src/auth/login.ts` | REQ-NNN | uncommitted | Ready |
| `src/auth/login.test.ts` | REQ-NNN | uncommitted | Ready |
| `src/auth/types.ts` | REQ-NNN | committed | Already Committed |
| `src/api/client.ts` | REQ-MMM | uncommitted | Needs attention |
| `src/api/errors.ts` | REQ-MMM | committed | Already Committed |
| `src/config/defaults.ts` | REQ-MMM | committed | Already Committed |
| `package.json` | — | uncommitted | Ready |
| `src/utils/debug-helper.ts` | — | uncommitted | Not ready |

**Overall: Needs attention** — 3 of 5 uncommitted files ready to commit. 1 has a contradicting config value. 1 is a debug file with TODOs. 3 committed files shown for context.
```

**Formatting rules:**

- **What** explains the change in plain language — what each file does and how they relate.
- **Why** traces to the REQ or infers the purpose. Always answer "why does this change exist?"
- **Hints** appear only when something is worth flagging. Omit entirely when nothing stands out.
- **Contradictions** appear only when conflicting changes are found. Omit when none.
- In REQ/UR scope, each REQ group has **Uncommitted** and **Committed Files** subsections. Omit either subsection if empty (e.g., all files committed → no "Uncommitted" subsection).
- The **Readiness Summary** table includes a **Status** column (`committed` / `uncommitted`) alongside the verdict. Committed files always show verdict "Already Committed".
- The **Overall** line at the bottom counts only uncommitted files for the readiness assessment. Committed files are noted separately ("N committed files shown for context").
- Omit sections with no entries (e.g., skip "REQ-Associated Changes" if no files match any REQ).

If the working tree is clean and no REQ/UR scope was specified:

```markdown
# Inspect Report

**Date:** {timestamp}
**Scope:** All changes

No uncommitted changes.
```

## Error Handling

| Situation | Action |
|-----------|--------|
| Not a git repo | Report "Not a git repository" and exit |
| Clean working tree (no scope) | Report "No uncommitted changes" and exit |
| Clean working tree (REQ/UR scope) | Continue — inspect committed files from the Implementation Summary |
| No `do-work/` directory | Skip REQ association (Step 3), still analyze and assess all files |
| Scoped to REQ/UR that doesn't exist | Report "{REQ/UR}-NNN not found in archive or working directory" and exit |
| Scoped REQ/UR has no matching uncommitted files | Continue with committed-only inspection from Implementation Summary. Report shows only committed files under the REQ group |
| Binary files in untracked | Note as binary, skip content analysis, assess based on path/name only |
| Very large number of files (50+) | Process normally but warn: "Large changeset — {N} files. Consider reviewing in smaller batches." |
| All files excluded | Report the exclusions, no analysis to perform |

## What This Action Does NOT Do

- Create commits — use `do work commit` for that
- Modify files — use your editor or `do work run` to fix issues
- Create REQ files — it only reads existing REQs for traceability
- Replace code review — this is a readiness check, not a thorough review
- Run tests — it checks for test file existence, not test results
- Stage changes — it never touches the git index
- Push to remote

## Checklist

```
□ Step 1: Check for git repo
□ Step 1: Run git status, categorize files (M/A/D)
□ Step 1: Identify excluded files (.env, credentials, keys)
□ Step 1: If clean tree + REQ/UR scope, continue (don't exit)
□ Step 2: Read diffs for modified files
□ Step 2: Read contents for new files (skip binaries)
□ Step 2: Note deleted file paths
□ Step 2: (REQ/UR scope) Collect committed files from Implementation Summary via git show
□ Step 3: Scan archive/working for REQs with Implementation Summaries (skip if no do-work/)
□ Step 3: (Scoped) Pre-associate all Implementation Summary files, skip matching
□ Step 3: (Unscoped) Match uncommitted files to REQ file lists
□ Step 4: Semantically group unassociated files (1-5 per group)
□ Step 4: Assign descriptive labels to each group
□ Step 5: Assess completeness (TODOs, debug code, placeholders)
□ Step 5: Check test coverage (corresponding test files)
□ Step 5: Note REQ traceability status
□ Step 5: Check coherence across changed files (flag contradictions)
□ Step 5: Scan for safety issues (secrets in diffs)
□ Step 5: Note improvement hints (length, duplication, missing types, naming)
□ Step 5: Assign per-file and per-group readiness verdicts (Already Committed for committed files)
□ Step 6: Write narrative What/Why per group
□ Step 6: Separate Uncommitted and Committed Files subsections in REQ groups
□ Step 6: Include Hints and Contradictions where applicable
□ Step 6: Report excluded files
□ Step 6: Print readiness summary table with Status column
```

**Common mistakes to avoid:**
- Modifying files or staging changes (this action is read-only)
- Skipping the safety scan for sensitive data patterns
- Giving a "Ready" verdict to files with TODO/FIXME comments in added lines
- Reporting "Untested" for non-code files (config, docs, assets) — use N/A instead
- Omitting the "Why" explanation for each group
- Turning improvement hints into a full code review — keep them light (1-2 sentences)
- Flagging style preferences as contradictions — only flag logical conflicts
- Exiting early when no uncommitted files match a scoped REQ/UR — committed files should still be inspected
- Giving a committed file a "Ready"/"Needs attention"/"Not ready" verdict — use "Already Committed" instead
