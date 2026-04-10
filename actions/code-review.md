# Code Review Action

> **Part of the do-work skill.** Standalone codebase review — not tied to the REQ/UR queue. Evaluates consistency, patterns, security, and architectural health across a scoped section of the codebase.

**Source-code read-only** — this action does NOT modify any project source files. It produces a structured report only. May write queue metadata (`do-work/REQ-*` files) with explicit user confirmation — see Step 10.

## Input

`$ARGUMENTS` determines the review scope. Two targeting modes:

### Mode 1: Prime File Target

```
do work code-review prime-auth
do work code-review prime-auth.md
do work code-review src/prime-auth.md
do work code-review prime-auth prime-checkout
```

When `$ARGUMENTS` contains one or more prime file references:
1. Resolve each prime file — search for `prime-*.md` matching the argument (with or without `prime-` prefix, with or without `.md` extension)
2. Read each prime file to discover the files it references (source files, config files, related modules)
3. The review scope is the **union of all files referenced by the target prime files**
4. If a prime file references directories, include all source files in those directories

### Mode 2: Directory Target

```
do work code-review src/
do work code-review src/api/ src/utils/
do work code-review .
```

When `$ARGUMENTS` contains one or more directory paths:
1. Resolve each directory
2. The review scope is **all source files in those directories** (recursive)
3. Still load any `prime-*.md` files found in or above those directories for context — but the scope is the directory contents, not just what primes reference

### Combined Mode

```
do work code-review prime-auth src/utils/
do work code-review prime-checkout src/shared/
```

When `$ARGUMENTS` contains both prime file references and directory paths:
1. Resolve prime files → collect their referenced files
2. Resolve directories → collect their source files
3. The review scope is the **union of both sets**

### Default (no arguments)

```
do work code-review
```

If no arguments provided:
1. Search for all `prime-*.md` files in the project
2. If prime files exist, list them and ask the user which scope to review — don't review everything by default
3. If no prime files exist, default to the current working directory (like quick-wins)

## Steps

### Step 1: Resolve Scope

1. Parse `$ARGUMENTS` into prime file references and directory paths
2. Resolve prime files: search for matching `prime-*.md` files, read them, extract referenced files and directories
3. Resolve directories: glob for source files (same language detection as quick-wins — check for `package.json`, `Cargo.toml`, `go.mod`, etc. and scan extensions)
4. **Skip vendored/generated files**: ignore `node_modules/`, `vendor/`, `dist/`, `build/`, `.next/`, `__pycache__/`, `*.min.js`, `*.min.css`, `*.bundle.*`, `*.generated.*`, lock files, and similar
5. Build the final file list with line counts
6. Report the resolved scope to the user before proceeding:
   ```
   Scope: 23 files across src/auth/, src/utils/validation.ts, src/middleware/
   Prime context: prime-auth.md, prime-validation.md
   ```

### Step 2: Load Context

- Read all resolved `prime-*.md` files — these define the project's conventions, architecture, and known patterns
- Read any `crew-members/*.md` files if present — these contain domain-specific standards
- Check for linter configs (`.eslintrc*`, `.prettierrc*`, `biome.json`, `rustfmt.toml`, `.rubocop.yml`, `ruff.toml`, etc.) — note what the project already enforces automatically
- Check for CI config (`.github/workflows/`, `.gitlab-ci.yml`, `Makefile`, etc.) — understand what's already validated in the pipeline

### Step 3: Consistency Review

Evaluate consistency **within the scoped files** and **against project conventions** from prime files:

