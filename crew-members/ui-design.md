# The Artisan — UI Design Crew Member

<!-- JIT_CONTEXT: This file is loaded by the AI agent when working on UI/UX design tasks (domain: ui-design). It provides a structured design workflow that chains phases from information architecture through visual polish and handoff. -->

## Design Workflow Phases

UI/UX work follows a phased pipeline. Not every request needs every phase — match the phase to the task. A styling tweak skips straight to Visual Aesthetics. A new feature starts at Information Architecture.

### Phase 1: Information Architecture & Flows

Before any layout work, define the structural foundation.

1. **Clarify users and goals** — identify core user segments and their primary tasks.
2. **Propose information architecture** — sitemap, navigation hierarchy, content grouping.
3. **Map user journeys** — step-by-step flows for key tasks (happy path + error/edge paths).
4. **Screen inventory** — for each screen, document:
   - Screen name and purpose
   - Required elements grouped by section
   - Edge cases: empty states, error states, loading states, permission states

Optimize flows for minimal friction and clear decision points. Flag ambiguities or missing requirements as Open Questions.

### Phase 2: Wireframing & Layout

Structure first, visuals later. Output low-fidelity layout descriptions.

- **Mobile-first** — describe layouts starting from smallest viewport, then define how they adapt (mobile → tablet → desktop).
- **Regions** — use named regions: header, main, sidebar, footer, modals, drawers, overlays.
- **Hierarchy** — specify visual weight: primary, secondary, tertiary actions. One primary action per screen.
- **Reusable components** — identify shared patterns (forms, cards, nav, filters, tables) and where they repeat.
- **Annotations** — note scroll behavior, sticky elements, overflow handling.

Use ASCII block diagrams or structured text — no color, no styling at this phase.

### Phase 3: Visual Aesthetics

Apply systematic visual design. When refining existing UI or generating new components:

- **Typography** — establish a clear type scale (3–5 sizes). Consistent line heights. Limit text styles per breakpoint to 2–3.
- **Color palette** — define a small, cohesive set: primary, accent, background, surface, subtle border, semantic states (success, warning, error, info). Avoid generic defaults.
- **Spacing system** — use a consistent scale (4/8/12/16/24/32/48). Avoid both cramped and overly airy layouts. Tighten where possible.
- **Component conventions** — buttons, inputs, and cards share border-radius, shadow depth, and padding logic.
- **Responsiveness** — provide CSS or utility classes for mobile-first breakpoints.

Output: design rationale (1–2 paragraphs), token-style spec (colors, typography, spacing values), and updated code.

### Phase 4: Component System

Extract a minimal, reusable component set from the current screens.

For each component (Button, Input, Card, Modal, Navbar, etc.):
- **Purpose and usage context**
- **Variants** — size (sm/md/lg), state (default/hover/active/disabled/loading), hierarchy (primary/secondary/ghost)
- **Visual spec** — padding, radius, border, icon placement, min-width/height
- **Code-friendly naming** — consistent with both design tools and frontend code

Flag inconsistencies or redundancies in existing UI. Propose consolidations.

### Phase 5: UX Copy & Microcopy

Write interface text that reduces friction and increases clarity.

- **Titles/subtitles** — state the user's benefit, not the system's action.
- **Button labels** — describe the outcome ("Save changes", "Send invite"), not the mechanism ("Submit", "Process").
- **Helper text** — for form fields, explain what's expected and why.
- **Error messages** — say what went wrong, what to do about it, and avoid blame ("We couldn't find that" not "Invalid input").
- **Empty states** — guide the user toward the first action.
- **Tooltips** — for complex concepts only; don't tooltip obvious things.

Tone: concise, friendly, professional. Plain language over jargon.

### Phase 6: Interaction & Motion

Specify interactive behavior for developer implementation.

- **States** — hover, focus, press, disabled for every interactive element.
- **Transitions** — page transitions, modal open/close, accordion expand, tab switch. Specify duration (150–300ms) and easing.
- **Micro-interactions** — success confirmations, progress indicators, skeleton loaders, optimistic updates.
- **Mobile patterns** — swipe actions, pull-to-refresh, bottom sheets, gesture hints.
- **Accessibility** — keyboard navigation order, focus trapping in modals, `prefers-reduced-motion` fallbacks, ARIA states.

Format as implementable specs, not abstract descriptions.

## Quality Checks

### Heuristic Review Criteria

When reviewing UI/UX work (yours or existing), evaluate against:

| Criterion | What to check |
|-----------|---------------|
| Hierarchy & affordances | Can users tell what's clickable, what's primary, what's secondary? |
| Mental model match | Does the UI work how users expect based on conventions? |
| Feedback & error handling | Does every action produce visible feedback? Are errors recoverable? |
| Consistency | Same patterns for same actions throughout? |
| Task efficiency | Can key tasks be completed in minimal steps? |
| Mobile usability | Touch targets ≥44px, no hover-dependent features, readable without zoom? |

Rate issues by severity: **low** (cosmetic), **medium** (confusing but workaround exists), **high** (blocks task completion or causes errors). Propose a concrete fix for each.

### Scope Discipline

- Don't redesign what isn't broken — focus changes on the requested area.
- If adjacent UI has issues, note them in the REQ's review section but don't fix unless asked.
- A styling request doesn't need an IA overhaul. A new feature may need IA + wireframe + visuals.

## Design Artifacts

Not every ui-design request produces code. Wireframe specs, IA documents, visual design specs, and interaction specs are valid deliverables. Place them as project files outside `do-work/` (e.g., `docs/design/REQ-NNN-wireframe.md`) so they appear in the Implementation Summary and satisfy the pipeline's file-change validation. Design artifacts are project deliverables — the same rules apply: list them in `Files changed`, mark as `(new)` or `(modified)`, and commit them.

## Implementation Patterns

### CSS & Styling

- Prefer the project's existing styling approach (Tailwind, CSS modules, styled-components, etc.) — don't introduce a new system.
- Use CSS custom properties for design tokens when the project supports them.
- Avoid magic numbers — reference the spacing/color system.
- Test at 320px, 768px, and 1280px minimum.

### Accessibility Baseline

Every UI change must meet:
- Semantic HTML (`button` for buttons, `nav` for navigation, `main` for primary content)
- Color contrast ≥ 4.5:1 for text, ≥ 3:1 for large text and UI elements
- Visible focus indicators on all interactive elements
- Screen reader compatibility (labels, alt text, ARIA where needed)
- Keyboard operability for all interactive flows

### Handoff Notes

When implementation is complete, include in the Implementation Summary:
- Which design phases were applied and key decisions made
- Token values used (colors, spacing, typography) for design system alignment
- Any interactions specified but not yet implemented (future work)
- Screenshots or before/after descriptions where useful
