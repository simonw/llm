# The Engineer — Backend Crew Member

<!-- JIT_CONTEXT: This file is loaded by the AI agent only when working on backend-related tasks. Keep rules scoped and concise to minimize token usage. -->

## Implementation Patterns

### API Design
- Follow the project's existing API conventions (REST, GraphQL, RPC).
- Consistent error response format across endpoints.
- Input validation at the boundary — never trust client data.
- Use appropriate HTTP status codes (don't 200 everything).

### Data Layer
- Follow the project's existing ORM/query patterns.
- Migrations for schema changes — never modify production schemas directly.
- Transactions for multi-step writes that must succeed or fail together.
- Parameterized queries — no string interpolation for SQL.

### Security Baseline
- Authentication checks on every protected endpoint.
- Authorization: verify the user can access the specific resource, not just that they're logged in.
- No secrets in code, logs, or error responses.
- Rate limiting awareness — note if an endpoint needs it and doesn't have it.

### Error Handling
- Catch errors at the boundary (route handler / controller), not deep in business logic.
- Log with enough context to debug (request ID, user ID, action) but never log sensitive data (passwords, tokens, PII).
- Return structured errors to clients; keep stack traces server-side.

### API Resilience
- Rate limiting: be aware of which endpoints need it (login, signup, password reset, public search). Note if rate limiting is missing when adding or modifying these endpoints.
- API versioning: follow the project's existing convention (URL prefix `/v1/`, header-based, query param). If no convention exists and you're creating a new API surface, use URL prefix versioning and document the choice as a Decision (D-XX).
- Timeouts: set explicit timeouts on all outbound HTTP calls. Never rely on the default (which may be infinite).
- Idempotency keys: for non-idempotent write endpoints exposed to retries (payment, order creation), note if an idempotency mechanism is missing.
- Circuit breakers: when calling external services, note if the failure mode is "cascade" (one service down brings everything down).

### Async & Concurrency
- Follow the project's concurrency model — don't mix paradigms (e.g., threads + asyncio, callbacks + promises).
- **Async/await:** Never call blocking I/O (file reads, synchronous HTTP, `time.sleep`) inside async functions. Use async equivalents (`aiofiles`, `fetch`, `asyncio.sleep`).
- **Shared mutable state:** If multiple coroutines/threads/goroutines access the same data, protect it (locks, atomics, channels, immutable snapshots). Race conditions are silent until production.
- **Parallelism for independent work:** When making multiple independent I/O calls, parallelize them (`Promise.all`, `asyncio.gather`, `sync.WaitGroup`, `tokio::join!`). Sequential independent awaits are a performance bug.
- **Cancellation & timeouts:** Long-running async operations should respect cancellation (abort signals, context cancellation, `CancellationToken`). Never fire-and-forget without cleanup.
- **Connection lifecycle:** Database connections, HTTP clients, and gRPC channels should be reused via pools — not created per request. Close/release connections in `finally` blocks or use context managers.

### Dependency Awareness
- Before adding a new dependency, check if the existing stack already provides the functionality. Prefer stdlib or existing deps over new ones.
- **Vulnerability check:** After adding or upgrading dependencies, note whether `npm audit` / `pip audit` / `cargo audit` / equivalent reports new vulnerabilities. Don't block on advisory-only findings, but flag Critical/High severity.
- **Lockfile hygiene:** Commit lockfiles (`package-lock.json`, `uv.lock`, `Cargo.lock`, `Gemfile.lock`). If the lockfile changes unexpectedly, investigate — don't blindly commit.
- **Pinned versions for security-critical deps:** Auth libraries, crypto packages, and serialization libraries should use exact versions, not ranges.

### Performance Awareness
- N+1 queries: if you see a database call inside a loop, refactor to a batch query.
- Pagination: never return unbounded result sets. All list endpoints should accept `limit`/`offset` or cursor parameters.
- Caching: for data that changes infrequently (config, feature flags, user permissions), note where a cache could help. Don't implement caching without the REQ requesting it, but flag it in Discovered Tasks.
- Connection pooling: note if database connections are being opened per-request instead of pooled.

## Quality Checks

Before marking UNIFY complete, verify:

| Criterion | What to check |
|-----------|---------------|
| Handles invalid input | Malformed requests return 400, not 500 |
| Auth enforced | Protected routes reject unauthenticated/unauthorized requests |
| No data leaks | Error responses don't expose internal details |
| Idempotency | Safe methods (GET) have no side effects; writes handle retries |
| Existing tests pass | No regressions in adjacent endpoints or services |
| No blocking I/O in async paths | Synchronous calls don't sneak into async handlers |
| Dependencies clean | No new Critical/High vulnerabilities from added deps |

## Scope Discipline

- Do not refactor unrelated endpoints while fixing a bug in one.
- Do not change database schemas beyond what the REQ requires.
- Do not introduce new dependencies for functionality the existing stack already provides.
