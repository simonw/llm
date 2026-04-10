# The Renderer — Frontend Crew Member

<!-- JIT_CONTEXT: This file is loaded by the AI agent only when working on frontend-related tasks. Keep rules scoped and concise to minimize token usage. -->

## Implementation Patterns

### Component Structure
- Follow the project's existing component conventions (functional vs class, file organization, naming).
- One component per file unless the project clearly groups related small components.
- Co-locate styles, tests, and types with their component when the project does this.
- Prefer composition over inheritance in component hierarchies.

### State Management
- Use the project's existing state solution — do not introduce a new one.
- Local state for UI-only concerns (open/closed, hover, form input).
- Shared/global state only when multiple unrelated components need the same data.
- Derive computed values rather than storing redundant state.

### Performance Baseline
- Avoid re-renders from unstable references (new objects/arrays in render, inline function definitions in JSX when they cause child re-renders).
- Lazy-load routes and heavy components when the project supports code splitting.
- Images: use appropriate formats, provide dimensions to prevent layout shift.

### Error Handling
- Every data fetch needs loading, success, and error states.
- Form validation: client-side for UX, never trust it for security.
- Display user-friendly error messages — log technical details to console.
- Error boundaries (React) or equivalent: catch rendering failures without crashing the entire app.
- Retry logic for transient network failures — distinguish between 4xx (don't retry) and 5xx/network errors (retry with backoff).
- Graceful degradation: if a non-critical feature fails to load, the rest of the page still works.
- Never swallow errors silently — at minimum, log to an error tracking service or console.

### Animation & Rendering Performance
- Animate only `transform` and `opacity` — these run on the compositor thread. Animating `width`, `height`, `top`, `left`, `margin`, or `padding` triggers layout recalculation.
- Use `will-change` sparingly and only on elements that will actually animate. Remove it after animation completes.
- Respect `prefers-reduced-motion` — disable non-essential animations when the user requests it.
- Virtualize long lists (>100 items visible) — react-window, tanstack-virtual, or framework equivalent.
- Debounce resize/scroll event handlers. Use `IntersectionObserver` over scroll-position polling.

### Frontend Security
- Never use `dangerouslySetInnerHTML` (React), `v-html` (Vue), or `[innerHTML]` (Angular) with unsanitized user content. Use DOMPurify or equivalent.
- Validate and sanitize all user input on the client for UX, but enforce on the server for security.
- Never store auth tokens in `localStorage` — use `httpOnly` cookies.
- Never bundle API keys or secrets in client-side code.
- Set `rel="noopener noreferrer"` on external `target="_blank"` links.

## Quality Checks

Before marking UNIFY complete, verify:

| Criterion | What to check |
|-----------|---------------|
| Renders without errors | No console errors/warnings on mount and primary interaction |
| Responsive | Tested or verified at 320px, 768px, 1280px minimum |
| Accessible | Keyboard navigable, semantic HTML, no missing alt/labels |
| No regressions | Existing tests still pass after changes |
| Bundle impact | No unnecessary large dependencies added |

## Scope Discipline

- Do not refactor unrelated components while fixing a bug in one.
- Do not upgrade dependencies unless the REQ explicitly requests it.
- Do not switch styling approaches (e.g., CSS modules to Tailwind) as a side effect.
