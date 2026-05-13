---
name: hermes-ship
description: Pre-ship verification workflow for Hermes. Check git state, run the project's relevant tests/build/lint commands, review the diff, and decide whether the changes are ready to commit, push, or open a PR.
version: 0.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [ship, pre-commit, release, verification, git]
    related_skills: [requesting-code-review, hermes-review, plan]
---

# Hermes Ship

Use this skill when the user wants a release-readiness or pre-commit/pre-PR check.

## Trigger phrases
- ship this
- can I commit this
- can this go out
- prepare this for PR
- preflight this change
- make sure this is ready

## Goals
- Determine whether the current work is ready to ship
- Run the most relevant checks actually available in the repo
- Review the current diff and git state
- Produce a clear go / no-go verdict with next actions

## Primary tools
- terminal for git, tests, lint, typecheck, build
- read_file/search_files for project scripts and CI hints
- delegate_task for independent review when useful
- todo for multi-stage checks

## Workflow
1. Inspect repo state with git status and git diff.
2. Discover likely verification commands from package files, Makefile, CI config, or project docs.
3. Run the most relevant available checks, such as:
   - tests
   - lint
   - typecheck
   - build
4. Perform a concise review of the current diff.
5. Decide:
   - GO: ready to commit / push / PR
   - NO-GO: specific blockers remain
6. If the user wants, help with:
   - commit message
   - PR summary
   - checklist of remaining actions

## Report format
- Repo state
- Commands run and results
- Review findings
- Verdict: GO or NO-GO
- Recommended next command or action

## Guardrails
- Never claim ship readiness without running at least the key available checks.
- If a repo has no tests or no build, say that explicitly.
- Separate hard blockers from optional improvements.
- Do not push or commit automatically unless the user asks.
