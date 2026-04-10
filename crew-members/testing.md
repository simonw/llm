# The Verifier — Testing Crew Member

<!-- JIT_CONTEXT: This file is loaded by the AI agent when working on test-heavy tasks (domain: testing), when the REQ has tdd: true, or when the test failure loop (Step 6.5) exceeds 1 attempt alongside debugging.md. Provides structured guidance on test strategy, framework selection, and common pitfalls. -->

## Core Principle: Tests Prove Behavior, Not Implementation

A good test breaks when the behavior changes, not when the code is refactored. Test the contract (inputs → outputs, side effects, error conditions), not the internal wiring.

## Test Framework Detection

Before writing tests, identify the project's existing test setup. Don't guess — check:

| Indicator | Framework | Runner |
|-----------|-----------|--------|
| `pytest.ini`, `pyproject.toml [tool.pytest]`, `conftest.py` | pytest | `pytest` / `uv run pytest` |
| `jest.config.*`, `"jest"` in package.json | Jest | `npx jest` / `npm test` |
| `vitest.config.*`, `"vitest"` in package.json | Vitest | `npx vitest` |
| `playwright.config.*` | Playwright | `npx playwright test` |
| `cypress.config.*`, `cypress/` dir | Cypress | `npx cypress run` |
| `Cargo.toml` | Rust built-in + cargo-nextest | `cargo test` / `cargo nextest run` |
| `*_test.go` files | Go built-in | `go test ./...` |
| `spec/*_spec.rb`, `.rspec`, `Gemfile` with rspec | RSpec | `bundle exec rspec` |

**Rule:** Use the project's existing framework. Never introduce a second test framework unless the REQ explicitly requests it.

## Testing Pyramid

Choose the right test type for what you're verifying:

```
         /  E2E  \          Few — slow, brittle, high confidence
        / Integration \      Some — real dependencies, moderate speed
       /    Unit Tests  \    Many — fast, isolated, focused
```

- **Unit tests** for pure logic, data transformations, utility functions, state transitions. Mock external dependencies.
- **Integration tests** for API endpoints, database queries, service interactions. Use real (or containerized) dependencies where practical.
- **E2E tests** for critical user journeys only. These are expensive to maintain — don't E2E-test every edge case.

**Default:** If the REQ doesn't specify test type, write unit tests. Escalate to integration tests only when the behavior under test involves real I/O boundaries.

## Writing Good Tests

### Structure: Arrange-Act-Assert

Every test follows three phases. Keep them visually distinct:

```
# Arrange — set up inputs and preconditions
# Act — call the function / trigger the behavior
# Assert — verify the outcome
```

One behavior per test. If a test name needs "and" in it, split it into two tests.

### Naming

Test names should describe the behavior, not the method:

- Good: `test_expired_token_returns_401`, `it("rejects empty email with validation error")`
- Bad: `test_validate`, `it("works")`, `test_function_1`

A failing test name should tell you what broke without reading the test body.

### Assertions

- Assert on **specific values**, not truthiness. `assert result == 42` over `assert result`.
- One logical assertion per test. Multiple `assert` calls are fine if they verify the same behavior (e.g., checking both status code and response body).
- Use the framework's rich matchers (`toEqual`, `toContain`, `pytest.raises`, `assert_called_with`) — they produce better failure messages than raw `==`.

## Mocking Boundaries

### What to Mock
- External HTTP APIs, third-party services
- Clocks / time-dependent behavior (`freezegun`, `jest.useFakeTimers`, `tokio::time::pause`)
- Filesystem and network I/O in unit tests
- Non-deterministic sources (random, UUIDs) when output must be predictable

### What NOT to Mock
- The code under test — if you're mocking the thing you're testing, the test proves nothing
- Simple value objects, data classes, pure functions — just use the real thing
- Database queries in integration tests — that's the point of integration tests

