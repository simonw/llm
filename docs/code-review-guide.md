# Code Review (Standalone)

Review the actual codebase independent of the task queue. Evaluates consistency, architecture, security, and test coverage across a scoped section of your project. Read-only — never modifies source files.

## Scoping

Three ways to define what gets reviewed:

### Prime file scope
```
do work code-review prime-auth             # everything prime-auth.md references
do work code-review prime-auth prime-checkout  # union of both
```

### Directory scope
```
do work code-review src/                   # all source files in src/
do work code-review src/api/ src/utils/    # multiple directories
```

### Combined
```
do work code-review prime-auth src/utils/  # prime file scope + directory
```

### Interactive (no arguments)
```
do work code-review                        # lists available prime files, asks
```

## Review dimensions

### Consistency
Naming conventions, error handling patterns, API shapes, import organization, type usage, logging, config management, code organization. Each finding shows both patterns found and identifies the dominant one.

### Architecture & Patterns
Separation of concerns, dependency direction, abstraction health (over- or under-abstracted), state management, interface contracts.

### Security & Risk
Input validation, auth checks, data exposure, injection vectors, dependency concerns, hardcoded secrets.

### Test Coverage
Existing tests for scoped code, coverage gaps, test quality, missing test categories.

### Performance
Hot-path anti-patterns: N+1 queries, unbounded queries, sequential I/O, missing caching, bundle bloat, no list virtualization, synchronous blocking, overfetching. Only flags plausibly hot paths.

### Automated Checks
Runs the project's linter, type checker, and relevant tests against the scoped files.

## Health ratings

| Rating | Meaning |
|--------|---------|
| **Excellent** | Consistent patterns, clean architecture, good tests, no security concerns |
| **Good** | Mostly consistent, sound architecture, some test gaps, few important findings |
| **Needs Attention** | Multiple consistency issues, architectural concerns, significant test gaps |
| **Concerning** | Widespread inconsistency, architectural problems, security vulnerabilities |

## Output

Structured markdown report with: summary, findings tables by dimension (with file:line references and severity), strengths, and top 3 recommended actions.

## Guardrails

Includes anti-rationalization tables (guards against shortcuts like "this pattern is used elsewhere so it's fine" or "tests exist so the code is correct") and a verification checklist to ensure all 6 dimensions are covered before the report is finalized.

## Depth scaling

- 5 files: line-by-line review
- 50 files: pattern-focused scan
- 200+ files: sampling strategy focused on critical paths

## Usage

```
do work code-review
do work code-review prime-auth
do work code-review src/api/
do work code-review prime-auth src/utils/
do work audit codebase
do work codebase review
```
