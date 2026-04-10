# UI Review Action

> **Part of the do-work skill.** Validates UI quality against design best practices without making changes. Read-only audit that produces a structured findings report.

## Philosophy

This action is a **validation-only** pass. It does not modify code — it identifies issues and recommends what should be updated. Think of it as a design-aware code review: it reads the UI, evaluates it against a comprehensive design checklist, and reports findings with severity and concrete fix suggestions.

It combines two layers of design knowledge:

1. **`crew-members/ui-design.md`** — the structured 6-phase design workflow (IA, wireframing, visual aesthetics, component systems, UX copy, interaction & motion) plus quality checks, accessibility baseline, and implementation patterns.
2. **`frontend-design` skill** (if installed at `.claude/skills/frontend-design/SKILL.md`) — Anthropic's production-grade aesthetics guidance covering typography, color, motion, and backgrounds.

Together, these provide both the structural rigor of a design system review and the aesthetic eye of a visual design audit.

## Input

The user specifies what to review. Accepted formats:

- **File paths**: `do work ui-review src/components/Header.tsx`
- **Directory paths**: `do work ui-review src/pages/`
- **Prime file references**: `do work ui-review prime-dashboard`
- **Combined**: `do work ui-review prime-auth src/components/`
- **No arguments**: Interactive — list UI-relevant files and ask the user what to review

## Workflow

### Step 1: Resolve Scope

Parse the arguments to determine which files to review.

**Prime file references**: Read the referenced prime file(s) and collect all files they reference.

**Directory paths**: Glob for UI-relevant source files — `*.tsx`, `*.jsx`, `*.vue`, `*.svelte`, `*.html`, `*.css`, `*.scss`, `*.module.css`, `*.styled.*`. Skip `node_modules/`, `dist/`, `build/`, `.next/`, vendored files, and generated files.

**No arguments**: Look for UI-related files in the project. List candidate directories (e.g., `src/components/`, `src/pages/`, `app/`, `src/views/`) and ask the user which scope to review. If only one candidate, proceed with it.

Combine all resolved file paths into a single deduplicated list. This is the **review scope**.

### Step 2: Load Design Context

1. **Read `crew-members/ui-design.md`** from the skill root. This provides the 6-phase design checklist, heuristic review criteria, accessibility baseline, and implementation patterns.

2. **Check for `frontend-design` skill**: Look for `.claude/skills/frontend-design/SKILL.md`. If it exists, read it and incorporate its aesthetics criteria into the review. If not installed, note this in the report as a recommendation but proceed without it.

3. **Check for project design tokens**: Look for existing design system files — `tailwind.config.*`, `theme.*`, `tokens.*`, `design-system.*`, CSS custom properties files, or equivalent. These establish the project's design language and serve as the baseline for consistency checks.

4. **Check for browser/visual verification tools** (in this order):
   - **Playwright CLI (`playwright-cli`)**: Check if `playwright-cli` is available — run `playwright-cli --help 2>/dev/null` or check for it in `node_modules/.bin/`. This is the preferred tool for visual verification (Step 8.5). It's token-efficient, supports headed/headless modes, parallel sessions, and screenshots via simple CLI commands.
   - **Bowser skill**: Check if `.claude/skills/playwright-bowser/SKILL.md` exists from the project root. If available, use it — it wraps `playwright-cli` with session management and viewport configuration.
   - **Neither available**: Note in the report that visual verification was skipped. Recommend installing via do-work:
     ```
     do work install-bowser
     ```
     This installs both `playwright-cli` (global) and the Bowser skill (project-scoped) from https://github.com/disler/bowser. Playwright CLI enables rendered-page checks — screenshot comparison, actual color contrast measurement, responsive viewport testing, and accessibility audits — that static code analysis alone cannot provide.

5. **Read the scoped files**: Read all files in the review scope. For large scopes (>20 files), prioritize component files and page/view files over utility/helper files.

### Step 3: Structural & IA Review (Phase 1–2)

Evaluate the UI structure against Phase 1 and Phase 2 criteria from `crew-members/ui-design.md`:

- **Navigation & information hierarchy**: Is the navigation structure clear? Are content groups logical?
- **Screen completeness**: Are edge cases handled — empty states, error states, loading states, permission states?
- **Layout structure**: Are regions well-defined (header, main, sidebar, footer)? Is there a clear visual hierarchy with primary/secondary/tertiary actions?
- **Mobile-first approach**: Does the layout adapt from small to large viewports? Or is it desktop-only?
- **Reusable patterns**: Are shared UI patterns (forms, cards, tables, nav) extracted or duplicated?

