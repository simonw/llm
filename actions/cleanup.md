# Cleanup Action

> **Part of the do-work skill.** Invoked when routing determines the user wants to tidy the archive, or automatically at the end of the work loop. Consolidates loose files and ensures the archive is well-organized.

The archive should be a collection of self-contained UR folders, each containing their original input and all related REQ files. Over time, REQ files can end up loose in the archive root — either from intermediate archival (when not all REQs were done yet) or from legacy requests predating the UR system. This action fixes that.

## When This Runs

- **Automatically** at the end of every work loop (after all pending REQs are processed)
- **Manually** when the user invokes it (e.g., `do work cleanup`, `do work tidy`)

## What It Does

Four passes, in order:

### Pass 0: Sweep Finished Queue Items

Scan the queue root and working directory for REQs with terminal statuses that should have been archived but weren't — typically from manual work, different agents, or legacy sessions that completed outside the standard work pipeline.

1. **Glob `do-work/REQ-*.md`** in the queue root
2. **Read each REQ's frontmatter** `status` field
3. **If status is any terminal value** — `completed`, `completed-with-issues`, `failed`, or any non-standard terminal status (`done`, `finished`, `closed`):
   - **Normalize non-standard statuses** before moving: change `done` → `completed`, `finished` → `completed`, `closed` → `completed` in frontmatter
   - Move the REQ to `do-work/archive/` root (Pass 1 and Pass 2 will then consolidate it into the correct UR folder)
   - Report: `Swept REQ-NNN from queue root (was status: {original}) → archive`
4. **Leave `pending`, `pending-answers`, and `claimed` REQs untouched** — those are active queue items
5. **Also check `do-work/working/`** — if any REQ there has a terminal status (`completed`, `completed-with-issues`, `done`, `finished`, `closed`, `failed`), it was finished but never moved out. Same treatment: normalize status, move to `do-work/archive/` root, report it.

### Pass 1: Close Completed User Requests

Check `do-work/user-requests/` for UR folders that are ready to archive.

For each UR folder in `do-work/user-requests/`:

1. Read `input.md` and parse the `requests` array from frontmatter (e.g., `[REQ-044, REQ-045, REQ-046]`)
2. For each REQ ID in the array, check if it exists with `status: completed` in ANY of these locations:
   - `do-work/archive/UR-NNN/` (already consolidated)
   - `do-work/archive/` root (loose in archive)
   If the same REQ-ID is found in **both** locations simultaneously, flag it and leave the UR in `user-requests/` untouched: `⚠ Duplicate: REQ-NNN found in both archive/ root and archive/UR-NNN/. Resolve manually, then re-run cleanup.`
3. If **ALL** REQs are completed (and no duplicates flagged):
   - Gather any loose completed REQ files from `do-work/archive/` root into the UR folder
   - Move the entire UR folder to `do-work/archive/UR-NNN/`
   - Report: `Archived UR-NNN (all N REQs complete)`
4. If **NOT all** REQs are completed:
   - Leave the UR folder in `user-requests/` — it's not ready yet
   - Report: `UR-NNN still open (X/Y REQs complete)`

### Pass 2: Consolidate Loose REQ Files in Archive

Check `do-work/archive/` root for any `REQ-*.md` files that should be inside a UR folder.

For each loose `REQ-*.md` file directly in `do-work/archive/` (not inside a subfolder):

1. Read its frontmatter and check for a `user_request` field
2. **If it has `user_request: UR-NNN`:**
   - Check if `do-work/archive/UR-NNN/` exists
   - If yes: move the REQ file into that UR folder
   - If no: check if `do-work/user-requests/UR-NNN/` exists (UR still open — leave the REQ in archive root for now; it will be consolidated when the UR is fully complete and archived by Pass 1)
   - If the UR folder doesn't exist anywhere: report a warning — `REQ-XXX references UR-NNN but no UR folder found`
3. **If it has NO `user_request` field (legacy/standalone):**
   - Move it to `do-work/archive/legacy/` (create the folder if needed)
   - Report: `Moved REQ-XXX to archive/legacy/ (no UR reference)`

### Pass 3a: Misplaced do-work Directories Elsewhere in the Repo

Scan for `do-work/` directories created inside utility subdirectories instead of the project root. This happens when an agent's working directory drifts into a subdirectory (e.g., during a refactor) and the next capture creates `do-work/` relative to that location. Once the misplaced directory exists, subsequent sessions keep writing there — silently diverging from the canonical queue.