### Mock Hygiene
- Reset mocks between tests. Shared mock state across tests causes ordering-dependent failures.
- Verify mock call counts only when the number of calls matters (e.g., "sends exactly one email"). Avoid `assert_called` on every mock — it couples tests to implementation.
- If a test needs more than 3 mocks, the code under test may have too many dependencies. Note this as a design smell, but don't refactor unless the REQ asks for it.

## Fixture & Setup Patterns

- **Prefer factory functions** over shared fixtures for test data: `make_user(email="test@x.com")` is clearer and more flexible than a global `TEST_USER` constant.
- **Keep fixtures close** to the tests that use them. A shared `conftest.py` / `testHelper.js` is fine for database setup, but test-specific data belongs in the test file.
- **Don't share mutable state** between tests. Each test creates its own data, or fixtures return fresh copies.
- **Database tests**: use transactions that roll back after each test, or truncate tables in setup. Never rely on data left by a previous test.

## Flaky Test Prevention

Tests that pass sometimes and fail sometimes are worse than no tests — they erode trust. Common causes and fixes:

| Cause | Symptom | Fix |
|-------|---------|-----|
| **Time dependency** | Fails near midnight, month boundaries, DST transitions | Use frozen/fake time in tests |
| **Ordering dependency** | Passes alone, fails in suite (or vice versa) | Ensure each test is fully independent; no shared mutable state |
| **Race conditions** | Fails intermittently in CI, passes locally | Use deterministic waits (poll for condition) not `sleep`. Use test-specific ports/resources |
| **Floating point** | `0.1 + 0.2 != 0.3` | Use approximate comparisons (`pytest.approx`, `toBeCloseTo`) |
| **External services** | Fails when network is slow or service is down | Mock external services in unit/integration tests |
| **Random data** | Fails with specific generated values | Use seeded randomness or known edge-case inputs |

**Rule:** If you encounter a flaky test during implementation, fix the flakiness before proceeding. Don't re-run and hope.

## Test Coverage Expectations

- Don't chase a coverage number. 100% coverage with bad assertions is worse than 80% coverage with meaningful tests.
- **Do cover:** Happy paths, error paths, edge cases (empty input, null, boundary values), security-sensitive paths (auth, validation).
- **Don't cover:** Generated code, framework boilerplate, trivial getters/setters, configuration files.
- If the project has a coverage threshold in CI, respect it. Don't lower the threshold to make your code pass.

## Red-Green Workflow (TDD Requests)

When the REQ has `tdd: true`:

1. **Red:** Write a test that captures the expected behavior. Run it. Verify it fails for the right reason (not a syntax error or import failure — the assertion itself must fail).
2. **Green:** Write the minimum code to make the test pass. No more.
3. **Refactor:** Clean up the implementation without changing behavior. Tests must still pass.

**Evidence:** After the Green step, record the test output showing the transition from red to green. This is the Red-Green Proof referenced in the REQ.

## Anti-Patterns

- **Testing implementation details:** Asserting on internal method calls, private state, or execution order when only the output matters. These tests break on every refactor.
- **Copy-paste tests:** 10 tests that differ by one value should be parameterized (`@pytest.mark.parametrize`, `test.each`, table-driven tests in Go).
- **Giant setup, tiny assert:** If 90% of a test is setup, the code under test is doing too much, or the test needs a helper/factory.
- **Asserting on error messages:** Brittle — messages change. Assert on error types, status codes, or structured error fields instead.
- **Commenting out failing tests:** If a test fails, fix it or delete it. Commented-out tests are dead code that no one re-enables.
- **Testing the mock:** When assertions verify mock return values you set up yourself, rather than behavior of the code under test.
- **Test-per-method symmetry:** Mirroring the source file structure 1:1 (one test file per module, one test per method). Test behavior and use cases, not method inventory. Some methods need 5 tests; some need zero.
- **Catch-all assertions:** `expect(result).toBeTruthy()` or `assert response` without checking specific values. These pass on wrong results and catch nothing.
- **Ignoring test output:** Re-running a failing test without reading the failure message. The assertion diff usually points directly at the bug.
