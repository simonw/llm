# Verify Requests Action

> **Part of the do-work skill.** Invoked when routing determines the user wants to verify the quality of captured requests. Evaluates REQ files against their originating User Request (UR) to find gaps.

A confidence evaluation system that compares extracted REQ files against the original user input to identify lost requirements, dropped UX details, missing intent signals, and incomplete coverage. This is **capture QA** — it checks whether requirements were extracted correctly, not whether the implementation is good.

## Philosophy

- **The original input is the source of truth** — the UR's input.md contains everything the user said
- **REQs should be lossless extractions** — every requirement in the input should appear in at least one REQ
- **Intent signals matter** — not just WHAT was requested, but HOW firmly and with what scope guidance
- **REQs are validated intent** — capture resolves ambiguities with the user present. Verify checks that this validation actually happened: are Open Questions resolved? Does the Validation field reflect user confirmation? A REQ marked "Inferred during capture" when the user was available is a missed opportunity.
- **Behavioral proof matters** — when a request is testable, the REQ should preserve the RED/GREEN proof target: how we know it fails now and what turns it GREEN later
- **Actionable output** — don't just report problems, offer to fix them

## When to Use

- After creating REQs from a complex request (to validate the extraction)
- When the user says "verify", "check", "evaluate", "review requests"
- Before starting `do work` processing, as a quality gate

If the user wants a post-implementation quality review of shipped code (not capture quality), route to **`review work`** instead.

## Workflow

### Step 1: Find the Target UR

1. **If user specifies a UR** (e.g., "verify UR-003"): Use that UR directly
2. **If user specifies a REQ** (e.g., "verify REQ-018"): Read the REQ's `user_request` field to find the UR
3. **If no target specified**: Find the most recent UR folder in `do-work/user-requests/` (highest UR number)

**Legacy support:** If the user points to a REQ with `context_ref` instead of `user_request`, read the referenced CONTEXT file from `do-work/assets/` and use its verbatim input as the source of truth.

### Step 2: Read the Original Input

1. Read `do-work/user-requests/UR-NNN/input.md`
2. Extract the full verbatim input section
3. Note the `requests` array to know which REQs to evaluate
4. Note any Batch Constraints section

### Step 3: Read All Related REQs

1. Find all REQ files listed in the UR's `requests` array
2. Check `do-work/`, `do-work/working/`, and `do-work/archive/` for each
3. Read the full content of each REQ file

### Step 4: Evaluate Each REQ

For each REQ, score it on these dimensions:

**Requirements Coverage (0-100%)**
- Does the REQ capture all requirements from the original input that apply to this feature?
- Are specific values, constraints, and conditions preserved?
- Are edge cases and error handling requirements included?

**UX/Interaction Details (0-100%)**
- Are interaction behaviors captured? (e.g., "auto-scroll to current file," "collapse on click")
- Are visual/layout requirements noted?
- Are state transitions described?

**Intent Signals (0-100%)**
- Does the Builder Guidance section (if applicable) accurately reflect the user's tone?
- Is the certainty level correct (exploratory vs firm)?
- Are scope cues preserved ("keep it simple," "don't over-build")?

**Internal Coherence (0-100%)**
- Does the REQ contradict itself? (e.g., "## What" says one thing, "## Detailed Requirements" says another)
- If the REQ has addendum sections, do they conflict with the original content?
- Are scope cues consistent? (e.g., "keep it simple" in Builder Guidance but 15 detailed requirements)
- Is the Red-Green Proof consistent with the What section?

**Red-Green Proof (0-100%)** — only for `tdd: true` or clearly behavioral requests
- Does the REQ capture a concrete RED prompt/case, repro, or example?
- Does it explain why that case is RED today?
- Does it state what observable outcome turns it GREEN?
- If capture-time validation was possible, does it reflect the user's confirmed or adjusted version?

**Batch Context (0-100%)** — only for multi-REQ batches
- Do cross-cutting constraints from the UR appear in this REQ's Constraints section?
- Are sequencing requirements noted?
- Are shared design principles captured?

### Step 5: Identify Gaps

