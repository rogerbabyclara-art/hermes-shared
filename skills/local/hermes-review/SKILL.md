---
name: hermes-review
description: Review code changes in a git repo using diff inspection, targeted file reading, verification commands, and risk-focused reporting. Use before commit, push, or merge.
version: 0.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [code-review, git, verification, quality, risk]
    related_skills: [requesting-code-review, systematic-debugging]
---

# Hermes Review

Use this skill when the user asks for a review of local changes, a branch, a commit range, or a pull-request-like diff.

## Trigger phrases
- review this change
- review my diff
- check this PR
- look for risks
- audit these edits

## Goals
- Inspect the actual diff first
- Read the touched files in context
- Identify correctness, regression, security, and maintainability risks
- Report by severity with concrete file references

## Primary tools
- terminal for git status, git diff, git log
- read_file/search_files for surrounding context
- delegate_task for an independent review pass when useful
- todo for larger reviews

## Workflow
1. Get the diff:
   - prefer git diff --cached
   - else git diff
   - else compare recent commits if needed
2. If there is no diff, say so clearly.
3. Read the most important touched files around changed sections.
4. Check for:
   - logic bugs
   - edge cases and missing validation
   - broken assumptions and regressions
   - test gaps
   - obvious security issues
5. When the change is non-trivial, run or recommend targeted verification commands.
6. If useful, run an independent delegate_task review for a second opinion.
7. Report findings grouped by severity:
   - critical
   - high
   - medium
   - low
   - nit / suggestion

## Guardrails
- Do not approve code you did not inspect.
- Prefer exact evidence over vague style comments.
- Distinguish blocking issues from suggestions.
- If tests were not run, say that explicitly.
