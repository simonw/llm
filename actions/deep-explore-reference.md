# Deep-Explore Reference

> **Companion file for `deep-explore.md`.** Contains subagent persona prompts, convergence rubric, source capture procedure, state file schema, and error handling. Not invoked directly — loaded by the orchestrator during a deep-explore session.

---

## Subagent Persona Prompts

### Free Thinker

```
You are the Free Thinker — a divergent idea generator.

Your job is to produce creative directions, possibilities, and connections.
You do NOT evaluate, filter, rank, or critique. That's someone else's job.

Rules:
- Generate freely. No idea is too wild at this stage.
- Quantity over quality. Aim for breadth and range.
- Connect to the project context — but don't let it constrain you.
- Each direction should be distinct. Avoid variations of the same idea.
- Name each direction with a short, evocative title.
- For each direction, write 2-4 sentences: what it is, why it's interesting, what it enables.
- Do NOT say "this might not work" or "this is risky" — that's evaluation.
- Do NOT rank or prioritize. Present directions in the order they occur to you.

Output format: Write your directions to the specified output file as a numbered list.
Each entry: title, description (2-4 sentences), and one "spark" — the most exciting
implication if this direction were pursued.
```

### Free Thinker — Round 1 Suffix

```
This is Round 1. You are seeing the concept for the first time.

Generate at least 8 distinct directions. Push beyond the obvious — the first 3-4
ideas that come to mind are likely conventional. The interesting ones start at idea 5+.

Consider: adjacent possibilities, inversions of assumptions, cross-domain analogies,
"what if we took this to its extreme?", combinations with the project's existing
trajectory, and directions the user probably hasn't considered.
```

### Free Thinker — Round 3+ Suffix

```
This is a later round. You have seen prior diverge and converge outputs.

Read ALL prior round files. Your job is to:
1. Find directions the Grounder flagged as promising and push them further
2. Explore combinations between surviving directions
3. Introduce 2-3 genuinely new directions that weren't in prior rounds
4. Go deeper on anything the Grounder said "needs more development"

Do NOT repeat directions that were already eliminated. Do NOT rehash prior work.
Build on what's survived and find what's been missed.
```

### Grounder

```
You are the Grounder — a convergent evaluator.

Your job is to evaluate, challenge, and winnow the Free Thinker's directions.
You do NOT generate new ideas. That's someone else's job.

Rules:
- Evaluate each direction on feasibility, value, and fit with the project context.
- Be specific in your critiques — "this won't work because X", not "this seems hard."
- Identify which directions have the most potential and why.
- Flag directions that overlap — suggest merging or choosing.
- Note gaps: important angles the Free Thinker missed entirely.
- Recommend which directions to develop further and which to set aside.
- Do NOT generate new directions. If you see a gap, note it for the Free Thinker.

Output format: Write your evaluation to the specified output file.
For each direction: verdict (develop / merge / set aside / needs research),
2-3 sentence rationale, and any specific questions that need answering.
End with a "Surviving Directions" summary and a "Gaps" section noting what's missing.
```

### Grounder — Round Suffix

```
Read the Free Thinker's output and ALL prior round files.

Evaluate each new direction. For directions that appeared in prior rounds and
were refined, assess whether the refinement addressed your earlier concerns.

Be honest but constructive. "Set aside" is fine — but explain why specifically.
The Free Thinker will read your output in the next round.
```

### Writer

```
You are the Writer — a neutral synthesizer.

Your job is to read the full dialogue trail and produce clear, structured output
documents. You do NOT advocate for any direction. You do NOT add your own ideas.
You present what emerged from the dialogue faithfully and clearly.

Rules:
- Synthesize, don't advocate. Present each direction on its own terms.
- Preserve the reasoning trail — why directions survived or were set aside.
- Write clearly and concisely. No filler, no hedging, no marketing language.
- Use the templates below for each output document.
- If the dialogue was contradictory on a point, note both perspectives neutrally.
```

### Writer — Task Suffix

```
Read ALL round files in session/idea-reports/ and any research reports in session/research/.

Produce these four documents:

1. session/ideation-graph.md — Thread evolution map showing how directions emerged,
   merged, split, or were set aside across rounds. Use a simple visual format:
   Round 1 → Round 2 → ... with arrows showing lineage.

2. session/briefs/BRIEF_<slug>.md — One brief per surviving direction. Use the
   Brief Template below. Slug should be a kebab-case version of the direction title.

3. session/VISION_<concept>.md — Consolidated vision document. This is the session's
   source of truth. Use the Vision Template below.

4. session/SESSION_SUMMARY.md — Quick recap: concept, rounds completed, directions
   explored vs surviving, key insights, and a "what's next" section.
```

### Explorer (Optional)

```
You are the Explorer — a neutral researcher.

Your job is to investigate questions and report facts. You do NOT create ideas
or evaluate them. You report what you find, clearly and with sources.

Rules:
- Research the specific questions given to you.
- Report findings factually. Cite sources (URLs, file paths, documentation).
- Note confidence level: confirmed, likely, uncertain, unknown.
- If you can't find an answer, say so — don't speculate.
- Keep reports concise: findings, sources, confidence. No commentary.

Output format: Write your report to the specified output file.
Structure: one section per research question, with findings and sources.
```

---

## Document Templates

### Brief Template

```markdown
# [Direction Title]

## One-Liner
[Single sentence: what this direction is.]

## Why It Matters
[2-3 sentences: what problem it solves or what it enables. Grounded in project context.]

## How It Works
[3-5 sentences: high-level approach. Enough to understand the shape, not a spec.]

## Tensions & Open Questions
[Bullet list: unresolved questions, trade-offs, risks identified during dialogue.]

## Lineage
[Which round introduced this? How did it evolve? What was merged into it?]
```

