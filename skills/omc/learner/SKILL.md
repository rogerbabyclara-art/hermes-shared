---
name: learner
description: Extract a learned skill from the current conversation (from OMC)
version: 0.1.0
author: OMC/Hermes
metadata:
  from_omc: true
  omc_level: 7
---

# Learner

Extract a learned skill from the current conversation

## Trigger phrases
- "learner"

## Purpose

Extracted from OMC (oh-my-claudecode) skill system. This skill provides structured workflow automation.

## Workflow

See OMC documentation for detailed workflow steps.

## Original OMC Content

# Learner Skill

This is a Level 7 (self-improving) skill. It has two distinct sections:
- **Expertise**: Domain knowledge about what makes a good skill. Updated automatically as patterns are discovered.
- **Workflow**: Stable extraction procedure. Rarely changes.

Only the Expertise section should be updated during improvement cycles.

---

## Expertise

> This section contains domain knowledge that improves over time.
> It can be updated by the learner itself when new patterns are discovered.

### Core Principle

Reusable skills are not code snippets to copy-paste, but **principles and decision-making heuristics** that teach Claude HOW TO THINK about a class of problems.

**The difference:**
- BAD (mimicking): "When you see ConnectionResetError, add this try/except block"
- GOOD (reusable skill): "In async network code, any I/O operation can fail independently due to client/server lifecycle mismatches. The principle: wrap each I/O operation separately, because failure between operations is the common case, not the exception."

### Quality Gate

Before extracting a skill, ALL three must be true:
- "Could someone Google this in 5 minutes?" → NO
- "Is this specific to THIS codebase?" → YES
- "Did this take real debugging effort to discover?" → YES

### Recognition Signals

Extract ONLY after:
- Solving a tricky bug that required deep investigation
- Discovering a non-obvious workaround specific to this codebase
- Finding a hidden gotcha that wastes time when forgotten
- Uncovering undocumented behavior that affects this project

### What Makes a USEFUL Skill

1. **Non-Googleable**: Something you couldn't easily find via search
   - BAD: "How to read files in TypeScript" ❌
   - GOOD: "This codebase uses custom path resolution in ESM that requires fileURLToPath + specific relative paths" ✓

2. **Context-Specific**: References actual files, error messages, or patterns from THIS codebase
   - BAD: "Use try/catch for error handling" ❌
   - GOOD: "The aiohttp proxy in serv

... (content truncated)

## See Also

- Original: https://github.com/Yeachan-Heo/oh-my-claudecode
- OMC Skills: `/home/dev/workspace/omc/skills/learner/`