| Dimension | What to check |
|-----------|--------------|
| **Naming conventions** | Are functions, variables, types, files, and directories named consistently? Mixed camelCase/snake_case? Inconsistent prefixes/suffixes? Abbreviations used in some places but not others? |
| **Error handling** | Is error handling consistent? Same pattern used everywhere, or a mix of try/catch, result types, error codes, and silent swallows? Are errors logged consistently? |
| **API patterns** | Do similar endpoints/functions follow the same structure? Consistent parameter ordering, return shapes, status codes, response formats? |
| **Import/module organization** | Consistent import ordering? Circular dependencies? Files importing from unexpected layers (e.g., UI importing from database)? |
| **Type usage** | Consistent use of types/interfaces? `any` or untyped escape hatches? Inconsistent nullability handling? |
| **Logging & observability** | Consistent log levels, formats, and context? Missing logging in critical paths? Excessive logging in hot paths? |
| **Config & environment** | Hardcoded values that should be config? Inconsistent env var access patterns? Missing defaults? |
| **Code organization** | Files that mix concerns? Utility functions scattered vs centralized? Inconsistent file/folder structure within the scope? |

For each finding, record:
- **Files** affected (with line references where relevant)
- **What's inconsistent** (concrete — show both patterns, not just "naming is inconsistent")
- **Which pattern is dominant** (so the fix is clear — align to the majority)
- **Severity**: Critical / Important / Minor / Nit

### Step 4: Pattern & Architecture Review

Look at the bigger picture within the scoped files:

| Dimension | What to check |
|-----------|--------------|
| **Separation of concerns** | Are responsibilities clearly divided? Business logic mixed with I/O? Presentation mixed with data access? |
| **Dependency direction** | Do dependencies flow in a sensible direction? Higher-level modules importing lower-level, or spaghetti? |
| **Abstraction health** | Are abstractions earning their keep? Over-abstracted code (interfaces with one implementation, factories for one type)? Under-abstracted code (duplicated logic that should be shared)? |
| **State management** | Is state handled consistently? Global mutable state? Unclear ownership? Race condition opportunities? |
| **Interface contracts** | Are module boundaries clear? Could you swap an implementation without touching callers? Are internal details leaking? |

### Step 5: Security & Risk Scan

Check the scoped files for:

| Category | What to look for |
|----------|-----------------|
| **Input validation** | Unvalidated user input flowing into queries, commands, file paths, or rendered output |
| **Authentication/authorization** | Missing auth checks, inconsistent permission enforcement, privilege escalation paths |
| **Data exposure** | Sensitive data in logs, error messages, API responses, or client bundles |
| **Injection vectors** | SQL injection, command injection, XSS, path traversal, template injection |
| **Dependency concerns** | Known vulnerable patterns, outdated security practices, missing CSRF/CORS protections |
| **Secrets** | Hardcoded credentials, API keys, tokens — even if they look like placeholders |

If `crew-members/security.md` exists, load it and apply the OWASP Top 10 checklist and framework-specific patterns to the scoped code. Classify findings using the same severity scale as the rest of this review (Critical / Important / Minor / Nit). Map security-specific levels: Critical → Critical, High → Important, Medium → Minor, Low → Nit.

Only report findings relevant to the code in scope. Don't flag theoretical risks that don't apply.

### Step 6: Performance Anti-Pattern Scan

Scan scoped files for common performance anti-patterns. Check what's relevant to the detected stack:

| Pattern | What to look for |
|---------|-----------------|
| **N+1 queries** | Loops that execute a query per iteration. ORM `.find()` inside a `.map()` or `for` loop |
| **Unbounded queries** | `SELECT *` without `LIMIT`, or queries that fetch entire tables into memory |
| **Sequential I/O** | Multiple independent async operations run sequentially instead of concurrently (`Promise.all`, `asyncio.gather`) |
| **Missing caching** | Repeated expensive computations or DB queries for data that changes infrequently |
| **Bundle bloat** | Large dependencies imported for small features. No code splitting. `moment.js` when `date-fns` suffices |
| **No virtualization** | Rendering 1000+ DOM nodes in a list when only 20 are visible |
| **Synchronous blocking** | Blocking I/O in async contexts. `fs.readFileSync` in a request handler |
| **Overfetching** | API endpoints returning full objects when clients need 2-3 fields |

For each finding, record the file, line range, pattern, and estimated impact (High / Medium / Low). Only report patterns where the code is on a plausibly hot path — don't flag one-time startup code or CLI scripts.

