---
name: deep-interview
description: Socratic deep interview with mathematical ambiguity gating before autonomous execution (from OMC)
version: 0.1.0
author: OMC/Hermes
metadata:
  from_omc: true
  omc_level: 3
---

# Deep-Interview

Socratic deep interview with mathematical ambiguity gating before autonomous execution

## Trigger phrases
- "deep-interview"

## Purpose

Extracted from OMC (oh-my-claudecode) skill system. This skill provides structured workflow automation.

## Workflow

See OMC documentation for detailed workflow steps.

## Original OMC Content

<Purpose>
Deep Interview implements Ouroboros-inspired Socratic questioning with mathematical ambiguity scoring. It replaces vague ideas with crystal-clear specifications by asking targeted questions that expose hidden assumptions, measuring clarity across weighted dimensions, and refusing to proceed until ambiguity drops below the resolved threshold for this run. The output feeds into a 3-stage pipeline: **deep-interview → ralplan (consensus refinement) → autopilot (execution)**, ensuring maximum clarity at every stage.
</Purpose>

<Use_When>
- User has a vague idea and wants thorough requirements gathering before execution
- User says "deep interview", "interview me", "ask me everything", "don't assume", "make sure you understand"
- User says "ouroboros", "socratic", "I have a vague idea", "not sure exactly what I want"
- User wants to avoid "that's not what I meant" outcomes from autonomous execution
- Task is complex enough that jumping to code would waste cycles on scope discovery
- User wants mathematically-validated clarity before committing to execution
</Use_When>

<Do_Not_Use_When>
- User has a detailed, specific request with file paths, function names, or acceptance criteria -- execute directly
- User wants to explore options or brainstorm -- use `omc-plan` skill instead
- User wants a quick fix or single change -- delegate to executor or ralph
- User says "just do it" or "skip the questions" -- respect their intent
- User already has a PRD or plan file -- use ralph or autopilot with that plan
</Do_Not_Use_When>

<Why_This_Exists>
AI can build anything. The hard part is knowing what to build. OMC's autopilot Phase 0 expands ideas into specs via analyst + architect, but this single-pass approach struggles with genuinely vague inputs. It asks "what do you want?" instead of "what are you assuming?" Deep Interview applies Socratic methodology to iteratively expose assumptions and mathematically gate readiness, ensuring the AI has genuine clarity before spendi

... (content truncated)

## See Also

- Original: https://github.com/Yeachan-Heo/oh-my-claudecode
- OMC Skills: `/home/dev/workspace/omc/skills/deep-interview/`
