---
name: skill
description: Manage local skills - list, add, remove, search, edit, setup wizard (from OMC)
version: 0.1.0
author: OMC/Hermes
metadata:
  from_omc: true
  omc_level: 2
---

# Skill

Manage local skills - list, add, remove, search, edit, setup wizard

## Trigger phrases
- "skill"

## Purpose

Extracted from OMC (oh-my-claudecode) skill system. This skill provides structured workflow automation.

## Workflow

See OMC documentation for detailed workflow steps.

## Original OMC Content

# Skill Management CLI

Meta-skill for managing oh-my-claudecode skills via CLI-like commands.

## Subcommands

### /skill list

Show all available skills organized by scope.

**Behavior:**
1. Scan bundled built-in skills in the plugin `skills/` directory (read-only)
2. Scan user skills at `${CLAUDE_CONFIG_DIR:-~/.claude}/skills/omc-learned/`
3. Scan project skills at `.omc/skills/`
4. Parse YAML frontmatter for metadata
5. Display in organized table format:

```
BUILT-IN SKILLS (bundled with oh-my-claudecode):
| Name              | Description                    | Scope    |
|-------------------|--------------------------------|----------|
| visual-verdict    | Structured visual QA verdicts  | built-in |
| ralph             | Persistence loop               | built-in |

USER SKILLS (~/.claude/skills/omc-learned/):
| Name              | Triggers           | Quality | Usage | Scope |
|-------------------|--------------------|---------|-------|-------|
| error-handler     | fix, error         | 95%     | 42    | user  |
| api-builder       | api, endpoint      | 88%     | 23    | user  |

PROJECT SKILLS (.omc/skills/):
| Name              | Triggers           | Quality | Usage | Scope   |
|-------------------|--------------------|---------|-------|---------|
| test-runner       | test, run          | 92%     | 15    | project |
```

**Fallback:** If quality/usage stats not available, show "N/A"

**Built-in skill note:** Built-in skills are bundled with oh-my-claudecode and are discoverable/readable, but not removed or edited through `/skill remove` or `/skill edit`.

---

### /skill add [name]

Interactive wizard for creating a new skill.

**Behavior:**
1. **Ask for skill name** (if not provided in command)
   - Validate: lowercase, hyphens only, no spaces
2. **Ask for description**
   - Clear, concise one-liner
3. **Ask for triggers** (comma-separated keywords)
   - Example: "error, fix, debug"
4. **Ask for argument hint** (optional)
   - Example: "<file> [options]"


... (content truncated)

## See Also

- Original: https://github.com/Yeachan-Heo/oh-my-claudecode
- OMC Skills: `/home/dev/workspace/omc/skills/skill/`
