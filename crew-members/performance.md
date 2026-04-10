# The Profiler — Performance Crew Member

<!-- JIT_CONTEXT: This file is loaded by the AI agent when working on performance-related tasks (domain: performance), or when code-review/review-work detects performance anti-patterns in scoped code. Keep rules scoped and concise to minimize token usage. -->

## Core Principle: Measure Before You Optimize

Never optimize based on intuition. Profile first, identify the bottleneck, fix that bottleneck, measure again. Optimizing non-bottleneck code is wasted effort that adds complexity.

## Frontend Performance

### Core Web Vitals Awareness
- **LCP (Largest Contentful Paint)**: Ensure the largest visible element loads within 2.5s. Common blockers: unoptimized hero images, render-blocking CSS/JS, slow server response.
- **INP (Interaction to Next Paint)**: Keep input response under 200ms. Common blockers: long main-thread tasks, synchronous JS in event handlers, layout thrashing.
- **CLS (Cumulative Layout Shift)**: Prevent layout shifts. Common causes: images without dimensions, dynamically injected content above the fold, late-loading fonts.

### Bundle & Loading
- Code-split routes and heavy components. Lazy-load below-the-fold content.
- Tree-shake unused exports. Avoid barrel files that defeat tree-shaking.
- Prefer lightweight alternatives: `date-fns` over `moment`, `zustand` over `redux` (when feature-equivalent).
- Audit bundle size impact of new dependencies before adding them.

### Rendering
- Virtualize lists with 100+ items.
- Avoid re-renders from unstable references (new objects/arrays in render, inline function props).
- Use `requestAnimationFrame` for visual updates, not `setTimeout`.
- Animate only `transform` and `opacity` for compositor-thread animations.

## Backend Performance

### Database
- N+1 detection: queries inside loops must be refactored to batch queries.
- Unbounded queries: every query must have a `LIMIT` or pagination. `SELECT *` without bounds is a finding.
- Index awareness: when adding queries with `WHERE` clauses on new columns, note if an index is needed.
- Connection pooling: one connection per request is a scaling bottleneck.

### API & I/O
- Parallelize independent I/O: `Promise.all`, `asyncio.gather`, goroutines. Sequential independent awaits are a finding.
- Overfetching: API endpoints returning full objects when clients need 2-3 fields. GraphQL projects should use field-level resolvers.
- Caching: repeated expensive computations or DB queries for infrequently-changing data should use a cache layer.
- Streaming: for large payloads (file downloads, large JSON responses), use streaming instead of buffering the full response in memory.

## Observability Basics

Production code that can't be observed is code you can't debug, tune, or trust. Apply these lightweight patterns during implementation — not as an afterthought.

### Structured Logging
- Use structured formats (JSON lines) over free-text `print`/`console.log`. Fields should include: `timestamp`, `level`, `message`, `request_id`, and relevant context (user ID, endpoint, duration).
- Log at boundaries: incoming requests, outgoing calls, error paths. Don't log inside tight loops or hot paths — it becomes the bottleneck.
- Never log secrets, tokens, passwords, PII, or full request/response bodies in production. Redact or omit.

### Health Checks & Readiness
- Every service should expose a health endpoint (`/health`, `/readyz`) that verifies critical dependencies (database, cache, external APIs) are reachable.
- Health checks should be fast (<500ms) and not create load. Don't run a full query — ping the connection pool.

### Metric Naming Conventions
- Use a consistent naming scheme: `<service>_<noun>_<unit>_<aggregation>` (e.g., `api_request_duration_seconds`, `db_pool_connections_active`).
- Track the four golden signals: **latency** (request duration histogram), **traffic** (request count), **errors** (error count by type), **saturation** (queue depth, pool usage).
- Instrument at boundaries: HTTP handlers, database calls, external API calls. Don't instrument every internal function.

### Trace Context
- When the project uses distributed tracing (OpenTelemetry, Datadog, Jaeger), propagate trace context through all outbound calls. Don't break the trace chain.
- Add meaningful span names and attributes at service boundaries. Avoid creating spans for trivial internal operations.

## Anti-Patterns

- **Premature optimization:** Optimizing code that isn't on a hot path. Check call frequency before optimizing.
- **Caching without invalidation:** A cache that never expires is a bug that hasn't manifested yet.
- **Synchronous blocking in async contexts:** `fs.readFileSync` in a request handler, blocking I/O in an async function.
- **Memory leaks:** Event listeners not cleaned up, growing arrays/maps without bounds, closures holding references to large objects.
- **Benchmarking once:** A single benchmark run is noise. Measure multiple times, report median and p99.

## Quality Checks

Before marking implementation complete, verify:

| Criterion | What to check |
|-----------|---------------|
| No N+1 queries | Grep for database calls inside loops |
| No unbounded queries | All queries have LIMIT or pagination |
| No sequential independent I/O | Independent async operations use parallel execution |
| Bundle impact measured | New dependencies assessed for size impact |
| No blocking I/O in async paths | Synchronous file/network operations flagged |
| Structured logging at boundaries | Request/response logging uses structured format with request ID |
| Health check exists | Service exposes a health endpoint if it's a long-running process |
