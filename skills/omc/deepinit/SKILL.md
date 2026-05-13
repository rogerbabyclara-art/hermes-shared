---
name: deepinit
description: Deep codebase initialization with hierarchical AGENTS.md documentation (from OMC)
version: 0.1.0
author: OMC/Hermes
metadata:
  from_omc: true
---

# deepinit

Deep codebase initialization with hierarchical AGENTS.md documentation

## Source
OMC: https://github.com/Yeachan-Heo/oh-my-claudecode

---

(Adapted for Hermes)

---
name: deepinit
description: Deep codebase initialization with hierarchical AGENTS.md documentation
level: 4
---

# Deep Init Skill

Creates comprehensive, hierarchical AGENTS.md documentation across the entire codebase.

## Core Concept

AGENTS.md files serve as **AI-readable documentation** that helps agents understand:
- What each directory contains
- How components relate to each other
- Special instructions for working in that area
- Dependencies and relationships

## Hierarchical Tagging System

Every AGENTS.md (except root) includes a parent reference tag:

```markdown
<!-- Parent: ../AGENTS.md -->
```

This creates a navigable hierarchy:
```
/AGENTS.md                          ← Root (no parent tag)
├── src/AGENTS.md                   ← <!-- Parent: ../AGENTS.md -->
│   ├── src/components/AGENTS.md    ← <!-- Parent: ../AGENTS.md -->
│   └── src/utils/AGENTS.md         ← <!-- Parent: ../AGENTS.md -->
└── docs/AGENTS.md                  ← <!-- Parent: ../AGENTS.md -->
```

## AGENTS.md Template

```markdown
<!-- Parent: {relative_path_to_parent}/AGENTS.md -->
<!-- Generated: {timestamp} | Updated: {timestamp} -->

# {Directory Name}

## Purpose
{One-paragraph description of what this directory contains and its role}

## Key Files
{List each significant file with a one-line description}

| File | Description |
|------|-------------|
| `file.ts` | Brief description of purpose |

## Subdirectories
{List each subdirectory with brief purpose}

| Directory | Purpose |
|-----------|---------|
| `subdir/` | What it contains (see `subdir/AGENTS.md`) |

## For AI Agents

### Working In This Directory
{Special instructions for AI agents modifying files here}

### Testing Requirements
{How to test changes in this directory}

### Common Patterns
{Code patterns or conventions used here}

## Dependencies

### Internal
{References to other parts of the codebase this depends on}

### External
{Key external packages/libraries used}

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
```

## Execution Workflow

### Step 1: Map Directory Structure

```
Task(subagent_type="explore", model="haiku",
  prompt="List all directories recursively. Exclude: node_modules, .git, dist, build, __pycache__, .venv, coverage, .next, .nuxt")
```

### Step 2: Create Work Plan

Generate todo items for each directory, organized by depth level:

```
Level 0: / (root)
Level 1: /src, /docs, /tests
Level 2: /src/components, /src/utils, /docs/api
...
```

### Step 3: Generate Level by Level

**IMPORTANT**: Generate parent levels before child levels to ensure parent references are valid.

For each directory:
1. Read all files in the directory
2. Analyze purpose and relationships
3. Generate AGENTS.md content
4. Write file with proper parent reference

### Step 4: Compare and Update (if exists)

When AGENTS.md already exists:

1. **Read existing content**
2. **Identify sections**:
   - Auto-generated sections (can be updated)
   - Manual sections 
