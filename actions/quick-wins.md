# Quick-Wins Action

> **Part of the do-work skill.** Scans a target directory for obvious refactoring opportunities and low-hanging tests to add.

**Read-only** — this action does NOT modify any files. It produces a structured report only.

## Input

`$TARGET` comes from `$ARGUMENTS` — a directory path. If empty, defaults to the current working directory.

## Steps

### Step 1: Load Context

- Resolve `$TARGET` to a concrete directory (default: cwd)
- Check for `prime-*.md` files in and around the target — these contain project context, conventions, and architecture notes
- Read any available `prime-*.md` files to understand the project's patterns and standards before scanning

### Step 2: Survey the Codebase

- Detect the languages in use by checking for project markers (`package.json`, `Cargo.toml`, `go.mod`, `requirements.txt`, `Gemfile`, `composer.json`, `pom.xml`, `*.csproj`, etc.) and scanning file extensions
- Glob for source files matching the detected languages — adapt the extensions to what's actually in the repo (e.g., `*.go` for Go, `*.rs` for Rust, `*.java` for Java, `*.rb` for Ruby, `*.sh` for shell, `*.js,*.ts,*.jsx,*.tsx` for JS/TS, `*.py` for Python, etc.)
- **Skip vendored/generated files**: ignore `node_modules/`, `vendor/`, `dist/`, `build/`, `.next/`, `__pycache__/`, `*.min.js`, `*.min.css`, `*.bundle.*`, `*.generated.*`, lock files, and similar
- Build a file list with approximate line counts
- Note the primary language(s) and frameworks in use

### Step 3: Identify Refactoring Candidates

Scan source files for these patterns:

| Pattern | What to look for |
|---------|-----------------|
| **Long functions** | Functions/methods exceeding ~50 lines. Note the function name, file, and line range |
| **Copy-pasted blocks** | Near-identical code blocks appearing in 2+ locations. Note both locations |
| **God files** | Files doing too many unrelated things, or files exceeding ~300 lines with low cohesion |
| **Dead code** | Exported functions with no importers, commented-out blocks, unreachable branches |
| **Hardcoded values** | Magic numbers, hardcoded URLs/paths/credentials, values that should be config |
| **Deep nesting** | Conditionals nested 4+ levels deep. Note the file and line range |
| **Mixed concerns** | Files mixing business logic with I/O, UI with data fetching, config with runtime logic |
| **Sequential async I/O** | Multiple independent `await` calls in sequence where `Promise.all`/`asyncio.gather` would work. Note the file and estimated concurrency gain |
| **Unbounded data loading** | Queries without `LIMIT`, array operations on full datasets, API responses with no pagination |

For each candidate, record:
- **File** and **line range** (be specific — `src/utils/parse.ts:45-112`, not just "parse.ts")
- **Function/symbol name** where applicable
- **Pattern** (which category from the table above)
- **What's wrong** (1 sentence — be concrete)
- **Suggested fix** (1 sentence — be actionable)

### Step 3.5: Security Smell Scan

Scan for obvious security anti-patterns. This is not a full audit (use the code-review action for that) — it catches low-hanging risks:

| Smell | What to look for |
|-------|-----------------|
| **Hardcoded secrets** | API keys, tokens, passwords, connection strings in source (not `.env`) |
| **Unescaped user input** | `dangerouslySetInnerHTML`, raw SQL interpolation, `eval()` with variables |
| **Disabled security** | `rejectUnauthorized: false`, CORS `*` on authenticated endpoints, disabled CSRF |
| **Debug artifacts in production paths** | `console.log` of sensitive data, `DEBUG=true` in non-dev config |

For each smell, record: file, line range, smell category, risk level (High/Medium), and a one-sentence suggested fix.

### Step 4: Identify Low-Hanging Tests

Before scanning, check for existing test infrastructure:
- Look for test directories (`__tests__/`, `test/`, `tests/`, `spec/`)
- Look for test files (`*.test.*`, `*.spec.*`, `*_test.*`)
- Check for test config (`jest.config.*`, `vitest.config.*`, `pytest.ini`, `setup.cfg`, `.mocharc.*`, `phpunit.xml`)
- Note what's already covered so you don't suggest duplicates

Then scan for untested code that would be easy to test:

| Category | What to look for |
|----------|-----------------|
| **Pure functions** | Functions with no side effects — take inputs, return outputs. These are the easiest to test |
| **Data transformations** | Mappers, formatters, serializers, parsers — anything that reshapes data |
| **Validation logic** | Input validators, schema checks, guard clauses, permission checks |
| **Config sanity checks** | Config loading, environment variable parsing, default value logic |
| **Obvious edge cases** | Empty arrays, null inputs, boundary values, off-by-one candidates in existing tested code |

For each candidate, record:
- **File** and **function name** (be specific)
- **Category** (from the table above)
- **Why it's easy to test** (1 sentence)
- **Example test case** (1 sentence describing what to assert)

