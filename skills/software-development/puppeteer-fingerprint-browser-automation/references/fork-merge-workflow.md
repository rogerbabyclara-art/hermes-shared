# Fork/Merge Workflow for Automation Codebases

When the user maintains a "source" directory that they actively edit, and you maintain a "v2" fork with your enhancements, the two diverge fast. Here's the workflow that emerged from real sessions.

## Problem
- Source directory: `azure-auto-reg` (user edits directly, don't touch)
- Fork directory: `azure-auto-reg-v2` (agent's enhanced version)
- User edits source between sessions → v2 gets stale → merging gets messy

## Decision: Re-clone vs Incremental Patch

**Re-clone + selective merge** (preferred when source has many changes):
1. `rm -rf v2 && cp -r source v2` — fresh clone
2. Diff old v2 against source to identify your enhancements that are NOT in source
3. Apply only those enhancements to the fresh v2
4. Verify with grep/diff

**Incremental patch** (preferred when source has few isolated changes):
1. `diff source/file v2/file` to see divergence points
2. Identify source-side changes that v2 is missing
3. Apply source changes to v2 without clobbering enhancements
4. Harder to get right; risk of conflicts

## How to decide
- Count diff hunks: `diff src/flow.js v2/src/flow.js | grep '^[0-9]' | wc -l`
- If source changed in areas that DON'T overlap with your enhancements → incremental is safe
- If source changed in the SAME areas as your enhancements (e.g. both modified captcha handling) → re-clone is cleaner

## Verification checklist
After merging, grep for:
1. Your enhancement markers (comments like `// ★ Bug fix`)
2. Source-side new features (`progress.setBlocking`, new timeout values, etc.)
3. Source directory timestamps unchanged (confirm you didn't accidentally edit it)

## Forking an Electron companion app alongside the backend

When the automation project has an Electron desktop companion (e.g. `form-helper-app` for `azure-auto-reg`), fork it too:

1. **Copy the entire Electron project**: `robocopy /E form-helper-app form-helper-v2`
2. **Re-run `npm install`** in the copy — Electron binaries in `node_modules/electron/dist/` contain absolute path references that break on copy. `npm install` rebuilds them.
3. **Patch the data directory pointer** — find the line where the Electron app resolves the backend's data dir (e.g. `AZURE_REG_DIR = path.join(__dirname, '..', 'azure-auto-reg')`) and change it to point at v2.
4. **Update branding** — title in `main.js` (`BrowserWindow` title), `renderer/index.html` `<title>`, `package.json` name/version/description. This prevents confusion between v1 and v2 windows.
5. **Create a separate .bat launcher** — don't share a launcher with v1.

### Pitfall: Electron cannot launch from git-bash / MSYS2

`electron .` or `npm start` in an Electron project **crashes immediately** when run from git-bash:

```
TypeError: Cannot read properties of undefined (reading 'whenReady')
```

This happens because MSYS2's PTY handling breaks Electron's internal IPC. The same command works fine from cmd.exe or PowerShell. This is NOT a code bug — v1 exhibits the same crash from git-bash.

**Impact on Hermes agent**: the `terminal` tool in Hermes WebUI runs through git-bash, so you **cannot** launch or test Electron apps from the terminal tool. You must:
- Write a `.bat` file and tell the user to double-click it
- Or use `start "" cmd /c "cd /d D:\\Projects\\form-helper-v2 && npm start"` inside another .bat

### Pitfall: Electron app spawning child processes

If the Electron app spawns the runner as a child process (e.g. FormHelper's "Start Runner" button), the v2 copy needs its `AZURE_REG_DIR` correct or the child process will read/write v1's data files. Verify by:
1. Start the Electron v2 app
2. Check the Azure tab — it should show v2's tasks.json content (or empty if v2 hasn't run yet)
3. If it shows v1's data, the path pointer wasn't changed correctly

## Real example (2026-05-12)
Source directory added `progress.setBlocking/clearBlocking`, changed timeout to 6h, simplified `detectLoginStage` URL check. V2 had enhanced captcha check conditions, auto-click-次へ after captcha, includes-based prefecture matching. Re-cloned, applied 3 selective enhancements to the fresh clone. Total: 3 patches on flow.js, 0 on runner.js (source's runner changes were fine as-is).

FormHelper cloned to form-helper-v2: changed `AZURE_REG_DIR` (main.js L1160), title (main.js L370), index.html title, package.json metadata. npm install rebuilt 525 packages. Confirmed Electron won't launch from git-bash (v1 also fails same way) — created separate `启动FormHelper-v2.bat` for cmd.exe launch.