### Step 4: Visual Aesthetics Review (Phase 3)

Evaluate against Phase 3 criteria from `crew-members/ui-design.md` and the `frontend-design` skill (if available):

- **Typography**: Is there a consistent type scale? Are there too many font sizes/weights/families? Generic defaults (Inter, Roboto, system-ui only) without intentional pairing?
- **Color palette**: Is the palette cohesive and intentional? Are semantic colors (success, warning, error, info) consistent? Any accessibility contrast issues?
- **Spacing system**: Is spacing consistent and systematic (multiples of 4/8)? Magic numbers? Cramped or overly airy areas?
- **Component visual consistency**: Do buttons, inputs, cards share border-radius, shadow, and padding logic?
- **Design distinctiveness**: Does the UI have a clear aesthetic identity, or does it fall into generic "AI slop" defaults (purple gradients, centered hero sections, generic card grids)?

### Step 5: Component System Review (Phase 4)

Evaluate against Phase 4 criteria:

- **Component inventory**: Are there components that serve the same purpose but look different?
- **Variant consistency**: Do components have consistent size/state/hierarchy variants?
- **Naming conventions**: Are component names code-friendly and consistent?
- **State coverage**: Do interactive components handle all states (default, hover, active, disabled, loading, error)?
- **Redundancy**: Are there components that should be consolidated?

### Step 6: UX Copy Review (Phase 5)

Evaluate against Phase 5 criteria:

- **Button labels**: Do they describe outcomes ("Save changes") or mechanisms ("Submit")?
- **Error messages**: Do they explain what happened, what to do, and avoid blame?
- **Empty states**: Do they guide the user toward a first action?
- **Helper text**: Do form fields explain what's expected?
- **Tone consistency**: Is the voice consistent throughout (concise, friendly, professional)?
- **Jargon**: Is there technical language where plain language would work?

### Step 7: Interaction & Accessibility Review (Phase 6)

Evaluate against Phase 6 criteria and the accessibility baseline:

- **Interactive states**: Do elements have hover, focus, press, disabled states?
- **Focus indicators**: Are focus styles visible on all interactive elements?
- **Keyboard operability**: Can all interactive flows be completed by keyboard?
- **Semantic HTML**: `button` for buttons, `nav` for navigation, `main` for primary content, proper heading hierarchy?
- **ARIA usage**: Are labels, alt text, and ARIA attributes present where needed? Are they correct (no redundant ARIA on semantic elements)?
- **Color contrast**: Text contrast >= 4.5:1, large text/UI elements >= 3:1?
- **Touch targets**: Are tap targets >= 44px on mobile?
- **Motion**: Are transitions reasonable (150–300ms)? Is `prefers-reduced-motion` respected?
- **Screen reader compatibility**: Would a screen reader user be able to navigate and use this UI?

#### Automated Accessibility Tooling

Before or alongside the manual checks above, check if the project has automated accessibility tooling configured. These catch issues systematically that manual review may miss:

| Indicator | Tool | What It Catches |
|-----------|------|-----------------|
| `eslint-plugin-jsx-a11y` in `package.json` or `.eslintrc` | eslint-plugin-jsx-a11y | Missing alt text, invalid ARIA, non-interactive element handlers, missing form labels |
| `@axe-core/react` or `react-axe` in dependencies | axe-core (runtime) | Contrast violations, missing landmarks, duplicate IDs, ARIA misuse — in the rendered DOM |
| `axe-core` in dev dependencies, `@axe-core/cli` | axe-core (CLI) | Same as above, runnable from terminal: `npx axe http://localhost:3000` |
| `pa11y` in dependencies or CI | Pa11y | WCAG 2.1 AA automated checks against rendered pages |

**If tools are configured:** Run them and include findings in the report. Tool-caught issues go in the Interaction & Accessibility table with a note that they were tool-detected.

**If no tools are configured:** Note this in the report as a recommendation. For projects with UI, `eslint-plugin-jsx-a11y` (static, zero-config with most ESLint setups) and `axe-core` (rendered DOM, catches contrast and landmark issues) cover the most ground with the least effort.

### Step 8: Implementation Patterns Review

Evaluate against the implementation patterns section:

