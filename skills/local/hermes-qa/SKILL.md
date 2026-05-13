---
name: hermes-qa
description: End-to-end QA workflow for Hermes using browser, terminal, file, and vision tools. Use for validating web flows, reproducing UI bugs, gathering evidence, and optionally fixing then re-verifying.
version: 0.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [qa, browser, testing, bug-hunting, verification]
    related_skills: [systematic-debugging, requesting-code-review, plan]
---

# Hermes QA

Use this skill when the user wants a real workflow test of a web page, product flow, or UI behavior.

## Trigger phrases
- test this page
- verify this flow
- QA this feature
- reproduce this UI bug
- click through and check
- validate after deploy

## Goals
- Reproduce behavior in the browser, not by guesswork
- Gather concrete evidence: page state, console errors, screenshots when useful
- If the user wants fixes, implement the smallest safe fix and re-test
- End with a pass/fail summary and exact reproduction notes

## Primary tools
- browser_* tools for navigation, clicking, typing, snapshots, console, screenshots
- read_file/search_files/patch/write_file for code inspection and edits
- terminal for tests, builds, git diff, and local verification
- todo for multi-step QA runs

## Workflow
1. Clarify target only if necessary. If the URL, page, or expected behavior is obvious, start immediately.
2. Create a short todo plan when the QA involves multiple steps or flows.
3. Reproduce the flow in the browser.
4. Collect evidence:
   - browser_snapshot after important transitions
   - browser_console for JS/API errors
   - browser_vision if visual layout matters
5. If the task is report-only, stop at findings.
6. If the user wants fixes:
   - inspect relevant files
   - make the minimum safe change
   - run focused verification
   - re-run the browser flow
7. Report:
   - what was tested
   - what failed or passed
   - evidence collected
   - what changed, if anything
   - remaining risks

## Guardrails
- Do not claim a flow works unless you actually exercised it with tools.
- Prefer focused reproduction over broad wandering.
- If authentication or external credentials are missing, state that clearly and test what is still testable.
- For destructive actions in the UI, confirm before proceeding.
