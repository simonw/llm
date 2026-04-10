# Prime Action

> **Part of the do-work skill.** Invoked when routing determines the user wants to create or audit prime files. Prime files (`prime-*.md`) are AI context documents — semantic indexes that help an AI coder navigate a utility in minimum tokens.

## Sub-Commands

The `prime` command accepts a sub-command as its first argument. If no sub-command is given, show the help menu.

| Sub-command | What it does |
|---|---|
| `create <path>` | Generate a new prime file for a utility via interactive Q&A |
| `audit` | Read-only audit of all prime files — stale refs, missing primes, broken links |
| (none) | Show help menu |

---

## Help Menu (no sub-command)

When invoked with no sub-command (`do work prime`), show:

```
prime — manage AI context documents (prime files)

  do work prime create src/auth/    Generate a prime file via interactive Q&A
  do work prime audit               Audit all prime files for staleness and broken links
```

---

## Sub-Command: `create <path>`

Generate a prime file for the utility at `<path>` — a routing index that helps an AI coder navigate the utility in minimum tokens.

### Principles

- **Target: 15-30 lines.** Every line must save the AI more tokens than it costs to read.
- The AI has `Read`, `Grep`, `Glob`. Don't reproduce what tool calls discover.
- Only include what the AI CANNOT efficiently find: routing, traps, exclusions.
- NO: line numbers, code descriptions, DOM anchors, request flow diagrams, URL params, environment tables, external service catalogs. The AI will discover these via tool calls.
- Follow the **PRIME Files Philosophy** from `crew-members/general.md`: low noise, high value, pointers not copies, no volatile metrics.
- Save to `{utility}/prime-{short-name}.md`

### Workflow

#### Step 1: Scan

`Glob` and `Read` the utility directory. Identify:
- Entry points (the 2-4 files an AI should read first)
- Build system (if any)
- Generated/vendor/dead files the AI should skip

#### Step 2: Report

Show the user a 3-line summary: entry points, build system, files to skip. Then proceed to questions.

#### Step 3: Ask 3 Questions

Use your environment's ask-user prompt/tool to ask these questions (free-text answers):

**Q1: "Which files should an AI read first to understand this utility?"**
- The files that contain the core logic, not config or boilerplate
- This becomes the **Read first** section
- Files that drive the rest of the code so that the project becomes discoverable

**Q2: "What files or code sections should the AI NOT edit?"**
- Dead code kept for reference, generated output, vendor files, config that looks editable but isn't
- This becomes the **Do not edit** section

**Q3: "What traps would waste an AI's debugging time?"**
- Dev/prod differences, path resolution gotchas, naming that misleads, two-directory patterns
- This becomes the **Traps** section

#### Step 4: Generate

Combine auto-detected facts with user answers. Apply these rules:
- If a section would be empty, omit it entirely
- If there's no build step, omit **Must build**
- Every line must earn its place — "would an AI waste tokens without this?"

#### Step 5: Write

Write to `{path}/prime-{short-name}.md` using this template:

```md
# Prime: {short-name}

{One line: what this utility is and where it lives.}

## Read first
- `{file}` — {why this one, max 8 words}
{2-4 files max}

## Do not edit
- `{file-or-pattern}` — {why}

## Must build
`{one-liner command}`

## Traps
- **{symptom}** — {cause and fix, one line}
```

#### Step 6: Post-creation checks

1. Show the user the generated file and ask if anything is missing.
2. Check whether the prime should be registered in CLAUDE.md:
   - **Utility-specific primes** (live in a utility root): NOT registered — discovered by convention via glob
   - **Cross-cutting primes** (shared docs not in a utility root): SHOULD be registered in CLAUDE.md if it has a prime registry section
3. Check if sibling primes exist in the same area. If so, add cross-links.
4. If the area now has 3+ primes, check whether an area index prime exists. If not, suggest creating one.

#### Report

After writing the file, output:

```
Prime created: {path}/prime-{short-name}.md ({line count} lines)
Sections: {list of included sections}
```

---

## Sub-Command: `audit`

Perform a read-only health check on the repo's prime file system. Prime files (`prime-*.md`) are AI context documents that live in utility directories. Your job is to audit them for staleness, missing coverage, and broken references.

**Important: Do NOT modify any files.** This is an audit-only operation. Report findings; let the user decide what to fix.

### Conventions

If CLAUDE.md has a section describing prime file conventions, read it to understand the project's specific rules. The general conventions are:
- **Utility-specific primes:** `<utility-dir>/prime-<name>.md` — discovered by convention (recursive glob), NOT registered in CLAUDE.md
- **Satellite docs:** `known-bugs-<name>.md`, `lessons-learned/<topic>.md` — live alongside the prime
- **Cross-cutting primes:** Registered in CLAUDE.md's prime registry section (if one exists) — only for shared docs that don't live in a utility root
- **Cross-linking:** Primes in the same area must cross-link to each other (not just operational dependencies)
- **Area indexes:** Areas with 3+ primes need one prime that lists all related primes as the entry point

