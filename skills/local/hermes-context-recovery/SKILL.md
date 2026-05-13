---
name: hermes-context-recovery
description: Safely resume interrupted or context-compressed Hermes tasks by verifying actual state, reconstructing missing context, and only then continuing.
version: 0.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [context-compression, resume, recovery, task-handoff, verification]
    related_skills: [hermes-investigate, plan]
---

# Hermes Context Recovery

Use this skill when a session was interrupted, compacted, or resumed with only a preserved todo list and partial context.

## Trigger phrases
- continue
- 继续
- pick up where we left off
- resume this
- active task list was preserved
- after context compression
- task list is here, continue

## Goals
- Recover the real current state before acting
- Distinguish verified facts from stale todo text
- Avoid blind or empty tool calls caused by missing context
- Ask the user only for the smallest missing identifier if tools cannot recover it

## Primary tools
- todo to read preserved task state
- terminal for pwd, git status, and live repo checks
- search_files/read_file for locating relevant files and confirming repo contents
- session_search when the missing context may live in a prior session
- skill_view for any domain skill that becomes relevant after recovery

## Workflow
1. Treat preserved todos as hypotheses, not proof of completion or current scope.
2. Reconstruct the actual environment first:
   - check current workspace/path
   - inspect whether this is a git repo and which repo it is
   - confirm whether the target files/repo already exist locally
3. Verify the task target before continuing:
   - repo URL or repo name
   - current local path
   - branch or checkout state if relevant
4. Search for concrete evidence of the requested artifact before claiming progress:
   - skill files
   - README
   - config/manifests
   - remote URL / git metadata
5. If context may be from an earlier session, use session_search with keywords from the task before asking the user to restate everything.
6. Summarize:
   - what is verified
   - what is missing
   - the exact next action once the gap is filled
7. Only then continue the original task.

## Guardrails
- Never trust a stale todo list over live evidence.
- Never send tool calls with missing required parameters.
- Do not claim a repo was cloned, inspected, or summarized unless the filesystem/git state confirms it.
- If the only missing fact is a single identifier (for example repo URL vs "use current workspace"), ask only for that one fact.
- Prefer a short verified recap over speculative continuation.
- **When the compaction summary says an Active Task is unfinished, and the user's next message reads like a new unrelated ask, treat it as ambiguous, NOT as a fresh task.** The user often types a short side-quest ("read this dir", "check that file") that is actually part of debugging the still-open task. Do the small literal thing if it's cheap and reversible, but in your reply make it explicit: "I did X you asked for. Was this meant to feed into the open task [Y]? Or are we switching focus?" — let the user steer. Going full depth on the literal ask without checking is how you drift away from real work and burn turns.

## Pitfall: literal-task drift after compaction
Symptom: compaction summary preserved an Active Task (e.g. "fix manual-takeover resume button"). User's next message is "读 D:\Some\Other\Project 这个目录" or similar. Agent dives in, reads the whole project, summarizes structure, asks "what do you want to do with V1?" User snaps back: "I didn't ask you to read V1, I asked you to fix the resume problem."

Why it happens: the literal request looked self-contained, so it bypassed the recovery check.

Fix: before executing a fresh-sounding request right after compaction, do a 1-line sanity check in your own reasoning — "is this related to the open Active Task?" If unclear, do the cheap part of what the user asked AND name the open task in your reply, so the user can correct you in one short message instead of after you've burned 5 tool calls.

### Specific high-risk pattern: multi-generation project trees (V1/V2/V3)

When the user has clearly versioned project directories sitting side by side (e.g. `azure-auto-reg` / `azure-auto-reg-v2` / `form-helper-v2`, or any `xxx-v1` / `xxx-v2` / `xxx-v3` triad), and the Active Task is happening in the **latest** generation, a request like "读 D:\Projects\xxx-v1 这个目录" is almost never "switch focus to V1". It is usually one of:

- "I want to reference V1's implementation of feature F while we're debugging V3"
- "Pull a specific module/file from V1 into V3"
- "Verify behavior X used to work in V1"

**Default behavior**: name the connection to the Active Task in your first reply. One of these openers:
- "Reading V1 — is this to compare against the current `microsoftLogin` issue in V3?"
- "Got it, scanning V1. Looking for anything specific (a function, an approach) related to [open task]?"

This costs you nothing if the user really did want a full V1 tour, but saves the whole turn when they didn't. The user's memory profile (look for entries like "**V1/V2/V3 都不动**" or "原 xxx 不动") is a strong signal that old generations are **reference-only assets, not edit targets**.

## Pitfall: claiming prior verification work without `session_search`

Symptom: user says "你之前不是检查过 X 吗，怎么又出问题" / "I asked you to check X already" / "didn't you already validate this". Tempting reaction is to apologetically agree ("you're right, I did check that"), or to deflect ("must be a sync issue"). Both are wrong if you have no actual evidence of having done it.

Why it matters: your visible context window only covers the current session post-compaction. Past work may live in earlier sessions you can't see — but that doesn't mean you DID it. Confabulating prior verification destroys trust ("你还号称长记忆") and leads to skipping the actual check now.

Correct response sequence:
1. **Run `session_search` with concrete keywords from what the user claims you did** (function names, file paths, error strings, serials). Single query, ≤3 results, just to confirm or deny.
2. **If no hit, say so plainly**: "Searched session history, no record of checking X. Either it was in a compacted-away context or it didn't happen. Either way, checking now." Do NOT promise it's in memory you can't see.
3. **If hit, cite the session/turn briefly** before continuing.
4. **Then run the actual verification** the user is asking about, with fresh tool calls — never just re-assert prior conclusions.

Don't write a long apology. The user wants the check redone, not a meditation on memory. One acknowledgment line + the actual probe is the right shape.

This also applies when YOU are tempted to write "I already verified X" in a reply without having done it in this visible session. If you can't point to a turn or a tool-call output that proves it, don't claim it.

## Useful recovery checklist
- `pwd`
- identify repo root and remote
- `git status --short --branch`
- locate candidate task files with search_files
- inspect README or manifest files
- load relevant skill once the domain is identified

## Example outcome
"I can continue, but first I verified that the current workspace is X and that the expected target repo/file is not yet confirmed. I need exactly one missing input: repo URL, repo name, or confirmation to use the current workspace."