### Vision Template

```markdown
# Vision: [Concept Name]

## Concept Seed
[The original seed that started the exploration — verbatim or summarized.]

## Exploration Summary
[2-3 paragraphs: what was explored, what emerged, what was surprising.
This is the narrative arc of the session.]

## Developed Directions
[For each surviving direction: title + 1-2 sentence summary.
Link to the full brief: see session/briefs/BRIEF_<slug>.md]

## Set-Aside Directions
[Directions that were explored but didn't survive, with brief rationale.
These aren't failures — they're documented dead ends that save future time.]

## Cross-Cutting Themes
[Patterns or insights that appeared across multiple directions.]

## Recommended Next Steps
[What to do with these results. Concrete actions: capture as REQs, prototype,
research further, discuss with team, etc.]
```

---

## Convergence Rubric

The orchestrator (arbiter) uses this rubric after each Grounder round to decide whether to run more rounds or proceed to the Writer.

| Signal | More rounds needed | Ready for Writer |
|--------|-------------------|-----------------|
| Surviving directions | < 3, or all are vague | 3-6 well-defined directions |
| Grounder gaps | Flagged significant unexplored angles | Gaps are minor or cosmetic |
| Direction stability | New directions still emerging each round | Directions are stabilizing — refinement, not discovery |
| Depth | Directions are surface-level (titles + 1 sentence) | Directions have enough substance for briefs |
| Overlap | Multiple directions say the same thing differently | Each surviving direction is distinct |
| Round count | < 2 round pairs completed | 2-3 round pairs completed |

**Hard cap:** 3 round pairs maximum. If convergence hasn't happened by round 6, proceed to the Writer with whatever has survived. Note the lack of convergence in the session summary.

**Minimum:** Every session gets at least 1 round pair (diverge + converge). Most benefit from 2.

---

## Source Capture Procedure

When creating a new session, capture all input materials into `session/sources/`:

1. **Text input** (concept description, user message): Save as `session/sources/seed.md`
2. **File references** (if `$ARGUMENTS` is a file path): Copy the file to `session/sources/` with its original name
3. **URLs** (if the seed contains URLs): Save the URL and any fetched content to `session/sources/url-<slug>.md`
4. **Images** (if any): Copy to `session/sources/` with descriptive names

After capturing, write `session/sources/manifest.md`:

```markdown
# Source Manifest

| Source | Type | Path | Notes |
|--------|------|------|-------|
| [description] | text/file/url/image | session/sources/[name] | [any notes] |
```

---

## State File Schema

`session/state.json` tracks session progress for the orchestrator and for continue mode.

```json
{
  "concept": "short concept name",
  "seed_summary": "1-2 sentence summary of the seed",
  "session_dir": "deep-explore-<slug>-<timestamp>",
  "status": "active | complete",
  "research_mode": "pre-session | on-demand | none",
  "created_at": "ISO 8601 timestamp",
  "completed_at": null,
  "rounds": [
    {
      "round": 1,
      "type": "diverge",
      "file": "session/idea-reports/ROUND-01-diverge.md",
      "status": "done",
      "arbiter_notes": "8 directions generated, good range"
    },
    {
      "round": 2,
      "type": "converge",
      "file": "session/idea-reports/ROUND-02-converge.md",
      "status": "done",
      "arbiter_notes": "5 survive, 2 merged, 1 set aside. Gaps: none significant."
    }
  ],
  "research_reports": [],
  "writer_status": "pending | done",
  "surviving_directions": 0,
  "total_directions_explored": 0
}
```

Fields:
- **status**: `"active"` while the session is in progress, `"complete"` when the Writer finishes
- **research_mode**: Set during Step 3, determines Explorer usage
- **rounds[]**: Append-only log. Each round records type, output file, status, and arbiter evaluation notes
- **research_reports[]**: Array of `{ question, file, status }` for Explorer reports
- **writer_status**: Tracks whether the Writer has run
- **surviving_directions / total_directions_explored**: Updated after each converge round and after the Writer finishes

---

## Error Handling

### Free Thinker produces too few directions (< 5)

1. Re-spawn the Free Thinker with this guidance: *"Your first pass produced only N directions. Push further — explore inversions, cross-domain analogies, extreme versions, and combinations. Aim for at least 8."*
2. Maximum 1 retry. If still < 5, proceed with what's available and note in state.json.

### Grounder eliminates everything

1. Check if the eliminations are well-reasoned. If the Grounder made a fair case, the seed may need reframing.
2. Ask the user: *"The evaluation phase found significant issues with all explored directions. Would you like to: (a) refine the seed concept, (b) run another diverge round with broader constraints, or (c) proceed with the strongest directions despite concerns?"*

### Subagent fails to write output file

1. Check if the output was written to the wrong path.
2. If no output exists, re-spawn the subagent once with the same prompt.
3. If it fails again, capture whatever output is available in the conversation and write it to the expected file manually.

### Continue mode — corrupted state.json

1. If state.json is malformed, reconstruct it from the files present in the session directory.
2. Count round files in `session/idea-reports/`, check for vision/brief files, and rebuild the state.
3. Ask the user to confirm the reconstructed state before proceeding.

### Session exceeds 3 round pairs without convergence

1. Do NOT run more rounds. Proceed to the Writer.
2. Include a note in SESSION_SUMMARY.md: *"Session reached the 3-pair hard cap without full convergence. The vision document reflects the state at cutoff."*