For each gap found:
1. Quote the relevant section from the original input
2. Identify which REQ should contain it (or if a new REQ is needed)
3. Classify the severity:
   - **Important**: A firm requirement that was completely dropped or partially captured with significant loss
   - **Minor**: A clear detail that was summarized too aggressively or a soft preference that was missed
   - **Nit**: A passing mention or stylistic preference — won't affect the build
   - **Ambiguous**: The original input doesn't contain enough information to resolve this — neither the REQ nor the UR has a clear answer. This isn't a gap in the REQ; it's a gap in the original request that only the user can fill.

### Step 6: Generate Report

Output a confidence report in this format:

```
## Verification Report: UR-NNN

**Overall Confidence: [X]%**

### Per-REQ Scores

| REQ | Title | Coverage | UX Detail | Intent | Coherence | Red-Green | Batch | Overall |
|-----|-------|----------|-----------|--------|-----------|------------|-------|---------|
| REQ-018 | TOC Panel | 85% | 70% | 90% | 100% | 100% | 80% | 85% |
| REQ-019 | File Tree | 90% | 60% | 90% | 100% | N/A | 80% | 80% |

**Scoring:** Per-REQ Overall = average of applicable dimension scores (omit N/A dimensions from the denominator). Overall Confidence = average of per-REQ Overall scores.

### Gaps Found

**Important:**
- [None / list of dropped or significantly under-captured requirements with source quotes]

**Minor:**
- [List of over-summarized details or missed soft preferences]

**Nit:**
- [List of stylistic or trivial gaps]

**Ambiguous (needs client input):**
- [List of requirements where the original input is unclear — these become Open Questions on the REQ]

### Recommendations

1. [Specific fix: "Add 'auto-scroll to current file' to REQ-018 Detailed Requirements"]
2. [Specific fix: "Add batch constraint about stability-first sequencing to REQ-019"]
```

### Step 7: Offer Fixes

After presenting the report:

1. Ask the user if they want to apply the recommended fixes
2. If yes, update the REQ files directly:
   - **Important/Minor gaps**: Add missing requirements to the appropriate sections, add or update Builder Guidance sections, add batch constraints to Constraints sections, and add or tighten `## Red-Green Proof` when the request is testable
   - **Ambiguous gaps**: The user is here right now — **resolve them on the spot.** For each Ambiguous gap:
     1. Present the question with recommended choices using the ask tool if your environment provides one; otherwise use your environment's normal ask-user prompt/tool:
        ```
        [Question]
        Recommended: [best default based on context]
        Also: [alternative A], [alternative B]
        ```
     2. If the user answers → add the resolved question to the REQ's `## Open Questions` section as `- [x] [question] → [user's answer]`
     3. If the user defers ("let the builder decide") → add as `- [~] [question] → Builder decides`
     4. If the user can't answer now → add as unresolved `- [ ]` with choices. The builder will use best judgment when it picks up the REQ.
3. Re-score after fixes to confirm improvement (Resolved Ambiguous items that resulted in new requirements being added DO affect the re-score. Items left as `- [ ]` or `- [~]` don't.)

## Scoring Guidelines

**90-100%**: Excellent — all requirements captured with full detail. Ready to build.
**75-89%**: Good — minor gaps that probably won't affect implementation. Fix if convenient.
**50-74%**: Needs attention — important requirements or interaction details missing. Fix before building.
**Below 50%**: Significant gaps — major requirements dropped. REQ needs substantial rework.

## Legacy REQ Handling

For REQs created before the UR system:
- They won't have `user_request` in frontmatter
- They may reference `assets/CONTEXT-*.md` via `context_ref`
- They won't have a Builder Guidance section
- Score them the same way, but note that missing Builder Guidance is expected (not a gap) for legacy REQs
- If the user wants to verify legacy REQs and has the original CONTEXT file, use its verbatim input

## What NOT To Do

- Don't expand requirements beyond what the user said — you're checking coverage, not inventing new features
- Don't penalize REQs for missing details the user never mentioned
- Don't treat implementation details as gaps — those are for the builder to decide
- Don't ask the user to design test internals — ask for the observable failing case and GREEN outcome instead
- Don't classify something as Ambiguous when the answer is in the original input — that's an Important gap. Ambiguous means the *user's input itself* doesn't contain the answer.
- Don't block on verification — it's advisory, not a gate (unless the user wants it as a gate)
- Don't set `status: pending-answers` on REQs after verify — that status is for follow-ups from the work/review pipeline. Verify already tried to ask the user; any remaining `- [ ]` items stay on a `pending` REQ and the builder will use best judgment.
