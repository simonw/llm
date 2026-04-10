# Version Action

> **Part of the do-work skill.** Handles version reporting, update checks, and work recaps.

**Current version**: 0.57.0

**Upstream**: https://raw.githubusercontent.com/knews2019/skill-do-work/main/actions/version.md

## Responding to Version Requests

When user asks "what version", "version", "what's new", "release notes", "what's changed", "updates", or "history":

1. Report the version shown above
2. **Show last 5 skill releases**:
   - Read the first ~80 lines of `CHANGELOG.md` in the skill's root directory (same level as `SKILL.md`) — do NOT load the full file
   - Extract the 5 most recent version entries (split at `## ` headings, take first 5 blocks)
   - Reverse so newest is at the bottom (right where the user's eyes are)
   - Print them after the version number

## Responding to Update Checks

When user asks "check for updates", "update", or "is there a newer version":

1. **Fetch upstream**: Use your environment's web fetch capability to get the raw version.md from the upstream URL above
2. **Extract remote version**: Look for `**Current version**:` in the fetched content
3. **Compare versions**: Use semantic versioning comparison
4. **Report result** using the format below

### Report Format

**If update available** (remote > local):

1. **Tell the user**: `Update available: v{remote} (you have v{local}).`
2. **Check for local changes** to shipped skill files (where SKILL.md lives):
   - **Scope the check to skill-owned files only.** Ignore `do-work/` (queue data, archives, deliverables) — those are generated at runtime and should never block an update.
   - If the directory is a git repo, run `git -C <skill-root> status --porcelain -- SKILL.md actions/ crew-members/ CHANGELOG.md README.md` (listing only shipped paths) and check for uncommitted changes.
   - If it's **not** a git repo, check whether shipped skill files (actions/, crew-members/, SKILL.md, etc.) differ from a fresh install by looking for user-modified content (custom crew-members, edited action files, etc.).
   - **If any shipped skill files are dirty / have local modifications**: Stop and warn the user. List the modified files and ask for explicit confirmation before proceeding. Do NOT auto-update.
   - **If clean**: Proceed to step 3.
3. **Run the update** from the skill's root directory:
   ```
   curl -sL https://github.com/knews2019/skill-do-work/archive/refs/heads/main.tar.gz | tar xz --strip-components=1 --exclude='_dev'
   ```
   **Note:** tar extraction adds and overwrites files but does not delete files removed upstream. Stale files from older versions may remain. This is generally harmless — the skill only loads files it references. If you need a fully clean update, delete only the known skill paths (`actions/`, `crew-members/`, `SKILL.md`, `CHANGELOG.md`, `README.md`) before extracting — never delete `do-work/` or other project files.
4. **Verify**: Read `actions/version.md` again and confirm the local version now matches the remote version.
5. **Report result**: `Updated to v{remote}.`

Do NOT just print the curl command and ask the user to run it. You are the agent — run it yourself.

**If up to date** (local >= remote):

```
You're up to date (v{local})
```

**If fetch fails**:

```
Couldn't check for updates.
```

Attempt the update anyway using the curl command above (still respecting the dirty-tree check in step 2). If that also fails, report the error and provide the manual command as a fallback:

```
To manually update, run this from the skill's root directory (where SKILL.md lives):
curl -sL https://github.com/knews2019/skill-do-work/archive/refs/heads/main.tar.gz | tar xz --strip-components=1 --exclude='_dev'

Or visit: https://github.com/knews2019/skill-do-work
```

## Responding to Recap Requests

When user asks "recap":

1. **Archive source** (`do-work/archive/UR-*/`): Read as before — title from `input.md`, REQs from `REQ-*.md` files inside each UR folder.
2. **Active source** (`do-work/user-requests/UR-*/`): Read `input.md` for the title. For REQs, scan root `do-work/REQ-*.md` files whose `user_request:` frontmatter field matches the UR id (e.g., `user_request: UR-143`). Also check `do-work/working/` for claimed REQs belonging to the UR.
3. **Merge**: Combine both lists, deduplicate by UR id (archive version wins if both exist), sort by UR number descending, take top 5.
4. **Label each UR**:
   - No label if fully archived
   - `(pending)` if the UR has any pending REQs
   - `(completed, awaiting archive)` if all its REQs are completed/done but the UR isn't archived yet
5. **Format as a "Recent Work" section**:
   ```
   ## Recent Work

   UR-144 — Block-level improved translation for ZH pairs
     REQ-361 — Block-level improved translation
   UR-143 — Model selector thinking variants (completed, awaiting archive)
     REQ-360 — Model selector thinking variants
   UR-142 — Quality-Score-Driven Repair Loop (completed, awaiting archive)
     REQ-359 — Quality-Score-Driven Repair Loop
   UR-011 — Dark mode implementation
     REQ-043 — Theme store setup
     REQ-044 — Settings panel toggle
   ```
   One line per UR, one indented line per REQ. No descriptions, no scores, no file lists.
6. **If no archive exists AND no active URs found**: Print `No completed work yet.` and skip this section.
