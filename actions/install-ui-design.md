# Install UI Design Action

> **Part of the do-work skill.** Installs the `frontend-design` Claude skill for production-grade frontend interfaces with high design quality.

## What It Does

Installs the Anthropic-maintained `frontend-design` skill into the current project. This skill gives Claude specialized knowledge for creating production-grade frontend interfaces with strong visual design, layout, and interaction quality.

Once installed, the skill is available to all agents working in this project — including do-work builders processing `domain: ui-design` requests.

## Workflow

### Step 1: Check If Already Installed

Look for an existing installation:

```bash
ls .claude/skills/frontend-design/SKILL.md 2>/dev/null
```

If the file exists, report that it's already installed and stop.

### Step 2: Install the Skill

Create the skill directory and download the skill file:

```bash
mkdir -p .claude/skills/frontend-design
curl -fsSL -o .claude/skills/frontend-design/SKILL.md \
  https://raw.githubusercontent.com/anthropics/claude-code/main/skills/frontend-design/SKILL.md
```

If `curl` is not available or the download fails, check for the skill in your environment's plugin/skill registry (e.g., `/plugin install frontend-design` or equivalent) and install it from there.

### Step 3: Verify Installation

Confirm the file exists and is non-empty:

```bash
test -s .claude/skills/frontend-design/SKILL.md && echo "Installed successfully" || echo "Installation failed"
```

### Step 4: Report Back

Tell the user what was installed and how it integrates:

```
Installed: frontend-design skill

This skill gives Claude production-grade UI design capabilities including:
- Professional visual aesthetics (typography, color, spacing, layout)
- Component design with proper states and variants
- Responsive, mobile-first implementations
- Accessibility-compliant interfaces

It works alongside do-work's `domain: ui-design` rules — the skill provides
implementation expertise while the domain rules provide workflow structure.

Requests tagged `domain: ui-design` will benefit from both automatically.
```

## Notes

- This action only installs the skill — it does not capture or process requests.
- The skill is project-scoped (`.claude/skills/`), not global. Each project that needs it should install it.
- If the project doesn't use Claude Code, the manual curl fallback ensures the skill file is still available for agents that can read it directly.