### Step 5: Rank by Effort vs Impact

Rate each finding:

**Effort:**
- **Trivial** — under 15 minutes, mechanical change
- **Small** — 15-60 minutes, straightforward but needs thought
- **Medium** — 1-3 hours, requires some refactoring

**Impact:**
- **High** — fixes a real maintenance pain point, prevents bugs, or significantly improves clarity
- **Medium** — noticeable improvement, but codebase works fine without it
- **Low** — nice-to-have, cosmetic, or marginal benefit

**Risk-impact scoring:** When two findings have the same effort/impact category, break ties using objective metrics:
- **Cyclomatic complexity** — higher complexity = higher refactoring value (functions with 10+ branches are strong candidates)
- **Nesting depth** — 4+ levels of nesting is a reliable smell regardless of function length
- **Import count** — files imported by many others have higher blast radius; refactoring them benefits more consumers
- **Change frequency** — files modified often (check `git log --format='' --name-only | sort | uniq -c | sort -rn`) are better targets than stable files

**False positive check:** Before reporting a finding, verify it's a genuine improvement opportunity:
- A long function may be appropriate if it's a state machine, parser, or migration — check if the length serves a purpose
- A "god file" may be intentional if `prime-*.md` documents describe it as a deliberate convention
- Dead code may be used dynamically (plugin systems, reflection, conditional requires) — check for non-static usage patterns

**Behavior preservation rule:** Every refactoring candidate in the report must be achievable without changing observable behavior. If a refactoring would require changing tests or API contracts, note it explicitly — it's a different class of work.

Sort findings by priority: **Trivial effort + High impact first**, then Small+High, Trivial+Medium, and so on. Drop anything that's Medium effort + Low impact — not worth mentioning.

## Output Format

Produce a markdown report with this structure:

```markdown
# Quick-Wins Report

**Target**: {resolved directory path}
**Scanned**: {N} files across {languages}
**Date**: {today}

## Refactoring Candidates

| # | File | Lines | Pattern | What's Wrong | Fix | Effort | Impact |
|---|------|-------|---------|-------------|-----|--------|--------|
| 1 | `src/utils/parse.ts:45-112` | 67 | Long function | `parseConfig` does validation, parsing, and fallback logic in one block | Extract validation and fallback into separate functions | Trivial | High |
| ... | | | | | | | |

## Test Candidates

| # | File | Function | Category | Why Easy to Test | Example Test | Effort | Impact |
|---|------|----------|----------|-----------------|-------------|--------|--------|
| 1 | `src/utils/format.ts` | `formatCurrency` | Pure function | No side effects, takes number + locale, returns string | `formatCurrency(1234.5, 'en-US')` → `'$1,234.50'` | Trivial | High |
| ... | | | | | | | |

## Security Smells

| # | File | Lines | Smell | Risk | Suggested Fix |
|---|------|-------|-------|------|---------------|
| 1 | `src/db/query.ts:23` | 1 | Unescaped user input | High | Use parameterized query instead of string interpolation |
| ... | | | | | |

## Already Covered

{List any areas where tests or clean patterns already exist — give credit where it's due. If a module is well-tested, say so. This prevents wasted effort re-analyzing good code.}

## Recommended Next Steps

1. {Highest-priority action — be specific}
2. {Second priority}
3. {Third priority}

> To act on these findings:
>   do work [describe the fix]     Capture as a request
>   do work run                    Process the queue
```

## Common Rationalizations

Guard against these when producing the report:

| If you're thinking... | STOP. Instead... | Because... |
|---|---|---|
| "This file is long so it must be a refactoring candidate" | Check if the length serves a purpose (state machine, migration, parser) | Length alone is not a smell |
| "No quick wins found" after scanning 3 files | Verify you scanned all source files in scope | Small scan = invisible problems |
| "This looks like dead code" | Grep for dynamic references, re-exports, and framework conventions | Static analysis misses dynamic usage |
| "I'll pad the report with low-impact findings" | Only report findings above the effort/impact threshold | Padding erodes trust in the report |

## Rules

- **Do NOT modify any files.** This action is read-only. Report only.
- **Be specific.** Every finding must include a file path, line range or function name, and a concrete description. "Some files are too long" is useless — "`src/api/handlers.ts` is 847 lines with 12 unrelated route handlers" is useful.
- **Be honest about impact.** Don't inflate findings to make the report look impressive. If the codebase is clean, say so. A short report with real findings beats a long report with filler.
- **Skip vendored and generated files.** Don't report issues in `node_modules/`, `vendor/`, `.next/`, compiled output, or generated code.
- **Check before suggesting tests.** If a function already has test coverage, don't suggest testing it again. Note it in "Already Covered" instead.
- **Respect project conventions.** If `prime-*.md` files describe deliberate patterns (e.g., "we use god files for route handlers"), don't flag those as problems.
