# Install Bowser Action

> **Part of the do-work skill.** Installs Playwright CLI (`playwright-cli`) and the Bowser skill for headed browser automation, screenshots, and UI validation.

## What It Does

Installs two components:

1. **`playwright-cli`** — a token-efficient CLI wrapper for Playwright. Supports headed/headless browsing, parallel named sessions, screenshots, snapshots, and persistent browser profiles.
2. **Bowser skill** — a skill file that teaches agents how to use `playwright-cli` effectively: session naming, viewport configuration, snapshot-based interaction, and cleanup.

Once installed, `do work ui-review` can use Playwright CLI for visual verification — screenshotting at multiple viewports, running accessibility checks on rendered pages, and catching layout issues that static code analysis misses.

## Workflow

### Step 1: Check If Already Installed

Check for both components:

```bash
# Check for playwright-cli
playwright-cli --help >/dev/null 2>&1 && echo "playwright-cli: installed" || echo "playwright-cli: not found"

# Check for Bowser skill
ls .claude/skills/playwright-bowser/SKILL.md 2>/dev/null && echo "bowser skill: installed" || echo "bowser skill: not found"
```

If both are present, report that everything is already installed and stop.

### Step 2: Install Playwright CLI

If `playwright-cli` is not found:

```bash
npm install -g @anthropic-ai/playwright-cli@latest
```

If `npm` is not available, try:

```bash
yarn global add @anthropic-ai/playwright-cli@latest
```

If neither package manager is available, report the error and provide the install command for the user to run manually.

### Step 3: Install Playwright Browsers

Playwright CLI needs browser binaries. Install them:

```bash
playwright-cli install --with-deps chromium
```

This installs only Chromium (sufficient for UI review). The `--with-deps` flag includes system dependencies. If this fails due to permissions, suggest:

```bash
npx playwright install chromium
```

### Step 4: Install the Bowser Skill

Create the skill directory from the **project root** and download the skill from the Bowser repository:

```bash
PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
mkdir -p "$PROJECT_ROOT/.claude/skills/playwright-bowser"
curl -fsSL -o "$PROJECT_ROOT/.claude/skills/playwright-bowser/SKILL.md" \
  https://raw.githubusercontent.com/disler/bowser/main/SKILL.md
```

If the download fails (network issue, file not at expected path), try an alternative path in the same repository:

```bash
# Fallback: check if skill is at a different path
PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
curl -fsSL -o "$PROJECT_ROOT/.claude/skills/playwright-bowser/SKILL.md" \
  https://raw.githubusercontent.com/disler/bowser/main/skills/playwright-bowser/SKILL.md
```

If both fail, report the error and direct the user to https://github.com/disler/bowser for manual installation.

### Step 5: Verify Installation

```bash
# Verify playwright-cli
playwright-cli --help >/dev/null 2>&1 && echo "playwright-cli: OK" || echo "playwright-cli: FAILED"

# Verify Bowser skill
PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
test -s "$PROJECT_ROOT/.claude/skills/playwright-bowser/SKILL.md" && echo "bowser skill: OK" || echo "bowser skill: FAILED"
```

### Step 6: Report Back

Tell the user what was installed and how it integrates:

```
Installed: Playwright CLI + Bowser skill

This gives agents browser automation capabilities including:
- Headed/headless browser sessions with Chromium
- Screenshots at any viewport size (mobile, tablet, desktop)
- DOM snapshots for accessibility and element inspection
- Parallel named sessions for independent browser tasks
- Persistent profiles (cookies, localStorage preserved)

It works alongside do-work's `ui-review` action — when Playwright CLI is
detected, ui-review automatically runs visual verification: viewport
screenshots, rendered-page layout checks, and accessibility audits.

To use directly: playwright-cli -s=my-session open https://example.com --persistent
```

## Notes

- This action installs both the CLI tool (global) and the skill file (project-scoped).
- `playwright-cli` is installed globally so it's available across projects. The Bowser skill is project-scoped (`<project-root>/.claude/skills/`).
- Only Chromium is installed by default. For Firefox or WebKit, run `playwright-cli install firefox` or `playwright-cli install webkit`.
- If the project doesn't use Claude Code, the skill file is still readable by any agent as a standalone prompt.
