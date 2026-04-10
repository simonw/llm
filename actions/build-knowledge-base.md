# Build Knowledge Base Action

> **Part of the do-work skill.** Implements the LLM Knowledge Base pattern — a persistent, compounding Markdown wiki compiled from raw source documents.

The core idea: instead of re-deriving knowledge from scratch on every query (RAG), the LLM incrementally compiles raw sources into a structured, interlinked Markdown wiki. `raw/` is the source code, the LLM is the compiler, the wiki is the executable.

## Sub-Commands

The `bkb` command accepts a sub-command as its first argument. If no sub-command is given, show the help menu.

| Sub-command | What it does | Crew |
|---|---|---|
| `init [path]` | Initialize a new knowledge base at the given path (default: `./kb`) | Architect |
| `triage` | Sort inbox items into capture subdirectories, update the queue | Sorter |
| `ingest [target]` | Compile source(s) into wiki pages (all ready, specific file, or path) | Compiler → Connector → Reviewer |
| `query [question]` | Search the wiki and synthesize an answer | Seeker |
| `lint [scope]` | Health check — contradictions, orphans, broken links, stale claims | Librarian + Reviewer + Connector + Editor |
| `resolve` | Walk through open contradictions and resolve them one by one | Librarian + Reviewer |
| `close` | Finalize the daily log, verify indexes, report summary | Librarian + Editor |
| `rollup` | Monthly rollup — trends, volume stats, recommendations | Librarian + Editor |
| `status` | Show current KB stats — article counts, pending items, recent activity | (any) |
| `defrag` | Weekly structural maintenance — re-evaluate clusters, suggest merges/splits | Architect + Connector + Editor |
| `garden` | Topic cluster and relationship hygiene — balance, orphans, reciprocity | Connector + Librarian |
| `crew [action]` | Manage custom agents — create, list, edit, remove | Architect |
| (none) | Show help menu | (any) |

### Agent Dispatch

Before executing a sub-command, read the relevant agent file(s) from `<kb>/agents/` listed in the **Crew** column above. Adopt the agent's focus and standards for the duration of that operation. When multiple agents are listed:

- **Arrow (`→`)** means sequential handoff — the first agent completes its work, then the next picks up. Example: during `ingest`, the Compiler creates pages, then the Connector adds cross-references, then the Reviewer audits confidence.
- **Plus (`+`)** means concurrent concerns — all agents' standards apply simultaneously. Example: during `lint`, the Librarian checks structural health while the Reviewer checks confidence accuracy, the Connector checks relationships, and the Editor checks readability.

**If `<kb>/agents/` does not exist**: skip agent dispatch entirely for that invocation. For `init`, the agents are created in Step 4 — no dispatch is needed beforehand. For other sub-commands on a legacy KB (created before v0.46.0), proceed without agent files and note in output: "No agents/ directory found — run `bkb init` on an existing KB to add the agent crew (non-destructive, preserves existing data)."

---

## Locating the Knowledge Base

Before executing any sub-command (except `init`), find the KB root:

1. Check if `$ARGUMENTS` includes an explicit `--kb <path>` flag — use that path.
2. Look for a `kb/` directory in the current working directory.
3. Look for a `knowledge-base/` directory in the current working directory.
4. Search parent directories (up to 3 levels) for a directory containing both `raw/` and `wiki/` subdirectories.
5. If not found, tell the user: "No knowledge base found. Run `do work bkb init` to create one."

---

## Sub-Command: `init [path]`

Create the full KB directory structure at the specified path (default: `./kb`).

### Pre-flight Check

Before creating anything, check if the target path already contains a KB (has both `raw/` and `wiki/` subdirectories):

- **If KB exists**: Stop and report: "Knowledge base already exists at `<path>/` (N articles, M topic clusters). To repair a broken structure, run `do work bkb init <path> --fill-gaps`."
- **If `--fill-gaps` flag is present**: Only create directories and seed files that don't already exist. Never overwrite existing files. Report what was created vs. what was skipped. This is the migration path for legacy KBs — e.g., a KB created before v0.46.0 will gain the `agents/` directory and all 8 built-in agent files without disturbing existing content.
- **If no KB exists**: Proceed with full initialization.

### Step 1: Create the Raw Pipeline

```
<path>/
├── raw/
│   ├── inbox/                      # Zero-friction drop zone
│   ├── capture/                    # Type-sorted staging
│   │   ├── web/
│   │   ├── papers/
│   │   ├── repos/
│   │   ├── images/
│   │   ├── notes/
│   │   ├── audio/
│   │   └── video/
│   ├── processed/                  # Ingested sources, organized by date (YYYY-MM-DD/)
│   └── _inbox_queue.md             # LLM work list
```

### Step 2: Create the Wiki Structure

```
<path>/
├── wiki/
│   ├── _master_index.md            # Top-level nav (~80 lines max)
│   ├── topics/                     # Second-level indexes
│   ├── concepts/                   # Concept articles
│   ├── entities/                   # Person/org/product articles
│   ├── sources/                    # Source summaries
│   ├── comparisons/                # Filed query outputs
│   ├── daily/                      # Daily changelog
│   ├── monthly/                    # Monthly rollup + trends
│   ├── log.md                      # Append-only timeline
│   ├── overview.md                 # High-level synthesis
│   └── agent.md                    # Retrieval agent — learns query patterns
├── agents/                         # Crew — role definitions for each KB operation
│   ├── architect.md                #   Structure, schema, init
│   ├── sorter.md                   #   Inbox triage → capture
│   ├── compiler.md                 #   Ingest sources → wiki pages
│   ├── seeker.md                   #   Query, retrieval, synthesis
│   ├── connector.md                #   Cross-references, typed relationships
│   ├── librarian.md                #   Lint, resolve, rollup, maintenance
│   ├── reviewer.md                 #   QA — confidence, source verification
│   └── editor.md                   #   Wiki readability, navigation quality
```

### Step 3: Create Seed Files

**`raw/_inbox_queue.md`:**

```markdown
# Inbox Queue

Items pending triage. Updated automatically during triage.

| # | File | Source Type | Status |
|---|---|---|---|
```

**`raw/processed/_manifest.md`:**

```markdown
# Processing Manifest

| File | Date Processed | Processed Path | Wiki Articles Produced | Status |
|---|---|---|---|---|
```

**`wiki/_master_index.md`:**

```markdown
# Master Index

Last updated: {today} | Total articles: 0 | Topic clusters: 0

## Topic Clusters

(none yet — run `do work bkb ingest` to add your first source)

## Recent Activity

- {today}: Knowledge base initialized
```