If no performance anti-patterns are found in scope, skip this section entirely rather than padding with non-findings.

### Step 7: Test Coverage Assessment

Evaluate testing for the scoped code:

1. **Find related tests** — look for test files that import from or exercise the scoped source files
2. **Coverage gaps** — which scoped files/functions have no test coverage at all?
3. **Test quality** — for existing tests, are assertions meaningful? Do they test behavior or just structure?
4. **Missing test categories** — unit tests present but no integration tests? Happy path only, no error cases?
5. **Risk-driven priorities** — cross-reference coverage gaps with module risk. Untested code that handles authentication, payments, or user data is a more urgent gap than an untested utility formatter. Flag critical-risk + untested combinations explicitly.

If the project has no test infrastructure, note it and skip — don't penalize.

### Step 8: Run Existing Checks

If the project has automated checks, run them against the scoped code:

1. **Linter** — run the project's linter if configured (eslint, ruff, rubocop, clippy, etc.). Report any findings not already caught.
2. **Type checker** — run type checking if applicable (tsc, mypy, pyright, etc.). Report errors in scoped files.
3. **Tests** — run tests related to the scoped files. Report failures.

If checks pass cleanly, note it — a clean bill of health is useful information.

If you can't run checks (missing dependencies, env issues), note what you couldn't run and why.

### Step 9: Synthesize & Report

Produce a structured report:

```markdown
# Code Review Report

**Scope**: {description of what was reviewed}
**Files reviewed**: {N} files ({total lines} lines)
**Prime context**: {list of prime files used, or "None"}
**Date**: {today}

## Summary

{2-3 sentences — overall health assessment. Lead with the most important finding. Be honest — if the code is solid, say so.}

**Overall health: {Excellent / Good / Needs Attention / Concerning}**

## Consistency

| # | Finding | Files | Severity | Dominant Pattern | Recommendation |
|---|---------|-------|----------|-----------------|----------------|
| 1 | {concrete description} | {file:line references} | Important | {the pattern to align to} | {specific fix} |

## Architecture & Patterns

| # | Finding | Files | Severity | Recommendation |
|---|---------|-------|----------|----------------|
| 1 | {concrete description} | {file:line references} | {level} | {specific fix} |

## Security & Risk

| # | Finding | Files | Severity | Recommendation |
|---|---------|-------|----------|----------------|
| 1 | {concrete description} | {file:line references} | {level} | {specific fix} |

{If no security findings: "No security concerns identified in the reviewed scope."}

## Performance

| # | Finding | Files | Pattern | Impact | Recommendation |
|---|---------|-------|---------|--------|----------------|
| 1 | {concrete description} | {file:line references} | {anti-pattern} | {High/Med/Low} | {specific fix} |

{If no performance findings: omit this section entirely.}

## Test Coverage

**Coverage**: {qualitative assessment — Well-tested / Partially tested / Gaps / Untested}

| Area | Status | Notes |
|------|--------|-------|
| {module/file} | {Covered / Partial / Missing} | {what's tested, what's not} |

## Automated Checks

| Check | Result | Notes |
|-------|--------|-------|
| {linter} | {Pass / N findings / Skipped} | {details} |
| {type checker} | {Pass / N errors / Skipped} | {details} |
| {tests} | {Pass / N failures / Skipped} | {details} |

## Strengths

{Give credit where it's due. List 2-3 things the code does well. Patterns worth keeping, clean modules, good test coverage in specific areas.}

## Recommended Actions

1. **{Highest priority}** — {1 sentence, specific}
2. **{Second priority}** — {1 sentence, specific}
3. **{Third priority}** — {1 sentence, specific}

{Rank by: Critical severity first, then Important, then by effort-to-impact ratio.}
```

### Step 10: Create Follow-up REQs (Optional)

For **Critical** and **Important** findings that warrant action, offer to create REQ files:

```
Found 3 Critical and 5 Important findings.
Create REQ files for these? (The user can run `do work run` to process them later.)
```

