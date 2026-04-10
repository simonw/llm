# UI Review

Read-only design audit that validates UI quality against structured best practices. Evaluates structure, aesthetics, accessibility, UX copy, and interaction patterns without modifying code.

## Scoping

Same as code-review — prime files, directories, or combined:

```
do work ui-review                          # interactive scope selection
do work ui-review src/components/          # validate a directory
do work ui-review prime-dashboard          # validate everything a prime file touches
do work design review src/pages/
```

## Review dimensions

### Structure & Information Architecture
Navigation patterns, edge cases (empty states, loading, errors), layout hierarchy, mobile-first approach.

### Visual Aesthetics
Typography scale, color palette usage, spacing consistency, component visual consistency, distinctiveness.

### Component System
Component inventory, variants, naming conventions, state coverage (default, hover, active, disabled, error, loading).

### UX Copy
Button labels, error messages, empty state messaging, tone consistency, clarity.

### Interaction & Accessibility
Focus management, keyboard operability, semantic HTML, ARIA attributes, color contrast, touch targets, motion preferences.

### Implementation Patterns
Styling approach consistency, design token usage, responsive breakpoints, CSS quality.

### Visual Verification (optional)
If Playwright CLI or Bowser skill is installed, renders pages to verify contrast, layout, and responsiveness visually.

## Finding severity

| Level | Meaning |
|-------|---------|
| **High** | Blocks task completion or fails accessibility standards |
| **Medium** | Confusing but workaround exists |
| **Low** | Cosmetic or minor polish |

## Guardrails

Includes anti-rationalization tables (guards against "the design looks fine to me" or "accessibility is someone else's job") and a verification checklist to ensure all review steps were attempted and severity counts match.

## Output

Structured markdown report organized by category with file:line references, severity levels, suggested fixes, top priorities, and acknowledged strengths.

## Usage

```
do work ui-review
do work ui-review src/components/
do work ui-review prime-dashboard
do work review ui
do work design review
do work validate ui
do work design audit
```