**`wiki/log.md`:**

```markdown
# Activity Log

## [{today}] init | Knowledge base created

Structure initialized. Ready for first source.
```

**`wiki/overview.md`:**

```markdown
# Knowledge Base Overview

This knowledge base was initialized on {today}. No sources have been ingested yet.

Add sources to `raw/inbox/` and run `do work bkb triage` followed by `do work bkb ingest` to begin building.
```

**`wiki/agent.md`:**

```markdown
# Retrieval Agent

Learned patterns from past queries. Read this file FIRST during `bkb query` to prioritize which topic clusters and articles to check.

## Hot Topics

(none yet — patterns emerge after 3+ queries)

## Query Log

| Date | Query | Topics Checked | Articles Used | Useful? |
|---|---|---|---|---|
```

### Step 4: Create the Agent Crew

Create these 8 files in `<path>/agents/`. Each defines a role the LLM adopts when performing that operation. Read the relevant agent file before executing each sub-command.

**`agents/architect.md`:**

```markdown
# Architect

You are the Architect. You own the KB's structure and schema.

## Focus
- Directory layout and naming conventions
- Schema enforcement (CLAUDE.md rules)
- Index hierarchy (master → topic → article)
- Init, fill-gaps, and structural repair

## When active
- `bkb init` — you design and create the full structure
- `bkb lint` — you verify index integrity and schema compliance
- `bkb defrag` — you evaluate and reshape cluster boundaries
- `bkb crew` — you guide custom agent creation and validate definitions

## Standards
- Master index stays under 80 lines
- Topic indexes stay under 60 lines; split when a cluster exceeds 40 articles
- Every article in exactly one topic index
- Every topic index in the master index
- The KB schema file (`<kb>/CLAUDE.md`) is the single source of truth for conventions
```

**`agents/sorter.md`:**

```markdown
# Sorter

You are the Sorter. You classify and route incoming files.

## Focus
- File type detection by extension and content
- Inbox → capture routing
- Queue management (_inbox_queue.md)
- Filename collision handling

## When active
- `bkb triage` — you own the entire triage pass

## Standards
- Classify by extension first, content second
- .md files: check for URL in frontmatter (web) vs. personal notes
- Handle collisions with HHMMSS- prefix
- Append-only to _inbox_queue.md — only add files moved in this pass
- Unknown types stay in inbox with a flag, never silently dropped
```

**`agents/compiler.md`:**

```markdown
# Compiler

You are the Compiler. You transform raw sources into wiki knowledge.

## Focus
- Reading and understanding source material
- Creating source summaries, concept pages, entity pages
- Duplicate detection (exact → merge, near → cross-link)
- Per-file processing with independent fault tolerance

## When active
- `bkb ingest` — you own the source-to-wiki compilation (including enhanced transcript handling for audio/video)

## Standards
- Every page gets YAML frontmatter with all required fields
- Sources field always uses raw/processed/ paths (final location)
- New pages default to confidence: medium
- Process each file independently — if file 4 fails, files 1-3 are done
- Move source to processed/ immediately after successful compilation
- Non-text sources: images get LLM vision description, audio/video need transcripts
```

**`agents/seeker.md`:**

```markdown
# Seeker

You are the Seeker. You find and synthesize knowledge from the wiki.

## Focus
- Reading the retrieval agent (wiki/agent.md) for query prioritization
- Two-hop navigation: master index → topic index → articles
- Answer synthesis with [[wiki-link]] citations
- Three-tier query routing (Synthesize / Record / Skip)

## When active
- `bkb query` — you own search and synthesis

## Standards
- Always read wiki/agent.md first — check hot topics before scanning cold
- Cite sources with [[wiki-links]], never make unsupported claims
- Synthesize tier: answer connects 2+ sources → file as comparison page
- Record tier: substantive single-source answer → log but don't file
- Skip tier: simple lookup → return only, no logging
- Update wiki/agent.md query log after every query
```

**`agents/connector.md`:**

```markdown
# Connector

You are the Connector. You discover and maintain relationships between pages.

## Focus
- Typed relationships (extends, contradicts, evidence-for, complements, supersedes, depends-on)
- Bidirectional link maintenance
- Contradiction detection and flagging
- Relationship density management (8-per-page cap)

## When active
- `bkb ingest` — you add cross-references after the Compiler creates pages
- `bkb lint` — you verify relationship validity and density
- `bkb defrag` — you assess how relationships span across cluster boundaries
- `bkb garden` — you audit relationship types, reciprocity, and density

## Standards
- Every relationship is bidirectional — if A extends B, B gets a link back to A
- Choose the most specific relationship type; default to complements when unsure
- contradicts auto-flags in the daily log and lowers confidence to low
- When a page hits 8 relationships, drop the weakest (lowest-confidence target or oldest complements)
- Every rel: value must be one of the six allowed types
```

**`agents/librarian.md`:**

```markdown
# Librarian

You are the Librarian. You maintain wiki health and track history.

## Focus
- Lint checks (contradictions, orphans, broken links, stale claims, index integrity)
- Contradiction resolution workflow
- Monthly rollups with trend analysis
- Queue archival and manifest maintenance
- Daily/monthly log management

## When active
- `bkb lint` — you run all health checks
- `bkb resolve` — you walk through contradictions
- `bkb rollup` — you produce the monthly summary
- `bkb close` — you finalize the day
- `bkb garden` — you audit topic cluster balance and identify orphaned indexes

## Standards
- Lint findings go to wiki/daily/{today}.md AND wiki/log.md
- Contradictions use the [RESOLVED] convention for tracking
- Rollups archive queue entries older than 30 days
- Never auto-fix without reporting what changed
```

**`agents/reviewer.md`:**

```markdown
# Reviewer

You are the Reviewer. You are the QA gate — you verify claims, challenge confidence levels, and flag gaps.

## Focus
- Confidence auditing: are pages rated correctly (high/medium/low)?
- Source verification: do sources actually support the claims made?
- Coverage gaps: concepts mentioned 3+ times without their own page
- Stale claims: content superseded by newer sources
- Untested assertions: claims with no source trail

## When active
- `bkb lint` — you check confidence accuracy and source backing
- `bkb ingest` — you challenge the Compiler's confidence assignments
- `bkb resolve` — you evaluate which side of a contradiction has better evidence

## Standards
- A page rated high must have a primary source or 2+ agreeing sources — flag if not
- A page rated medium with 2+ confirming sources should be upgraded to high — flag if not
- Claims that appear in wiki pages but trace to no raw/processed/ source are untested — flag them
- Never silently accept confidence: high without checking the sources list
```