Only create REQ files if the user explicitly confirms. If running non-interactively (e.g., via subagent), **skip REQ creation entirely** — include the findings in the report and let the user decide whether to capture them as requests afterward. The code-review action is read-only by default in all modes.

When the user confirms, create REQ files using the standard format:

```markdown
---
id: REQ-NNN
title: "Code review: [brief description]"
status: pending
created_at: [timestamp]
review_generated: true
source: code-review
scope: [prime file or directory that surfaced this]
---

# Code Review Fix: [Brief Description]

## What
[Describe the issue and the fix needed]

## Context
Found during code review of [scope]. [1 sentence on the specific finding.]

## Requirements
- [Specific fix needed]
```

Do NOT auto-create REQs without confirmation. The report itself is the primary output.

## Health Rating Guidelines

**Excellent** — Consistent patterns, clean architecture, good test coverage, no security concerns. Minor nits only.

**Good** — Mostly consistent with a few deviations. Architecture is sound. Some test gaps. No critical issues. A few Important findings.

**Needs Attention** — Multiple consistency issues. Architectural concerns (mixed concerns, unclear boundaries). Significant test gaps. One or more Critical findings.

**Concerning** — Widespread inconsistency. Architectural problems. Security vulnerabilities. Minimal test coverage. Multiple Critical findings.

## Rules

- **Be specific.** Every finding must include file paths and line references. "Error handling is inconsistent" is useless — "`src/api/users.ts:45` uses try/catch with custom AppError, but `src/api/orders.ts:72` uses bare throw with string messages" is useful.
- **Show both sides.** For consistency findings, always show the two (or more) patterns you found. The user needs to see the contrast.
- **Respect conventions from prime files.** If a prime file says "we use god files for route handlers," don't flag the god file as a problem. Prime files are the project's own voice.
- **Don't flag what linters catch.** If the project has eslint configured to catch missing semicolons, don't report missing semicolons. Focus on what automation misses.
- **Proportional depth.** 5 files get a thorough line-by-line review. 50 files get a pattern-focused scan. 200+ files get a sampling strategy with focus on critical paths. State your approach in the report.
- **Skip vendored and generated files.** Same exclusions as quick-wins.
- **Be honest.** If the code is clean, say so. A short report with real findings beats a long report with filler. An "Excellent" rating with zero findings is a valid outcome.
- **Stay in scope.** Only review files within the resolved scope. Don't wander into unrelated parts of the codebase. If you notice something outside scope that's concerning, mention it briefly in a "Notes" section but don't score it.

## Common Rationalizations

Guard against these when writing the review report:

| If you're thinking... | STOP. Instead... | Because... |
|---|---|---|
| "This pattern is fine because it's used elsewhere in the codebase" | Check if the existing usage is itself an anti-pattern | Widespread problems are still problems |
| "No security issues found" after a surface scan | Trace every user input to its sink | Surface scans miss injection, XSS, and SSRF |
| "Performance is probably fine" | Check if the code is on a hot path before skipping | "Probably" is not profiling |
| "Tests exist so the code is correct" | Read what the tests actually assert | `expect(true).toBe(true)` is a test that exists |
| "The architecture is too big to evaluate in this review" | Evaluate the scoped slice; note what's out of scope | Partial evaluation beats no evaluation |
| "I already noted enough findings" | Check coverage of all 6 review dimensions | Premature stopping misses entire categories |

## Verification Checklist

Before finalizing the report, verify:

- [ ] All 6 review dimensions attempted: Consistency, Architecture, Security, Performance, Test Coverage, Automated Checks
- [ ] Every finding has file:line references and shows concrete code patterns (not abstract descriptions)
- [ ] Health rating matches the evidence (no "Excellent" with Critical findings, no "Concerning" with only Nits)
- [ ] Recommended Actions are ordered by severity then effort-to-impact ratio
- [ ] Strengths section has 2-3 genuine positives (not filler)
- [ ] No findings that the project's configured linter/type-checker would already catch
