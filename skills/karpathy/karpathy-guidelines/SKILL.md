---
name: karpathy-guidelines
description: Behavioral guidelines to reduce common LLM coding mistakes. Use when writing, reviewing, or refactoring code to avoid overcomplication, make surgical changes, surface assumptions, and define verifiable success criteria.
license: MIT
---

# Karpathy Guidelines

Behavioral guidelines to reduce common LLM coding mistakes, derived from [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on LLM coding pitfalls.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### Code-porting / migration trap: don't carry forward logic the new environment doesn't need

When porting code between projects (V1→V2→V3, library upgrades, framework
swaps), the source may contain "smart" logic that solved a problem in the
old environment but is **wrong** in the new one. The most common form:
auto-allocation / fuzzy-matching / auto-binding logic that papered over a
sloppy data model in the source project.

Example pattern (real session, V2→V3 Azure auto-reg port):

- V2 CSV had arbitrary `serial` values (`1036`, `test001`, `456`) so the
  runner had a "pick any unused row" auto-binder.
- V3 CSV was deliberately renamed so `serial` literally equals the browser
  profile name (`C001`..`C100` ↔ `C001`..`C100`).
- I ported the V2 auto-binder verbatim. It silently bound `C001` to
  `test001` (first qualifying row) and wrote the bad pairing back to disk.
- User reaction: *"为什么会自动绑 test001？C001-C100 对应 C001-C100，这个很难嘛？"*

The V3 environment **needed only Tier-1 same-name direct match**. The V2
auto-binding tier was not "extra flexibility" — it was a footgun that
silently overrode the operator's intentional naming.

Rules:

- Before copying any "smart fallback" path from the source, ask: *was this
  needed because the source data was messy, or because the problem
  fundamentally requires it?* If the new data model is clean, the fallback
  is now wrong.
- "Flexibility you don't need = silent footguns you can't see." Strip
  unnecessary tiers; let the simple path fail loudly with a clear error.
- When in doubt, **error loudly** instead of guessing. `return { error:
  'no match for X' }` is always safer than silently picking something
  plausible.
- If you must keep a fallback for genuine pool-allocation cases, make it
  **explicit and operator-triggered** (a separate button, a CLI flag) — not
  a silent default inside the hot path.

Audit method after a port:

```bash
# List every fallback / auto-* / default-pick branch
grep -nE "auto.?(bind|allocate|pick|match)|fallback|find\(.*=>.*\)|filter" src/ported.js
```

For each hit: justify it against the new data model, or delete it.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
