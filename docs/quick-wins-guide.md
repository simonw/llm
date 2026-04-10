# Quick Wins

Scans a target directory for obvious refactoring opportunities and low-hanging tests to add. Read-only — produces a structured report without modifying code.

## What it looks for

### Refactoring candidates
- Long functions (>50 lines)
- Copy-pasted blocks (duplicated logic)
- God files (>300 lines with mixed concerns)
- Dead code (unreachable or unused exports)
- Hardcoded values (magic numbers, inline URLs)
- Deep nesting (4+ levels)
- Mixed concerns in single files

### Test candidates
- Untested pure functions
- Data transformations without assertions
- Validation logic missing edge case tests
- Config/environment checks
- Obvious boundary conditions

### Performance smells
- Sequential independent async I/O (should be parallelized)
- Unbounded data loading (missing LIMIT, no pagination)

### Security smells
- Hardcoded secrets (API keys, tokens, passwords in source)
- Unescaped user input (raw SQL interpolation, `dangerouslySetInnerHTML`, `eval()`)
- Disabled security features (`rejectUnauthorized: false`, CORS `*` on auth endpoints)
- Debug artifacts in production paths

## Ranking

Each finding is rated:

- **Effort**: Trivial / Small / Medium
- **Impact**: High / Medium / Low

Sorted by best ratio (Trivial + High first). Medium effort + Low impact items are dropped.

## Output

Two tables:

1. **Refactoring Candidates** — file:line, pattern, description, suggested fix, effort/impact
2. **Test Candidates** — file:line, what to test, suggested approach, effort/impact
3. **Security Smells** — file:line, smell category, risk level, suggested fix

Plus an "Already Covered" section noting existing good patterns, and recommended next steps.

## Key rules

- Respects project conventions from prime files
- Skips vendored and generated files
- Checks existing test coverage before suggesting new tests
- Specific references (file:line, function name) — never vague

## Usage

```
do work quick-wins               # scan current directory
do work quick-wins src/          # scan specific directory
do work scan src/api/
do work low-hanging
```
