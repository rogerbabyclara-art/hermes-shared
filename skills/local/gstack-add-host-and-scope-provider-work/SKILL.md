---
name: gstack-add-host-and-scope-provider-work
description: Investigate and extend gstack's host registry safely, and distinguish host-install config from actual model/provider configuration.
version: 0.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [gstack, host-config, typescript, provider-scope, investigation]
---

# gstack: add a host and separate host work from provider/model work

Use this when working in `/root/workspace/gstack` and the request mentions adding or switching an agent/host name (for example `roger`) and also mentions models/providers (for example `gpt-5.4`).

## Core lesson
In gstack, `hosts/*.ts` is a declarative registry for agent/host integration and skill generation paths. It does **not** by itself define live model/provider/base_url/API-token behavior. So first determine whether the request is:
1. "add a new gstack host" or
2. "make a real provider/platform list/use a model"

Do not assume those are the same task.

## Verified files and roles
- `hosts/index.ts` — host registry; adding a host requires import + registry + re-export
- `scripts/host-config.ts` — `HostConfig` type + validation rules
- `scripts/host-config-export.ts` — host listing/get/detect/validate/symlinks CLI
- `docs/ADDING_A_HOST.md` — authoritative workflow for adding a host
- `.gitignore` — must include the generated `.<host>/` directory
- `test/host-config.test.ts` — may contain hard-coded host-count assertions and named re-export checks
- `README.md` — host table and install docs may need updating

## Fast investigation workflow
1. Confirm repo and branch:
   - `git rev-parse --show-toplevel`
   - `git status --short --branch`
2. Confirm whether the target host already exists:
   - search filenames for `*roger*`
   - search contents for `ROGER|Roger|roger`
3. Read these files first:
   - `hosts/index.ts`
   - `scripts/host-config.ts`
   - `scripts/host-config-export.ts`
   - `docs/ADDING_A_HOST.md`
   - one nearby host implementation such as `hosts/slate.ts` or `hosts/hermes.ts`
4. Check tests and docs for hard-coded host counts or host lists:
   - especially `test/host-config.test.ts`
   - `README.md`
5. Separately search for true model/provider plumbing before claiming host edits will make a model available:
   - search for `gpt-5.4`, `listModels`, `fetchModels`, `availableModels`, `base_url`, `provider`

## What “add a new host” usually requires
When the target host does not already exist, the minimum likely changes are:
1. Create `hosts/<host>.ts` using `hosts/slate.ts`, `hosts/opencode.ts`, or `hosts/hermes.ts` as template
2. Update `hosts/index.ts`
3. Add `.<host>/` to `.gitignore`
4. Update `README.md` host table
5. Update tests, especially if they assert exact host count or specific named exports
6. Validate with:
   - `bun run scripts/host-config-export.ts validate`
   - relevant Bun tests

## Critical pitfall
If the user also asks that a model like `gpt-5.4` can be "pulled" or listed, do **not** promise success from host-registry edits alone.

Reason: the host config system controls skill installation, generation, rewrites, and host detection. It does not automatically create real provider connectivity. For actual model availability you still need the real platform details, typically one or more of:
- CLI binary name
- API/base URL
- auth env var/token name
- exact upstream model identifier
- model-list endpoint or protocol

## Decision rule to use with the user
After investigation, frame the next step as one of two paths:
- Path A: "ROGER is just a new gstack host name" → proceed with host-file/index/tests/README changes
- Path B: "ROGER is a real provider/platform" → require the actual API/CLI/auth/model details before attempting provider/model verification

## Signals that the host system is the one you found
You are in the correct subsystem if you see:
- `HostConfig` objects with fields like `globalRoot`, `localSkillRoot`, `hostSubdir`, `pathRewrites`, `toolRewrites`, `runtimeRoot`
- `ALL_HOST_CONFIGS` / `ALL_HOST_NAMES`
- validation around host names, paths, and linking strategy
- test coverage asserting host counts and registry behavior

## Good final summary pattern
State explicitly:
- whether the repo already contains the requested host
- which files define the host registry
- whether model/provider wiring was found or not
- what exact missing information is required for real model pull/list verification
