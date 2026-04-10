# Prime Files

Create and audit prime files — AI context documents that help an AI coder navigate a utility in minimum tokens. A prime file is a semantic index: entry points, traps, and exclusions so the AI doesn't waste tool calls rediscovering architecture.

## Sub-commands

| Sub-command | What it does |
|---|---|
| `create <path>` | Generate a new prime file for a utility via interactive Q&A |
| `audit` | Read-only health check of all prime files — stale refs, missing primes, broken links |
| (none) | Show help menu |

## Create workflow

1. **Scan** — globs the target directory for entry points, build system, and files to skip
2. **Report** — shows a 3-line summary of what was found
3. **Ask 3 questions** — which files to read first, what not to edit, what traps exist
4. **Generate** — combines auto-detected facts with your answers
5. **Write** — saves to `{path}/prime-{short-name}.md`
6. **Post-creation checks** — shows the result, checks CLAUDE.md registration, cross-links siblings

### Prime file format

```md
# Prime: {short-name}

{One line: what this utility is and where it lives.}

## Read first
- `{file}` — {why this one, max 8 words}

## Do not edit
- `{file-or-pattern}` — {why}

## Must build
`{one-liner command}`

## Traps
- **{symptom}** — {cause and fix, one line}
```

Target: 15-30 lines. Empty sections are omitted. Every line must save the AI more tokens than it costs to read.

### Registration rules

- **Utility-specific primes** (live in a utility root) — discovered by convention via `glob **/prime-*.md`, NOT registered in CLAUDE.md
- **Cross-cutting primes** (shared docs not in a utility root) — registered in CLAUDE.md under `### Registered`

## Audit checks

The audit is read-only — it reports findings but never modifies files.

| Check | What it detects |
|-------|----------------|
| **Stale references** | File paths in a prime that no longer exist on disk |
| **Missing primes** | Utility directories with source files but no prime |
| **Broken links** | Relative markdown links that don't resolve |
| **Absolute paths** | `file:///` URLs that should be relative (portability) |
| **Missing cross-links** | Sibling primes in the same area that don't link to each other |
| **Missing area indexes** | Areas with 3+ primes but no index prime listing them all |
| **Orphaned satellites** | `known-bugs-*.md` or `lessons-learned/` docs with no parent prime |
| **CLAUDE.md registry** | Registered paths that are broken or utility primes accidentally registered |
| **Content freshness** | Dev server commands, config files, or vendor files referenced but missing |

### Output

Markdown report with summary counts and a checklist of issues organized by category. Only actual issues are reported — healthy primes are not listed individually.

## Key rules

- Follows the PRIME Files Philosophy from `crew-members/general.md`: low noise, high value, pointers not copies, no volatile metrics
- Multiple primes per directory are valid for different concerns
- `create` is interactive (asks 3 questions); `audit` is fully automated and read-only

## Usage

```
do work prime                     # show sub-command help
do work prime create src/auth/    # generate a prime file via Q&A
do work prime audit               # audit all prime files
do work create prime src/utils/   # reversed order also works
do work audit primes              # same as prime audit
```