**`agents/editor.md`:**

```markdown
# Editor

You are the Editor. You ensure the wiki is clear, navigable, and well-structured for human readers.

## Focus
- Article readability: clear titles, logical section flow, concise language
- Navigation quality: can a human find what they need in 2 hops?
- Consistency: similar topics use similar page structures
- Frontmatter hygiene: titles match content, topic_cluster assignments make sense
- Overview freshness: wiki/overview.md reflects the current state

## When active
- `bkb close` — you review today's new/updated pages for readability
- `bkb lint` — you check for thin articles, unclear titles, and navigation dead ends
- `bkb rollup` — you refresh the overview and flag readability issues
- `bkb defrag` — you ensure restructured clusters have clear, intuitive names

## Standards
- Articles should be scannable — headers, short paragraphs, no walls of text
- Titles should be specific nouns or noun phrases, not sentences
- Every concept page should be understandable without reading its sources
- Topic cluster names should be intuitive — a new reader should guess what's inside
- Flag pages that are stubs (under 3 substantive sentences) for expansion
```

### Step 5: Create the Schema File

Create `<path>/CLAUDE.md` with the KB schema (conventions, frontmatter format, workflow triggers). Use the schema content from the "Schema File" section below.

### Step 6: Initialize Git

If the KB path is not already inside a git repository, run `git init` in the KB root.

### Step 7: Report

```
Knowledge base initialized at <path>/

  raw/       Source pipeline (inbox → capture → processed)
  wiki/      LLM-maintained wiki (master index → topic indexes → articles)
  agents/    Crew of 8 — role definitions for each KB operation

Next steps:
  Drop files into <path>/raw/inbox/
  do work bkb triage         Sort inbox items
  do work bkb ingest         Compile sources into wiki
```

---

## Sub-Command: `triage`

Sort new items from `raw/inbox/` into `raw/capture/` subdirectories by type.

### Steps

1. **Scan** `raw/inbox/` for all files (non-recursive — files only, not subdirectories).
2. **Classify** each file by extension and content:
   - `.pdf` → `capture/papers/`
   - `.md` from web clippers (has URL in frontmatter or content) → `capture/web/`
   - `.md` that looks like personal notes → `capture/notes/`
   - `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp` → `capture/images/`
   - `.mp3`, `.wav`, `.m4a`, `.ogg` → `capture/audio/`
   - `.mp4`, `.webm`, `.mkv`, transcript files → `capture/video/`
   - Code files, `README.md` from repos → `capture/repos/`
   - Unknown → leave in inbox, flag for user