- **Styling approach**: Does the code use the project's existing styling method, or does it introduce a conflicting system?
- **Design tokens**: Are values hardcoded (magic numbers) or referenced from a system (CSS custom properties, Tailwind config, theme object)?
- **Responsive breakpoints**: Is the UI tested/designed for at least 320px, 768px, and 1280px?
- **CSS quality**: Any `!important` overrides, deeply nested selectors, or inline styles that should be in stylesheets?

### Step 8.5: Visual Verification (if browser tools available)

If Playwright CLI or the Bowser skill was detected in Step 2.4, use it to validate the rendered UI. If neither is available, skip this step entirely — the code-level review (Steps 3–8) stands on its own.

**If the app can be started** (check for `dev`/`start` scripts in `package.json`, or a running dev server):

1. **Launch the app** if not already running. Use the project's dev server command (e.g., `npm run dev`, `yarn dev`).

2. **Screenshot at key breakpoints** — capture the scoped pages/components at three viewports. Derive a session name from the review scope (e.g., `ui-review-components`):

   ```bash
   # Mobile (320px)
   PLAYWRIGHT_MCP_VIEWPORT_SIZE=320x568 playwright-cli -s=ui-review-mobile open http://localhost:3000 --persistent --headless
   playwright-cli -s=ui-review-mobile screenshot --filename=ui-review-320.png
   playwright-cli -s=ui-review-mobile close

   # Tablet (768px)
   PLAYWRIGHT_MCP_VIEWPORT_SIZE=768x1024 playwright-cli -s=ui-review-tablet open http://localhost:3000 --persistent --headless
   playwright-cli -s=ui-review-tablet screenshot --filename=ui-review-768.png
   playwright-cli -s=ui-review-tablet close

   # Desktop (1280px)
   PLAYWRIGHT_MCP_VIEWPORT_SIZE=1280x800 playwright-cli -s=ui-review-desktop open http://localhost:3000 --persistent --headless
   playwright-cli -s=ui-review-desktop screenshot --filename=ui-review-1280.png
   playwright-cli -s=ui-review-desktop close
   ```

   If using the Bowser skill, follow the same session pattern — it wraps `playwright-cli` with the same commands.

3. **Accessibility audit** — use `playwright-cli` to run JavaScript-based accessibility checks on the rendered page:

   ```bash
   PLAYWRIGHT_MCP_VIEWPORT_SIZE=1280x800 playwright-cli -s=ui-review-a11y open http://localhost:3000 --persistent --headless
   # Inject and run axe-core if available, or use snapshot to inspect element structure
   playwright-cli -s=ui-review-a11y snapshot
   playwright-cli -s=ui-review-a11y close
   ```

   The snapshot output reveals the rendered element tree — check for missing labels, heading hierarchy, ARIA attributes, and interactive element roles. This catches issues that static code analysis misses.

4. **Visual checks on rendered output**:
   - Do elements overlap or overflow at any breakpoint?
   - Are fonts actually loading (not falling back to system fonts unexpectedly)?
   - Are images/icons rendering correctly?
   - Does the layout break at any viewport width?
   - Are interactive elements (dropdowns, modals, tooltips) positioned correctly?

5. **Add findings** from visual verification to the report under a new `### Visual Verification` category in Step 9. Include screenshot file paths as evidence where relevant.

6. **Clean up sessions** — always close all review sessions when done:
   ```bash
   playwright-cli close-all
   ```

**If the app cannot be started** (no dev server, build errors, missing dependencies):

Note in the report that visual verification was attempted but the app could not be started. Include the error. This is not a failure of the review — the code-level analysis is still complete.

### Step 9: Synthesize Report

Compile all findings into a structured markdown report. **Do not modify any files** — output the report only.

