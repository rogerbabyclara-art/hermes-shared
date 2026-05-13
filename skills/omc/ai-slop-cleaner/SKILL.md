---
name: ai-slop-cleaner
description: Clean AI-generated code slop with a regression-safe, deletion-first workflow and optional reviewer-only mode (from OMC)
version: 0.1.0
author: OMC/Hermes
metadata:
  from_omc: true
---

# ai-slop-cleaner

Clean AI-generated code slop with a regression-safe, deletion-first workflow and optional reviewer-only mode

## Source
OMC: https://github.com/Yeachan-Heo/oh-my-claudecode

---

(Adapted for Hermes)

---
name: ai-slop-cleaner
description: Clean AI-generated code slop with a regression-safe, deletion-first workflow and optional reviewer-only mode
level: 3
---

# AI Slop Cleaner

Use this skill to clean AI-generated code slop without drifting scope or changing intended behavior. In OMC, this is the bounded cleanup workflow for code that works but feels bloated, repetitive, weakly tested, or over-abstracted.

## When to Use

Use this skill when:
- the user explicitly says `deslop`, `anti-slop`, or `AI slop`
- the request is to clean up or refactor code that feels noisy, repetitive, or overly abstract
- follow-up implementation left duplicate logic, dead code, wrapper layers, boundary leaks, or weak regression coverage
- the user wants a reviewer-only anti-slop pass via `--review`
- the goal is simplification and cleanup, not new feature delivery

## When Not to Use

Do not use this skill when:
- the task is mainly a new feature build or product change
- the user wants a broad redesign instead of an incremental cleanup pass
- the request is a generic refactor with no simplification or anti-slop intent
- behavior is too unclear to protect with tests or a concrete verification plan

## OMC Execution Posture

- Preserve behavior unless the user explicitly asks for behavior changes.
- Lock behavior with focused regression tests first whenever practical.
- Write a cleanup plan before editing code.
- Prefer deletion over addition.
- Reuse existing utilities and patterns before introducing new ones.
- Avoid new dependencies unless the user explicitly requests them.
- Keep diffs small, reversible, and smell-focused.
- Stay concise and evidence-dense: inspect, edit, verify, and report.
- Treat new user instructions as local scope updates without dropping earlier non-conflicting constraints.

## Scoped File-List Usage

This skill can be bounded to an explicit file list or changed-file scope when the caller already knows the safe cleanup surface.

- Good fit: `oh-my-claudecode:ai-slop-cleaner skills/ralph/SKILL.md skills/ai-slop-cleaner/SKILL.md`
- Good fit: a Ralph session handing off only the files changed in that session
- Preserve the same regression-safe workflow even when the scope is a short file list
- Do not silently expand a changed-file scope into broader cleanup work unless the user explicitly asks for it

## Ralph Integration

Ralph can invoke this skill as a bounded post-review cleanup pass.

- In that workflow, the cleaner runs in standard mode (not `--review`)
- The cleanup scope is the Ralph session's changed files only
- After the cleanup pass, Ralph re-runs regression verification before completion
- `--review` remains the reviewer-only follow-up mode, not the default Ralph integration path

## Review Mode (`--review`)

`--review` is a reviewer-only pass after cleanup work is drafted. It exists to preserve explicit writer/reviewer separation for anti-slop work.

- **Writer pass**: make the cleanup changes with behavior locked by tests.
- 