3. **Move** each classified file to its target directory. If a file with the same name already exists in the target (from a previous triage that hasn't been ingested yet), prefix with the current time: `HHMMSS-filename.ext`.
4. **Update** `raw/_inbox_queue.md` — append only the files moved from inbox in **this** triage pass, marked as "ready". Do NOT re-scan all of `capture/`; the queue is an append-only ledger of triage batches. For each entry, include:
   - `topic_hint` — scan the file's first 500 characters against existing topic clusters in `wiki/topics/` and note the best match (or "new" if no match).
   - `priority` — set to "high" if the file references an open contradiction or an active query topic from `wiki/agent.md` Hot Topics; otherwise "normal".

   Queue entry format: `- [ ] filename.ext | type: <type> | topic_hint: <topic> | priority: <normal|high> | ready`
5. **Report**: Items triaged, items skipped (with reasons), items ready for ingestion.

If inbox is empty, say so and suggest adding files.

---

## Sub-Command: `ingest [target]`

Compile source documents into wiki pages. This is the core operation.

### Target Resolution

- `ingest` (no target) → process all "ready" items in `raw/_inbox_queue.md`
- `ingest <filename>` → process a specific file from `raw/capture/`
- `ingest <path>` → process a specific file by path (can be outside `capture/` — e.g., a file the user hasn't triaged yet)

### Steps

1. **Read** the target source file(s) from `raw/capture/` (or the specified path).
2. **Handle non-text sources**:
   - **Images** (`.png`, `.jpg`, `.svg`, etc.): Use LLM vision to describe the image. Generate a summary from the visual content. If a companion `.md` file exists alongside (e.g., `diagram.png` + `diagram.md`), use both. Both files are treated as a unit — move both to `processed/` together in step 6.
   - **Audio** (`.mp3`, `.wav`, etc.): Check for a companion transcript file (e.g., `podcast.mp3` + `podcast.txt` or `podcast.md`). If found, process the transcript using enhanced transcript handling (see below). Both files move to `processed/` together. If no transcript exists, skip the file and flag it: "Audio file needs a transcript — add a .txt or .md alongside it."
   - **Video** (`.mp4`, `.webm`, etc.): Same as audio — look for a companion transcript. Process using enhanced transcript handling. Both move together. Skip and flag if none found.
   - **Text files** (`.md`, `.pdf`, `.txt`, code files): Process normally.
3. **For each source**, discuss key takeaways briefly, then:
   a. **Duplicate check** — before creating any wiki page, search for existing pages covering the same topic:
      - **Exact duplicate** (same source re-ingested, or same content from a different URL): update the existing page — add the new file to its `sources:` frontmatter list, refresh any stale claims, note "additional source" in the daily log. Do NOT create a second page.
      - **Near-duplicate** (same topic, different angle or data): create a separate page but add bidirectional `[[wiki-links]]` in both pages' `related:` frontmatter. Note the relationship in the daily log (e.g., "New page X complements existing page Y").
      - **No duplicate**: proceed normally.
   b. **Create or update** a summary page in `wiki/sources/` with YAML frontmatter.
   c. **Create or update** relevant concept pages in `wiki/concepts/`.
   d. **Create or update** relevant entity pages in `wiki/entities/`.
   e. **Check for contradictions** with existing wiki content. Flag any found.
   f. **Update cross-references** — add `[[wiki-links]]` between related pages.
   g. **Confidence transitions** — check whether this new source changes confidence for existing pages:
      - If a new source corroborates an existing `medium` page's claims, upgrade that page to `confidence: high`.
      - If a new source contradicts an existing `high` page, downgrade to `confidence: low` and flag the contradiction.
      - Note all confidence changes in the daily log.
3b. **Batch cross-referencing** (when ingesting multiple sources): After completing step 3 for all sources in the batch, cross-reference claims across the batch before proceeding to step 4:
   - **Agreements**: If 2+ sources in the same batch make the same claim, set the resulting page to `confidence: high`.
   - **Contradictions**: If sources in the batch conflict with each other, flag them immediately — do not defer to lint.
   - **Entity unification**: Merge entity references that appear across multiple sources in the batch into a single canonical entity page.
4. **Update indexes**:
   a. Determine which topic cluster(s) the new content belongs to.
   b. Create new topic index (`wiki/topics/_index_[topic].md`) if needed.
   c. Update existing topic index(es) with new article entries.
   d. Update `wiki/_master_index.md` — article counts, topic list, recent activity.
5. **Write daily log**: Create or append to `wiki/daily/{today}.md` listing everything ingested, created, updated, and any contradictions flagged.
6. **Move to processed and mark done** (per-file): After each file completes steps 3–5 successfully, immediately move it to `raw/processed/{today}/` (create the date directory if needed) from wherever it currently lives (`raw/capture/`, `raw/inbox/`, or an external path). If the file was in the queue, mark its row as "done" in `raw/_inbox_queue.md`; if it was ingested directly by path (bypassing triage), add a "done" entry to the queue for traceability. If a file with the same name already exists in the target directory, prefix with the current time: `HHMMSS-filename.ext`. Update `raw/processed/_manifest.md` with the original path, processed path, and wiki articles produced. **This is per-file, not per-batch** — if file 4 of 5 fails, files 1–3 are already safely processed and marked done.
7. **Append to activity log**: Add entry to `wiki/log.md`.
8. **Report**: Sources processed, pages created/updated, contradictions found, skipped files (with reasons), index changes.

### Page Conventions

Every wiki page MUST have YAML frontmatter:

```yaml
---
title: Page Title
type: concept | entity | source-summary | comparison | daily-log | monthly-rollup
topic_cluster: [which topic index this belongs to]
sources: [list of raw/processed/ paths — the file's final stable location]
related:
  - page: other-page-name
    rel: extends | contradicts | evidence-for | complements | supersedes | depends-on
created: YYYY-MM-DD
updated: YYYY-MM-DD
confidence: high | medium | low
---
```

> **`sources:` always uses the `raw/processed/` path** (e.g., `raw/processed/2026-04-05/moe-paper.pdf`). This is the file's stable final location. Never use `capture/` paths — those are transient.

### Typed Relationships

The `related:` field uses typed entries instead of flat lists. Each entry has a `page` (the `[[wiki-link]]` target) and a `rel` (the relationship type):

| Relationship | Meaning | Example |
|---|---|---|
| `extends` | Builds on or expands the target page's ideas | A deep-dive article extends a concept overview |
| `contradicts` | Makes claims that conflict with the target | Two papers with opposing conclusions |
| `evidence-for` | Provides supporting evidence for the target's claims | An experiment result supporting a theory |
| `complements` | Covers related but distinct ground | Two frameworks for different aspects of the same problem |
| `supersedes` | Replaces or updates the target (target may be stale) | A newer version of a spec replacing the old one |
| `depends-on` | Requires understanding of the target as a prerequisite | An advanced concept depending on a foundational one |

**Rules:**
- Relationships are always **bidirectional** — if A `extends` B, then B gets a `related:` entry pointing to A (the inverse relationship is inferred: B is `extended-by` A, but store it as `complements` for simplicity).
- When creating or updating cross-references during ingest, choose the most specific relationship type. Default to `complements` when unsure.
- The `contradicts` relationship automatically flags a contradiction in the daily log and lowers the `confidence:` of the less-sourced page to `low`.
- Maximum 8 typed relationships per page. When adding a 9th, drop the weakest connection (lowest confidence target, or oldest `complements` link).

### Confidence Rules

Set `confidence:` in frontmatter based on source quality:

- **high** — backed by a primary source (peer-reviewed paper, official documentation, authoritative reference) OR corroborated by 2+ independent sources that agree.
- **medium** — single secondary source (blog post, talk transcript, tutorial) with no corroboration yet. This is the default for new pages.
- **low** — no direct source (inferred or synthesized by the LLM), OR an active contradiction is flagged against this page.

Confidence can change: medium → high when a second source confirms the claim. High → low when a contradiction is flagged. Low → medium/high when the contradiction is resolved.

### Enhanced Transcript Handling

When the Compiler ingests audio or video with a companion transcript, apply these additional steps beyond standard text ingestion:

1. **Detect multi-speaker content**: Scan the transcript for speaker labels (e.g., "Speaker 1:", "John:", "[Host]", timestamps with speaker changes). If multiple speakers are detected:
   a. Attribute quotes, claims, and opinions to their specific speakers.
   b. In the source summary, note which claims belong to which speaker rather than presenting everything as a single-voice narrative.

2. **Extract structured content**: Identify and extract:
   a. **Key decisions** — statements where speakers agree on a course of action or reach a conclusion.
   b. **Action items** — commitments to do something, assignments, deadlines mentioned.
   c. **Open questions** — questions raised but not answered, disagreements left unresolved, items explicitly deferred.

3. **Segment by topic**: For transcripts longer than ~2000 words, identify major topic shifts and segment the transcript. Each segment gets its own section in the source summary. If a segment covers a topic that warrants its own concept page, create one.

4. **Create entity pages for speakers**: For each identified speaker who does not already have an entity page in `wiki/entities/`:
   a. Create a new entity page with `type: entity` and available information (name, role/title if mentioned, organization if mentioned).
   b. Set `confidence: low` (since speaker identity comes from a single transcript).
   c. Link the entity page to the source summary.
   d. If the speaker already has an entity page, add the new source to their `sources:` list and update any new information mentioned.

5. **Structure the source summary**: When a transcript is detected, the source summary in `wiki/sources/` should use this format instead of the default:

   ```markdown
   ## Overview
   Brief description of the audio/video content, date, context, and duration if known.

   ## Speakers
   - **Speaker Name** — role/title if known. [[entity-page-link]]
   - ...

   ## Key Points
   - Point 1 (attributed to Speaker if applicable)
   - Point 2
   - ...

   ## Decisions
   - Decision 1 — agreed by [speakers]
   - ... (or "No explicit decisions recorded" if none)

   ## Action Items
   - [ ] Action item 1 — assigned to [speaker] (deadline if mentioned)
   - ... (or "No action items identified" if none)

   ## Open Questions
   - Question 1 — raised by [speaker], not resolved
   - ... (or "No open questions" if none)
   ```

This enhanced handling applies ONLY to audio/video transcripts. Standard text sources (articles, papers, notes) continue using the default source summary format.

### Index Size Rules

- `_master_index.md` must stay under 80 lines.
- Each topic index must stay under 60 lines.
- When a topic index exceeds 40 articles, split it and update `_master_index.md`.
- Every wiki article must appear in exactly one topic index.
- Every topic index must appear in `_master_index.md`.

---

## Sub-Command: `query [question]`

Search the wiki to answer a question. Uses the retrieval agent for prioritization and three-tier routing for output.

### Steps

1. **Read `wiki/agent.md`** first. Check the Hot Topics section for topic clusters and articles that have been useful for similar past queries. Use these to prioritize which indexes and articles to read — check high-frequency topics first.
2. **Read** `wiki/_master_index.md` to identify relevant topic cluster(s). If the agent suggested clusters, start there; otherwise scan the full index.
3. **Read** the relevant topic index(es) from `wiki/topics/`.
4. **Read** the specific articles identified as relevant (2–5 articles typically).
5. **Follow relationships** — for each article read in step 4, check its `related:` frontmatter and follow relevant typed links up to 2 hops deep:
   - If article A `extends` B and B is relevant to the question → read B for fuller context.
   - If article A `contradicts` B → read B and present both sides in the answer.
   - If article A `depends-on` B → read B first for prerequisite context.
   - Stop at 2 hops from any initial article to avoid scope creep.
6. **Synthesize** an answer using `[[wiki-link]]` citations to wiki pages.
7. **Classify the response** using three-tier routing:
   - **Synthesize** — the answer connects 2+ sources or produces a novel comparison. File it as a new wiki page in `wiki/comparisons/` with proper frontmatter. Update the relevant topic index, `_master_index.md`, and append to `wiki/log.md`.
   - **Record** — the answer is substantive but doesn't produce new cross-source connections. Return the answer to the user but do NOT create a wiki page. Append a brief entry to `wiki/log.md` noting the query and result.
   - **Skip** — the answer is a simple lookup or factual retrieval from a single page. Return the answer only. No log entry needed.
8. **Update `wiki/agent.md`**: Append a row to the Query Log table with today's date, the question asked, which topic clusters were checked, which articles were actually used in the answer, and whether the result was useful (yes/partial/no). After every 5th query, regenerate the Hot Topics section: scan the Query Log for topic clusters and articles that appear most frequently with "yes" usefulness, and list the top 5–10 as prioritized entries.

If the wiki has no content on the topic, say so and suggest sources to ingest.

---

## Sub-Command: `lint [scope]`

Health check the wiki for consistency and accuracy.

### Scope

- `lint` (no scope) → quick lint (changed pages since last lint)
- `lint [topic]` → full check of one topic cluster
- `lint full` → cross-cluster structural integrity check
- `lint all` → complete re-verification (quarterly cadence)

### Checks

1. **Contradictions** — pages that make conflicting claims about the same thing.
2. **Orphan pages** — wiki pages with no inbound `[[wiki-links]]`.
3. **Missing pages** — concepts mentioned 3+ times across pages without their own page.
4. **Stale claims** — content superseded by newer sources (check `updated` dates).
5. **Index integrity**:
   - Every wiki article appears in exactly one topic index.
   - Every topic index appears in `_master_index.md`.
   - Article counts in indexes match actual file counts.
   - No topic index exceeds the split threshold (40 articles).
6. **Broken links** — `[[wiki-links]]` pointing to non-existent pages.
7. **Daily log coverage** — daily logs exist for every day that had ingestion activity.
8. **Frontmatter completeness** — all required fields present in every wiki page.
9. **Relationship density** — pages with more than 8 `related:` entries (cap exceeded).
10. **Relationship validity** — every `rel:` value is one of the six allowed types; every `page:` target exists.
11. **Agent staleness** — `wiki/agent.md` Query Log has entries but Hot Topics haven't been regenerated in 10+ queries.
12. **Confidence audit** — pages where confidence level doesn't match their source evidence: a page with 2+ corroborating sources still at `medium` (should be `high`), or a page at `high` with only one secondary source (should be `medium`).

### Report

Write findings to `wiki/daily/{today}.md` and print a summary:

```
Lint results (scope: [scope]):
  Contradictions: N
  Orphan pages: N
  Missing pages suggested: N
  Stale claims: N
  Index issues: N
  Broken links: N
```

Suggest specific fixes for each finding.

Append a lint entry to `wiki/log.md` using the format `## [{today}] lint | <scope>` with a summary of findings. This allows `status` to derive the last-lint date by scanning `log.md` for the most recent lint entry.

---

## Sub-Command: `resolve`

Walk through open contradictions and resolve them interactively.

### Steps

1. **Find open contradictions**: Scan `wiki/daily/` logs and `wiki/log.md` for entries containing "contradiction" or "conflicting". A contradiction is **open** if no subsequent log entry marks it as `[RESOLVED]`. Convention: resolution log entries use the format `[RESOLVED] contradiction: <description>` so they can be matched against the original flag.
2. **Cluster related contradictions**: Group open contradictions into connected clusters using the wiki's typed relationships. If page A contradicts B, and B has an `evidence-for` link to C, and C contradicts D — then {A, B, C, D} form one cluster. Resolving them together prevents cascading inconsistencies (e.g., resolving A vs B in isolation may conflict with the later resolution of C vs D). Present each cluster as a unit; standalone contradictions (no relationship connections to other contradictions) are clusters of one.
3. **For each cluster**, present it to the user:
   - Show the two (or more) conflicting claims with their source pages and original raw sources.
   - Propose a resolution: which claim is more recent, better sourced, or more authoritative?
   - Ask the user to confirm, adjust, or skip.
4. **Apply resolution**: Update the wiki page(s) — correct the stale/wrong claim, add a note about what changed and why, update the `confidence:` frontmatter if needed. After resolving a cluster, propagate confidence changes: a page that was `low` solely because of a now-resolved contradiction may qualify for `medium` or `high`.
5. **Log resolution**: Append to `wiki/log.md` and `wiki/daily/{today}.md`. **Emit one `[RESOLVED] contradiction: <description>` entry per original contradiction in the cluster** — each original flag from step 1 must have its own matching resolved marker, or it will be re-detected as open on future runs. After the per-contradiction markers, include a summary of which pages were updated and how.
6. **Report**: Contradictions resolved (by cluster), contradictions skipped, contradictions remaining.

If no open contradictions are found, say so.

---

## Sub-Command: `close`

Finalize the day's work.

### Steps

1. **Finalize daily log**: Ensure `wiki/daily/{today}.md` has all changes from today.
2. **Verify indexes**: Check that `_master_index.md` article counts are accurate.
3. **Refresh overview**: Re-read the current state of the wiki (master index, recent daily logs, topic clusters) and regenerate `wiki/overview.md` with an up-to-date high-level synthesis of what the knowledge base covers.
4. **Report**:
   ```
   Day closed ({today}):
     Articles created: N
     Articles updated: N
     Sources ingested: N
     Contradictions pending: N
   ```
5. **Suggest git commit** (do not auto-commit): If there are uncommitted changes in the KB directory, print: "Uncommitted KB changes — run `do work commit` or `git add . && git commit` when ready."

---

## Sub-Command: `rollup`

Generate the monthly summary. Run on the 1st of each month or on demand.

### Steps

1. **Read** all `wiki/daily/` entries for the target month (default: previous month).
2. **Create** `wiki/monthly/{YYYY-MM}.md` with:
   - **Volume stats**: sources ingested, articles created/updated, contradictions found/resolved.
   - **Theme evolution**: which topics grew, which went stale, emerging patterns.
   - **Integrity summary**: lint results, confidence changes.
   - **Recommendations**: topic splits needed, new clusters suggested, gap areas.
3. **Archive queue**: Move all "done" rows older than 30 days from `raw/_inbox_queue.md` to `raw/_inbox_queue_archive.md` (create if needed). This keeps the active queue small while preserving the full ledger. The manifest in `raw/processed/_manifest.md` remains the authoritative permanent record.
4. **Evaluate** whether any topic index needs splitting (threshold: 80+ articles).
5. **Update** `wiki/_master_index.md` with monthly activity line.
6. **Append** to `wiki/log.md`.

---

## Sub-Command: `status`

Quick snapshot of the KB state.

### Steps

1. **Read** `wiki/_master_index.md` for article counts and topic clusters.
2. **Count** files in `raw/inbox/` (pending triage) and items marked "ready" in `raw/_inbox_queue.md` (pending ingestion).
3. **Read** the most recent `wiki/daily/` entry for last activity date.
4. **Scan** `wiki/log.md` for the most recent `lint |`, `defrag |`, and `garden |` entries to get their last-run dates.
5. **Count** custom agents: `.md` files in `<kb>/agents/` that contain `## Custom Agent`.
6. **Report**:
   ```
   Knowledge Base Status:
     Location: <path>
     Total articles: N across M topic clusters
     Inbox: N items pending triage
     Queue: N items ready for ingestion
     Last activity: YYYY-MM-DD
     Last lint: YYYY-MM-DD (or "never")
     Last defrag: YYYY-MM-DD (or "never")
     Last garden: YYYY-MM-DD (or "never")
     Agents: 8 built-in + N custom
   ```
7. **Staleness warnings**: If defrag hasn't run in 14+ days (or never), append a warning: `⚠ Defrag is overdue — last run was N days ago (recommend weekly).` Same for garden at 14+ days.

---

## Sub-Command: `defrag`

Weekly structural maintenance. Unlike lint (which finds problems), defrag proactively improves the wiki's structure as it grows. You can pass lint with flying colors and still benefit from defrag.

### Steps

1. **Read current structure**: Read `wiki/_master_index.md` and all `wiki/topics/_index_*.md` files. Count articles per cluster. Read a sample of articles from each cluster (first 3) to understand cluster boundaries.

2. **Evaluate cluster boundaries**: For each topic cluster:
   a. **Overcrowded clusters** (40+ articles): Analyze article titles and `topic_cluster` assignments. Propose splits — identify natural sub-groups that could become their own cluster.
   b. **Underweight clusters** (fewer than 5 articles): Check if articles would fit better in a neighboring cluster. Propose merges with the most closely related cluster.
   c. **Overlapping clusters**: Compare cluster scopes. If two clusters cover substantially similar ground, propose merging them.

3. **Check concept promotion**: Scan for concepts mentioned across 5+ articles in different clusters that do NOT have their own topic cluster. These are candidates for promotion to a new cluster.

4. **Check cluster demotion**: Identify topic clusters where no new articles have been added in 30+ days AND the cluster has fewer than 10 articles. Flag as candidates for absorption into a parent or sibling cluster.

5. **Refresh master index organization**: Re-order `_master_index.md` entries by cluster size (largest first) or by thematic grouping if logical groups emerge. Ensure article counts are accurate.

6. **Apply approved changes**: For each proposed change, describe it and apply:
   - **Merge**: Move all articles to the target cluster's index, delete the empty index, update all affected articles' `topic_cluster` frontmatter, update `_master_index.md`.
   - **Split**: Create the new topic index, move articles, update frontmatter, update master index.
   - **Promote**: Create a new `wiki/topics/_index_[topic].md`, reclassify articles, update frontmatter, update master index.
   - **Demote**: Merge the shrinking cluster into its best-fit neighbor.

7. **Generate defrag report**: Create `wiki/daily/{today}-defrag.md` with:
   - Cluster inventory (before and after)
   - Merges performed
   - Splits performed
   - Promotions and demotions
   - Master index changes
   - Recommendations for next defrag

8. **Log**: Append to `wiki/log.md` using the format `## [{today}] defrag | <summary of structural changes>`.

### When to Run

Weekly, or after a large batch ingest (20+ sources). The `status` command should note when defrag hasn't run in 14+ days.

---

## Sub-Command: `garden`

Audit the wiki's metadata layer — topic clusters, typed relationships, and cross-references. Focuses on the "connective tissue" rather than the content itself.

### Steps

1. **Topic cluster balance**: Read all `wiki/topics/_index_*.md` files. Report the distribution of articles across clusters. Flag clusters with fewer than 3 articles (underused) and clusters with more than 50 articles (overcrowded). Calculate the standard deviation of cluster sizes — a high value suggests imbalance.

2. **Relationship type distribution**: Scan all wiki pages' `related:` frontmatter. Tally how many of each relationship type are used across the entire wiki:
   - `extends`, `contradicts`, `evidence-for`, `complements`, `supersedes`, `depends-on`
   - Flag if any single type exceeds 60% of all relationships (likely overuse).
   - Flag if `evidence-for` and `contradicts` together are below 10% (the wiki may be under-analyzed — these are the most valuable relationship types).
   - Suggest specific pages where a `complements` link could be upgraded to a more precise type.

3. **Orphaned topic indexes**: Find topic indexes in `wiki/topics/` that exist as files but have zero articles pointing to them (no wiki page has that `topic_cluster` value in frontmatter). Suggest removal or re-population.

4. **Relationship reciprocity**: For every `related:` entry on every page, verify the target page has a reciprocal `related:` entry pointing back. Report all one-way links. Offer to add the missing back-links.

5. **Reclassification suggestions**: For each article, compare its content (title, related pages, relationship targets) against its assigned `topic_cluster`. If the majority of an article's relationships point to a different cluster, suggest reclassifying it.

6. **Generate garden report**: Write findings to `wiki/daily/{today}.md` and print a summary:
   ```
   Garden results:
     Cluster balance: N clusters (min: X, max: Y, avg: Z articles)
     Relationship distribution: {type: count, ...}
     Orphaned topic indexes: N
     One-way links (missing reciprocals): N
     Reclassification candidates: N
   ```

7. **Apply fixes**: For reciprocity violations, add the missing back-links automatically. For other findings, list them as recommendations (do not auto-apply reclassifications or index removals without user confirmation).

8. **Log**: Append to `wiki/log.md` using the format `## [{today}] garden | <summary of findings>`.

---

## Sub-Command: `crew [action]`

Manage the agent crew. Built-in agents (8) are read-only. Custom agents extend the crew with domain-specific roles.

### Actions

- `crew` or `crew list` — list all agents
- `crew create` — guided interview to define a new custom agent
- `crew edit <name>` — modify an existing custom agent
- `crew remove <name>` — remove a custom agent

### Sub-Action: `crew list`

1. **Read** all `.md` files in `<kb>/agents/`.
2. **Classify** each as built-in (one of the 8 original names: architect, sorter, compiler, seeker, connector, librarian, reviewer, editor) or custom.
3. **Display** a table:
   ```
   Agent Crew:
     # | Agent      | Type     | Role                              | Active during
     1 | Architect  | built-in | Structure, schema, init           | init, lint, defrag, crew
     2 | Sorter     | built-in | Inbox triage, file classification | triage
     ...
     9 | Taxonomist | custom   | Domain-specific classification    | ingest, garden
   ```

### Sub-Action: `crew create`

Guided interview to build a new agent file. Ask the user for:

1. **Name** — a single word, lowercase, no spaces. Must not collide with built-in names. File will be `<kb>/agents/<name>.md`.
2. **Role** — one-sentence description of what this agent does.
3. **Focus** — 3–5 bullet points describing the agent's area of expertise.
4. **When active** — which sub-commands this agent participates in, and whether it joins as a sequential step (arrow) or concurrent concern (plus). Example: "ingest (after Reviewer)" or "lint (concurrent)".
5. **Standards** — 3–5 rules this agent enforces.

Create the agent file using the same format as built-in agents, with an additional marker section:

```markdown
# {Name}

You are the {Name}. {Role}

## Focus
- {focus bullet 1}
- ...

## When active
- `bkb {command}` — {description}
- ...

## Standards
- {standard 1}
- ...

## Custom Agent
Created: {today}
```

After creating, confirm: "Agent '{name}' created. It will be active during: {commands}."

### Sub-Action: `crew edit <name>`

1. **Validate**: Check that `<name>.md` exists in `<kb>/agents/` and is a custom agent (has `## Custom Agent` section). Refuse to edit built-in agents — suggest creating a custom agent that supplements the built-in one instead.
2. **Show** the current agent definition.
3. **Ask** what the user wants to change (focus, when active, standards, or full rewrite).
4. **Update** the file. Set `Updated: {today}` in the `## Custom Agent` section.

### Sub-Action: `crew remove <name>`

1. **Validate**: Check that `<name>.md` exists and is a custom agent. Refuse to remove built-in agents: "Cannot remove built-in agent '{name}'. Built-in agents are part of the core BKB system."
2. **Confirm** with the user: "Remove custom agent '{name}'? This cannot be undone."
3. **Delete** the file from `<kb>/agents/`.
4. **Log**: Append to `wiki/log.md`: `## [{today}] crew remove | Removed custom agent: {name}`.

### Custom Agent Dispatch

Before executing any sub-command, scan ALL `.md` files in `<kb>/agents/` — not just the built-in crew listed in the Sub-Commands table. Custom agents activate based on their `## When active` section. If a custom agent lists the current sub-command, include it alongside the standard crew using the notation specified (arrow for sequential, plus for concurrent). If `<kb>/agents/` does not exist, skip custom agent scanning (see the guard in Agent Dispatch above).

---

## Help Menu

When invoked with no sub-command or with `help`:

```
do work bkb — LLM Knowledge Base builder

  Setup:
    do work bkb init              Initialize a new knowledge base in ./kb
    do work bkb init ~/research   Initialize at a custom path

  Daily workflow:
    do work bkb triage            Sort inbox items into capture directories
    do work bkb ingest            Compile all ready sources into wiki
    do work bkb query [question]  Search the wiki and synthesize an answer
    do work bkb close             Finalize today's daily log

  Maintenance:
    do work bkb lint              Quick health check (recent changes)
    do work bkb lint full         Full cross-cluster integrity check
    do work bkb resolve           Walk through and resolve contradictions
    do work bkb defrag            Weekly structural maintenance (merges, splits)
    do work bkb garden            Topic cluster and relationship hygiene
    do work bkb rollup            Monthly summary and trend analysis
    do work bkb status            Show KB stats and pending items

  Crew:
    do work bkb crew              List all agents (built-in + custom)
    do work bkb crew create       Define a new custom agent
    do work bkb crew edit <name>  Modify a custom agent
    do work bkb crew remove <name> Remove a custom agent

  Typical flow:
    1. Drop files into kb/raw/inbox/
    2. do work bkb triage
    3. do work bkb ingest
    4. do work bkb query "what are the tradeoffs of X vs Y?"
    5. do work bkb close
    Weekly: do work bkb defrag && do work bkb garden
```

---

## Schema File Content

When `init` creates `<path>/CLAUDE.md`, use this content:

```markdown
# LLM Knowledge Base Schema

## Project Structure
- `raw/` — source documents with lifecycle pipeline. NEVER modify originals.
- `raw/inbox/` — zero-friction drop zone. Sort into capture/ before processing.
- `raw/capture/` — type-sorted staging area.
- `raw/processed/YYYY-MM-DD/` — ingested sources, moved here after successful compilation.
- `raw/_inbox_queue.md` — append-only triage ledger. Only updated with files moved in the current triage pass.
- `wiki/` — LLM-generated wiki. You own this entirely.
- `wiki/_master_index.md` — top-level catalog. Read FIRST on every query.
- `wiki/topics/_index_[topic].md` — second-level indexes by topic cluster.
- `wiki/daily/YYYY-MM-DD.md` — daily changelog.
- `wiki/monthly/YYYY-MM.md` — monthly rollup and trends.
- `wiki/log.md` — append-only activity log.
- `wiki/agent.md` — retrieval agent. Learns query patterns to prioritize future lookups.

## Retrieval Agent
- `wiki/agent.md` tracks query history and hot topics.
- Read FIRST during `bkb query` to prioritize topic clusters.
- Hot Topics regenerated every 5 queries from the Query Log.
- Bounded to ~150 lines. Prune oldest log entries when exceeded.

## Page Conventions
Every wiki page MUST have YAML frontmatter:

    ---
    title: Page Title
    type: concept | entity | source-summary | comparison | daily-log | monthly-rollup
    topic_cluster: [which topic index this belongs to]
    sources: [list of raw/processed/ paths — stable final location]
    related:
      - page: other-page-name
        rel: extends | contradicts | evidence-for | complements | supersedes | depends-on
    created: YYYY-MM-DD
    updated: YYYY-MM-DD
    confidence: high | medium | low
    ---

## Typed Relationships
- `extends` — builds on target's ideas
- `contradicts` — conflicting claims (auto-flags contradiction)
- `evidence-for` — supporting data for target's claims
- `complements` — related but distinct ground
- `supersedes` — replaces/updates the target
- `depends-on` — requires target as prerequisite
- Max 8 relationships per page; drop weakest when adding a 9th

## Confidence Rules
- **high**: primary source (paper, official docs) OR 2+ independent sources agree
- **medium**: single secondary source (blog, tutorial). Default for new pages.
- **low**: no direct source, or active contradiction flagged
- Transitions: medium → high (corroborated), high → low (contradiction), low → medium/high (resolved)

## Non-Text Sources
- Images: use LLM vision to describe. Companion .md used if present. Both files move together.
- Audio/Video: require a companion transcript (.txt or .md). Skip and flag if missing.

## Contradiction Tracking
- Flag format in logs: `contradiction: <description>`
- Resolution format: `[RESOLVED] contradiction: <description>`
- A contradiction is open if no `[RESOLVED]` entry matches the original flag.

## Index Rules
- _master_index.md: max 80 lines, one line per topic cluster
- Topic indexes: max 60 lines, one line per article in the cluster
- Split threshold: 40 articles per topic index
- Every article in exactly one topic index
- Every topic index listed in _master_index.md

## Crew (Agent Dispatch)
- `agents/` — 8 built-in role definitions + custom agents, read before each sub-command (skipped if directory absent — see Agent Dispatch guard)
- **init**: Architect | **triage**: Sorter | **ingest**: Compiler → Connector → Reviewer
- **query**: Seeker | **lint**: Librarian + Reviewer + Connector + Editor
- **resolve**: Librarian + Reviewer | **close**: Librarian + Editor | **rollup**: Librarian + Editor
- **defrag**: Architect + Connector + Editor | **garden**: Connector + Librarian
- **crew**: Architect
- Arrow (→) = sequential handoff. Plus (+) = concurrent standards.
- Custom agents (files with `## Custom Agent` section) activate based on their `## When active` section.

## Custom Agents
- Custom agent files live in `agents/` alongside built-ins.
- Custom agents have a `## Custom Agent` section with Created/Updated dates.
- Built-in agents (8) are never modified. Custom agents extend the crew.
- Custom agents specify which sub-commands they activate during.

## Transcript Handling
- Audio/video transcripts get enhanced processing: speaker detection, decisions, action items, open questions.
- Source summaries for transcripts use the structured format: Overview, Speakers, Key Points, Decisions, Action Items, Open Questions.
- Entity pages created for identified speakers (confidence: low).

## Workflows
- **triage**: Sort inbox → capture, append only new items to _inbox_queue.md
- **ingest**: Read source → duplicate check → create/update wiki pages (enhanced transcript handling for audio/video) → update indexes → write daily log → move source to processed/{today}/ → update manifest → update queue
- **query**: Read agent.md → master index → topic index → articles → synthesize → route (Synthesize/Record/Skip) → update agent
- **lint**: Check contradictions, orphans, missing pages, stale claims, index integrity, broken links, relationship density/validity, agent staleness
- **resolve**: Walk through open contradictions, propose and apply resolutions with user confirmation
- **close**: Finalize daily log, verify index counts, refresh overview.md, suggest git commit
- **rollup**: Monthly summary with volume, themes, integrity, recommendations
- **defrag**: Read structure → evaluate cluster boundaries → check promotions/demotions → refresh master index → apply changes → generate report
- **garden**: Cluster balance → relationship distribution → orphaned indexes → reciprocity check → reclassification suggestions → apply reciprocity fixes
- **crew**: list/create/edit/remove custom agents in agents/
```

---

## Next Steps (shown after each sub-command)

**After init:**
```
Next steps:
  Drop files into <path>/raw/inbox/
  do work bkb triage            Sort inbox items
  do work bkb status            Check KB state
```

**After triage:**
```
Next steps:
  do work bkb ingest            Compile ready sources into wiki
  do work bkb ingest <file>     Ingest a specific source
```

**After ingest:**
```
Next steps:
  do work bkb query [question]  Ask the wiki a question
  do work bkb lint              Health check after ingestion
  do work bkb close             Finalize the day
```

**After query:**
```
Next steps:
  do work bkb ingest            Add more sources
  do work bkb lint              Health check
```

**After lint:**
```
Next steps:
  do work bkb resolve           Resolve flagged contradictions
  do work bkb defrag            Optimize structure (weekly)
  do work bkb garden            Audit relationships and clusters
  do work bkb ingest            Address gaps with new sources
  do work bkb close             Finalize the day
```

**After resolve:**
```
Next steps:
  do work bkb lint              Verify fixes
  do work bkb close             Finalize the day
```

**After close:**
```
Next steps:
  do work bkb rollup            Generate monthly summary (if end of month)
  do work bkb defrag            Weekly structural maintenance
  do work bkb status            Review KB state
```

**After rollup:**
```
Next steps:
  do work bkb lint full         Full integrity check
  do work bkb status            Review KB state
```

**After defrag:**
```
Next steps:
  do work bkb lint              Verify structural integrity after changes
  do work bkb garden            Check relationship hygiene
  do work bkb close             Finalize the day
```

**After garden:**
```
Next steps:
  do work bkb defrag            Apply structural changes if needed
  do work bkb resolve           Resolve any flagged issues
  do work bkb close             Finalize the day
```

**After crew (any action):**
```
Next steps:
  do work bkb crew              Review the full agent roster
  do work bkb status            Check KB state
```