1. **Detect directories, not file patterns.** Search for any directory named `do-work/` anywhere in the repo EXCEPT the project root. Look for the directory itself — don't rely on specific file patterns inside it, since a misplaced tree may contain only `user-requests/`, only `working/`, only assets, or any partial subset of the normal structure.
2. For each misplaced `do-work/` found, inspect its known subtrees (`archive/`, `user-requests/`, `working/`, and queue-root REQ files). Relocate preserving internal structure:
   - **Queue-root REQ files** (`do-work/REQ-*.md`): move to canonical `do-work/REQ-*.md`. **Before moving**, check if a REQ with the same number already exists at the canonical location (Pass 0 sweeps terminal-status REQs, but a misplaced `do-work/` may have a REQ with a status Pass 0 doesn't touch, such as `pending`). Conflict = same REQ number exists at both locations — report and leave the misplaced copy in place for manual resolution.
   - **`user-requests/UR-NNN/`**: move entire folder to canonical `do-work/user-requests/UR-NNN/`. Conflict = same UR number exists at both locations.
   - **`archive/UR-NNN/`**: move entire folder to canonical `do-work/archive/UR-NNN/`. Conflict = same UR number exists at both locations.
   - **`working/REQ-*.md`**: move to canonical `do-work/working/REQ-*.md`. Conflict = same REQ number exists at both locations.
   - **Other files/dirs**: move to matching path under canonical `do-work/`. Conflict = same path already exists.
   - **Conflict handling**: when the same item exists at both locations, do NOT overwrite — report the conflict with both paths and leave the misplaced copy in place for manual resolution.
   - Report: `Found misplaced do-work/ at {path} — relocated {N} items to project root` (and list any conflicts separately)
3. After relocating all non-conflicting contents, remove the misplaced `do-work/` directory if empty. If conflicts remain, leave it in place.

### Pass 3b: Misplaced Folders Within the Archive

Check for UR folders that ended up in wrong locations within the archive.

1. Check if `do-work/archive/user-requests/` exists (this is a common mistake — the entire `user-requests/` dir got moved instead of individual UR folders)
2. If it exists, for each `UR-NNN/` folder inside it:
   - If `do-work/archive/UR-NNN/` does NOT already exist: move it up to `do-work/archive/UR-NNN/`
   - If `do-work/archive/UR-NNN/` DOES already exist: merge contents (move files from the misplaced folder into the correct one)
   - Report: `Fixed misplaced UR-NNN (was in archive/user-requests/)`
3. If `do-work/archive/user-requests/` is now empty, remove it

Also check for and consolidate any loose CONTEXT-*.md files:
- Move to `do-work/archive/legacy/` alongside legacy REQs

## Reporting

Print a summary at the end:

```
Archive cleanup complete:
  - Swept: 3 finished REQs from queue root, 1 from working/
  - Archived: UR-011 (3 REQs), UR-004 (8 REQs)
  - Consolidated: 5 loose REQs into their UR folders
  - Legacy: 24 REQs moved to archive/legacy/
  - Misplaced do-work/: relocated 7 REQs, 6 URs from exp/g3-segment-anything/do-work/
  - Fixed: 1 misplaced UR folder in archive
  - Still open: UR-015 (2/4 REQs complete)
```

If nothing needed fixing:
```
Archive is clean. No loose files or pending closures found.
```

## Archive Structure After Cleanup

```
do-work/archive/
├── UR-001/                    # Self-contained: input + all REQs
│   ├── input.md
│   ├── assets/
│   ├── REQ-018-feature.md
│   └── REQ-019-feature.md
├── UR-002/
│   ├── input.md
│   └── REQ-024-feature.md
├── legacy/                    # REQs and CONTEXT docs without UR references
│   ├── REQ-001-old-task.md
│   ├── REQ-002-old-task.md
│   └── CONTEXT-001-batch.md
└── hold/                      # Items on hold (paused by user — cleanup skips these)
```

**No loose REQ or CONTEXT files should exist directly in `do-work/archive/` after cleanup.**

## Commit (Git repos only)

After all passes complete, if any files were moved or consolidated, commit the structural changes.

Check for git with `git rev-parse --git-dir 2>/dev/null`. If not a git repo, skip.

```bash
# Stage all paths affected by cleanup (moves show as delete + add)
# Include queue root and working/ if Pass 0 swept any finished REQs
git add do-work/archive/ do-work/user-requests/
# If Pass 0 swept REQs from queue root or working/, also stage those paths:
# git add do-work/REQ-NNN-*.md do-work/working/REQ-NNN-*.md  (the deletion side of the moves)
# If Pass 3a found misplaced directories, also stage those paths:
# git add exp/g3-segment-anything/do-work/  (the deletion side of the move)

git commit -m "$(cat <<'EOF'
do-work: cleanup — consolidated {N} REQs, closed {M} URs

- Archived: {list of UR-NNN closed}
- Consolidated: {X} loose REQs into UR folders
- Legacy: {Y} items moved to archive/legacy/
- Fixed: {Z} misplaced folders

EOF
)"
```

**Format:** `do-work: cleanup — consolidated {N} REQs, closed {M} URs` — adjust the counts and bullet list to reflect what actually changed. Omit bullet categories where the count is zero.

If nothing was moved (archive was already clean), skip the commit entirely.

Do not use `git add -A` or `git add .` — stage only paths within `do-work/archive/`, `do-work/user-requests/`, any queue root or working/ REQs swept by Pass 0, and any misplaced `do-work/` directories relocated by Pass 3a. Don't bypass pre-commit hooks.

## What This Action Does NOT Do

- Delete any files — only moves them into the right location
- Modify file contents or frontmatter — files are relocated as-is. Exception: Pass 0 normalizes non-standard terminal statuses (`done` → `completed`, etc.) in frontmatter before moving.
- Touch **active** files in the **canonical** `do-work/` root (the queue) or `do-work/working/` — `pending`, `pending-answers`, and `claimed` REQs are the work action's responsibility. Exceptions: Pass 0 sweeps REQs with terminal statuses (`completed`, `done`, `failed`, etc.) from queue root and working/ to archive — that's recovering stranded finished work, not queue processing. Pass 3a relocates queue and working items from **misplaced** `do-work/` trees (created in the wrong directory) back to the canonical root — that's error recovery.
- Archive UR folders that still have pending/in-progress REQs
- Process any REQ files (use the work action for that)
