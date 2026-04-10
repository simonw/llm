# Commit

Analyzes uncommitted changes, associates them with existing REQs for traceability, groups unassociated changes semantically, and commits in small atomic batches.

## How it works

1. **Preflight** — categorize changes (modified/added/deleted), exclude dangerous files (`.env`, credentials, keys)
2. **Read changes** — diffs for modified, full content for new, note paths for deleted
3. **Associate with REQs** — match files to archived REQ Implementation Summaries
4. **Group unassociated** — cluster remaining files semantically (1-5 per group)
5. **Commit** — REQ-associated groups first, then unassociated groups
6. **Report** — summary table with commit hashes, group labels, file counts

## Commit message format

REQ-associated changes:
```
[REQ-NNN] {title} — additional changes
```

Unassociated changes:
```
[do-work] {label}
```

## Key rules

- Stages specific files only (never `git add -A`)
- Respects pre-commit hooks (fixes issues, never bypasses with `--no-verify`)
- Excludes `.env`, credentials, and key files automatically
- One commit per semantic group
- Never pushes to remote

## Usage

```
do work commit
do work commit changes
do work save work
```
