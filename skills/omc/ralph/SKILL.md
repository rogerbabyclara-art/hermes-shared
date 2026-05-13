---
name: ralph
description: Self-referential loop until task completion with configurable verification reviewer (from OMC)
version: 0.1.0
author: OMC/Hermes
metadata:
  from_omc: true
  omc_level: 4
---

# Ralph

Self-referential loop until task completion with configurable verification reviewer

## Trigger phrases
- "ralph"

## Purpose

Extracted from OMC (oh-my-claudecode) skill system. This skill provides structured workflow automation.

## Workflow

See OMC documentation for detailed workflow steps.

## Original OMC Content

[RALPH + ULTRAWORK - ITERATION {{ITERATION}}/{{MAX}}]

Your previous attempt did not output the completion promise. Continue working on the task.

<Purpose>
Ralph is a PRD-driven persistence loop that keeps working on a task until ALL user stories in prd.json have passes: true and are reviewer-verified. It wraps ultrawork's parallel execution with session persistence, automatic retry on failure, structured story tracking, and mandatory verification before completion.
</Purpose>

<Use_When>
- Task requires guaranteed completion with verification (not just "do your best")
- User says "ralph", "don't stop", "must complete", "finish this", or "keep going until done"
- Work may span multiple iterations and needs persistence across retries
- Task benefits from structured PRD-driven execution with reviewer sign-off
</Use_When>

<Do_Not_Use_When>
- User wants a full autonomous pipeline from idea to code -- use `autopilot` instead
- User wants to explore or plan before committing -- use `plan` skill instead
- User wants a quick one-shot fix -- delegate directly to an executor agent
- User wants manual control over completion -- use `ultrawork` directly
</Do_Not_Use_When>

<Why_This_Exists>
Complex tasks often fail silently: partial implementations get declared "done", tests get skipped, edge cases get forgotten. Ralph prevents this by:
1. Structuring work into discrete user stories with testable acceptance criteria (prd.json)
2. Iterating story-by-story until each one passes
3. Tracking progress and learnings across iterations (progress.txt)
4. Requiring fresh reviewer verification against specific acceptance criteria before completion
</Why_This_Exists>

<PRD_Mode>
By default, ralph operates in PRD mode. A scaffold `prd.json` is auto-generated when ralph starts if none exists.

**Startup gate:** Ralph always initializes and validates `prd.json` at startup. Legacy `--no-prd` text is sanitized from the prompt for backward compatibility, but it no longer bypasses PRD creation 

... (content truncated)

## See Also

- Original: https://github.com/Yeachan-Heo/oh-my-claudecode
- OMC Skills: `/home/dev/workspace/omc/skills/ralph/`