### Step 1: Discover all prime files

```
glob **/prime-*.md
```

Build a table of every prime file with columns: path, utility it documents, last modified.

Skip directories that are clearly not source primes — build output (`dist/`, `build/`, `.next/`), dependencies (`node_modules/`, `vendor/`), and session/scratch artifacts (temp directories, `.cache/`).

### Step 2: Validate each prime file

For each prime file, check:

1. **Key files still exist** — read the prime, extract any file paths it references (e.g., "Read first: `src/index.js`"), verify those files still exist on disk via glob. Flag any that are missing.

2. **Utility directory still exists** — confirm the parent utility directory is populated (not empty/deleted).

3. **Internal links valid** — check any relative markdown links (`[text](path)`) in the prime resolve to real files.

4. **CLAUDE.md link correct** — if the prime has a link back to CLAUDE.md, verify the relative path depth is correct for its location.

5. **No absolute paths** — grep for `file:///` URLs in the prime. All links must be relative from the prime's directory. Flag any absolute paths as portability violations.

6. **Cross-links present** — primes in the same area (sharing a parent directory tree) should cross-link to each other, not just for operational dependencies. If two primes are siblings or cousins in the same area (e.g., multiple primes under the same utility root), flag missing cross-links.

7. **Area index exists** — if an area (parent directory tree) contains **3 or more primes**, one prime should serve as the **area index** that lists all related primes. An area index prime is identified by: (a) a filename matching `prime-*-index.md` (e.g., `prime-auth-index.md`), or (b) containing a `## Related Primes` or `## Index` section that lists other primes in the same area. Check if such an index prime exists and whether it lists all primes in that area. Flag areas with 3+ primes but no index prime.

### Step 3: Find utilities without primes

Identify directories that have source code but no prime file. A utility-sized directory typically has its own entry point, build config, or package manifest.

Look for directories containing source files (`.php`, `.js`, `.ts`, `.py`, `.go`, `.rs`, `.rb`, etc.) but no `prime-*.md`. Use the project's directory structure to identify utility-sized units — directories with their own `package.json`, `composer.json`, `Makefile`, `index.*` entry point, or similar markers of an independent unit.

Skip directories that are clearly not utility roots: `node_modules/`, `vendor/`, `dist/`, `build/`, `.next/`, `.git/`, test fixture directories.

If CLAUDE.md defines known utility locations or directory conventions, use those as the primary scan targets. Otherwise, scan the project root with reasonable depth limits (2-3 levels).

Focus on directories that represent distinct utilities or modules — not every subdirectory needs a prime. A directory is a good "missing prime" candidate if:
- It has 5+ source files
- It has its own entry point or build config
- An AI would need multiple tool calls to understand its structure

Report these as "missing prime" candidates.

### Step 4: Audit satellite docs

```
glob **/known-bugs-*.md
glob **/lessons-learned/**/*.md
```

For each satellite doc, verify its parent directory also has a prime file. Flag orphaned satellites (satellite exists but no prime in the same utility).

### Step 5: Verify CLAUDE.md registry (if applicable)

Read CLAUDE.md and check whether it has a prime file registry section. If it does:
1. Every path listed in the registry points to a real file
2. No utility-specific primes have been accidentally registered (they should be discovered by convention)
3. The convention description is still accurate

If CLAUDE.md has no prime registry section, skip this step.

### Step 6: Content freshness spot-check

For each prime, do a quick sanity check:
- If it references a dev server command, does that script still exist?
- If it references specific config files, do they still exist?
- If it has a "Do not edit" section with vendor files, are those files still present?

Don't read every line of source code — just verify the pointers are valid.

### Output Format

Report findings as a structured checklist:

```markdown
## Prime Audit Report — YYYY-MM-DD

### Summary
- Total primes found: N
- Healthy: N
- Issues found: N
- Utilities missing primes: N

### Issues

#### Stale references
- [ ] `path/prime-foo.md` references `src/old-file.js` which no longer exists
- [ ] ...

#### Missing primes
- [ ] `web/.../some-utility/` has source files but no prime
- [ ] ...

#### Broken links
- [ ] `path/prime-foo.md` has broken link to `../../CLAUDE.md` (wrong depth)
- [ ] ...

#### Absolute paths (portability)
- [ ] `path/prime-foo.md` uses `file:///Users/...` absolute URL — must be relative
- [ ] ...

#### Missing area indexes
- [ ] `web/checkout-eet/` has N primes but no index prime listing them all
- [ ] ...

#### Orphaned satellites
- [ ] `path/known-bugs-foo.md` exists but no prime in that directory
- [ ] ...

#### CLAUDE.md registry
- [ ] All registered paths valid: YES/NO
- [ ] No utility-specific primes registered: YES/NO

### Recommendations
[Actionable next steps — which primes to update, which to create, which links to fix]
```

Be concise. Only flag actual issues. "Everything looks fine" for a prime is not worth reporting individually.