```markdown
# UI Review Report

**Scope**: [list of reviewed files/directories]
**Date**: [today]
**frontend-design skill**: [Installed / Not installed — recommend `do work install-ui-design`]
**Visual verification**: [Playwright CLI / Bowser skill / Skipped — recommend `do work install-bowser`]

## Summary

[2–3 sentence overview: overall UI quality, strongest areas, most pressing concerns.]

**Overall health**: [Excellent / Good / Needs Attention / Concerning]

## Findings by Category

### Structure & Information Architecture
| # | Finding | Severity | File:Line | Suggested Fix |
|---|---------|----------|-----------|---------------|
| 1 | ...     | high/medium/low | ... | ... |

### Visual Aesthetics
| # | Finding | Severity | File:Line | Suggested Fix |
|---|---------|----------|-----------|---------------|

### Component System
| # | Finding | Severity | File:Line | Suggested Fix |
|---|---------|----------|-----------|---------------|

### UX Copy
| # | Finding | Severity | File:Line | Suggested Fix |
|---|---------|----------|-----------|---------------|

### Interaction & Accessibility
| # | Finding | Severity | File:Line | Suggested Fix |
|---|---------|----------|-----------|---------------|

### Implementation Patterns
| # | Finding | Severity | File:Line | Suggested Fix |
|---|---------|----------|-----------|---------------|

### Visual Verification (if performed)
| # | Finding | Severity | Viewport/Context | Suggested Fix |
|---|---------|----------|------------------|---------------|

## Severity Summary

- **High**: [count] — blocks task completion, causes errors, or fails accessibility requirements
- **Medium**: [count] — confusing UX, inconsistency, or workaround exists
- **Low**: [count] — cosmetic, polish, or best-practice improvement

## Top Priorities

[Numbered list of the 3–5 most impactful things to fix first, in priority order. Each item should reference the finding number and explain why it matters.]

## Strengths

[2–3 things the UI does well — acknowledge good patterns so they're preserved.]
```

**Severity definitions** (from `crew-members/ui-design.md`):
- **High**: Blocks task completion, causes user errors, or fails accessibility requirements (WCAG AA)
- **Medium**: Confusing UX but workaround exists, inconsistency across screens, missing states
- **Low**: Cosmetic polish, best-practice improvement, nice-to-have

### Step 10 (Optional): Create Follow-up REQs

If the user wants to act on findings, offer to capture high and medium severity findings as REQs in the do-work queue:

> Want me to capture the high/medium findings as requests in the queue? I'll create one REQ per logical group of related findings.

If the user confirms:
- Group related findings into logical units (e.g., all accessibility issues in one REQ, all component inconsistencies in another)
- Create REQ files using the capture action's format with `domain: ui-design`
- Reference the review report findings by number in each REQ

If the user declines or doesn't respond, skip this step. The report stands on its own.

## Common Rationalizations

Guard against these when conducting the UI review:

| If you're thinking... | STOP. Instead... | Because... |
|---|---|---|
| "The design looks fine to me" | Evaluate against each phase checklist systematically | Subjective approval skips objective criteria |
| "Accessibility is someone else's job" | Check semantic HTML, contrast, focus indicators, keyboard nav | Accessibility is a baseline, not an add-on |
| "This component is similar enough to the design system" | Measure: exact padding, radius, color values against the tokens | "Similar enough" accumulates into visual inconsistency |
| "I can't check this without running the app" | The code-level review (Steps 3–8) catches most issues statically | Visual verification is additive, not a prerequisite |
| "No findings in this category" | Verify you checked all items in the category's checklist | An empty category should be earned, not assumed |

## Rules

- **Read-only**: Do not modify any source files. The entire action is observational.
- **Be specific**: Every finding must include a file path and line number (or range). Vague findings ("the spacing feels off") are not actionable.
- **Show both sides**: When flagging inconsistency, show both the pattern and the deviation.
- **Respect the project's design language**: If the project has an established design system, evaluate against it — don't impose external preferences.
- **Don't flag what tools catch**: If a linter or formatter would catch it, skip it. Focus on design-level issues that require human judgment.
- **Proportional depth**: A 3-file review gets a focused report. A 50-file review gets broader patterns, not 50x the findings.
- **Acknowledge strengths**: A report that's all negatives is demoralizing and incomplete. Note what works.
- **frontend-design skill is additive**: If not installed, still run the full review using `crew-members/ui-design.md`. The skill adds aesthetic depth but isn't required.
- **Playwright CLI / Bowser skill are additive**: If not available, the code-level review (Steps 3–8) is still comprehensive. Visual verification adds rendered-page evidence but is not a prerequisite. Always recommend `do work install-bowser` when missing — it's high-value and low-effort.

## Verification Checklist

Before finalizing the report, verify:

- [ ] Every finding has a file path and line number (or range)
- [ ] Both sides shown for every inconsistency finding (the pattern and the deviation)
- [ ] All review steps (Structure, Visual, Component, UX Copy, Interaction, Implementation, Visual Verification) were attempted or explicitly noted as skipped with reason
- [ ] Severity counts in the summary match actual findings in the tables
- [ ] At least 1 item in Strengths section (acknowledge what works)
- [ ] No findings that a configured linter/formatter would catch
