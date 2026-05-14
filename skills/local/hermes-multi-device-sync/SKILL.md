---
name: hermes-multi-device-sync
description: Synchronize a user's Hermes home (`memories/`, `skills/`, `SOUL.md`, optional `scripts/`) across multiple machines (workstation + VPS + future hosts) using a private GitHub repo as the hub. Each device keeps its own `config.yaml`, `sessions/`, `auth.json`, `logs/`, `cron/`, and `state.db` — only the shared portable knowledge syncs. Use when the user runs Hermes on more than one machine and wants memory/skills mirrored, when setting up a backup/standby Hermes on a VPS, or when adding a third device to an existing sync setup.
when_to_use: setting up Hermes on a second/third device and wanting shared memories+skills; user mentions "synced Hermes", "backup Hermes", "main + standby", "把记忆同步过去", "Hermes 共享配置"; existing single-device user adding a VPS Hermes
version: 1.0.0
languages: bash, python
---

# hermes-multi-device-sync

When the user runs Hermes on more than one machine — typical pattern is workstation (development, interactive) + always-on VPS (cron jobs, Telegram bot, 24/7 services) + maybe a home server later — they want **the same memories, the same skills, the same SOUL.md** on all of them, without sharing API keys, sessions, or auth state. This skill is the complete recipe.

## Architecture

```
┌─────────────────────────┐         ┌─────────────────────────┐
│  Workstation (Win/Mac)  │         │   VPS (Ubuntu, 24/7)    │
│  HERMES_HOME=D:\..\     │         │   HERMES_HOME=~/.hermes │
│                         │         │                         │
│  ✓ memories/  (sync)    │         │  ✓ memories/  (sync)    │
│  ✓ skills/    (sync)    │         │  ✓ skills/    (sync)    │
│  ✓ SOUL.md    (sync)    │         │  ✓ SOUL.md    (sync)    │
│  ✗ config.yaml (local)  │         │  ✗ config.yaml (local)  │
│  ✗ sessions/  (local)   │         │  ✗ sessions/  (local)   │
│  ✗ auth.json  (local)   │         │  ✗ auth.json  (local)   │
└──────────┬──────────────┘         └──────────┬──────────────┘
           │                                    │
           │       git push/pull (SSH)          │
           └────────────┬───────────────────────┘
                        ▼
            ┌──────────────────────────┐
            │  GitHub (private repo)   │
            │  user/hermes-shared      │
            │  branch: main            │
            └──────────────────────────┘
```

- **Workstation** edits memories/skills interactively, pushes when done (or on cron).
- **VPS** auto-pulls every 30 minutes via cron, auto-pushes its own memory edits (if any) back.
- **GitHub private repo** is the single source of truth.
- **Each device's `config.yaml`** stays local — different `model`, `base_url`, `api_mode`, user IDs per device.

## What syncs vs what doesn't (critical to get right)

### MUST sync (the "portable brain")
- `memories/MEMORY.md`, `memories/USER.md` — the personal notes and user profile
- `skills/` — entire tree (SKILL.md + references + templates + scripts)
- `SOUL.md` — the persona file injected each turn
- `scripts/` — user-authored cron job scripts (rss_check, yt_check, etc.) if the user wants them on all devices

### MUST NOT sync (machine-local state and secrets)
- `config.yaml` — contains API keys, `base_url` (often device-specific), and per-device model preferences. **Different on each machine.**
- `auth.json`, `auth.lock`, `*.lock` — per-machine credentials
- `sessions/` — conversation history (each device has its own)
- `logs/` — runtime logs
- `cron/`, `cron.db` — cron job state (job IDs differ per device)
- `state.db`, `state.db-shm`, `state.db-wal` — local SQLite state
- `processes.json`, `pairing/`, `hooks/` — machine-bound runtime
- `cache/`, `audio_cache/`, `image_cache/`, `bin/`, `hermes-agent/`, `hermes-webui/`, `webui/`, `node/` — installed code/binaries (each device runs its own `hermes setup`)
- `.skills_prompt_snapshot.json`, `skills/.curator_state`, `skills/.usage.json`, `skills/.bundled_manifest`, `skills/.curator_backups/`, `.tirith-install-failed` — Hermes runtime caches and curator state (regenerate locally)

The exact `.gitignore` is in `templates/hermes-shared.gitignore`. **Copy it verbatim** when initializing.

## Setup procedure (workstation first, then each device)

### Phase 1 — Workstation: SSH key + GitHub repo + initial push

1. User creates a private GitHub repo (e.g. `<username>/hermes-shared`). Empty, private, no README.
2. Generate an SSH key on the workstation if one doesn't exist:
   ```bash
   test -f ~/.ssh/id_ed25519 || ssh-keygen -t ed25519 -N '' -C "hermes-workstation" -f ~/.ssh/id_ed25519
   cat ~/.ssh/id_ed25519.pub  # paste to GitHub → Settings → SSH keys
   ```
3. Title the key clearly (e.g. `Workstation-Roger`), Key type = **Authentication Key** (default; Signing Key is NOT needed).
4. Verify: `ssh -T git@github.com` → expect `Hi <username>!`.
5. Initialize the repo on the workstation:
   ```bash
   cd "$HERMES_HOME"           # e.g. D:\Projects\hermes-local
   git init -b main
   git config core.autocrlf false      # critical on Windows — see Pitfall 1
   git config user.email "<user>@users.noreply.github.com"
   git config user.name "<user>"
   git remote add origin git@github.com:<username>/hermes-shared.git
   ```
6. Write the `.gitignore` first (copy from `templates/hermes-shared.gitignore`).
7. Add, commit, push:
   ```bash
   git add .
   git commit -m "Initial commit: Hermes shared (memories + skills + SOUL)"
   git push -u origin main
   ```

### Phase 2 — Each additional device (VPS, second workstation, home server): clone + merge

Do NOT `rm -rf ~/.hermes && git clone …` — that nukes `config.yaml`/`auth.json`. The pattern is **clone to /tmp, rsync portable parts in, then convert ~/.hermes itself into a git checkout**:

1. Generate a device-specific SSH key, add to GitHub (different title, e.g. `VPS-HK2`):
   ```bash
   ssh-keygen -t ed25519 -N '' -C "hermes-vps-hk2" -f ~/.ssh/id_ed25519
   cat ~/.ssh/id_ed25519.pub
   ```
2. Verify: `ssh -T git@github.com` from the device.
3. Pre-trust github.com to avoid hostkey prompts:
   ```bash
   ssh-keyscan github.com >> ~/.ssh/known_hosts
   ```
4. Clone, merge, convert (full script in `scripts/clone_to_device.sh`):
   ```bash
   cp -a ~/.hermes ~/.hermes_backup_$(date +%Y%m%d)
   rm -rf /tmp/hermes-shared
   git clone git@github.com:<username>/hermes-shared.git /tmp/hermes-shared

   rsync -a --delete /tmp/hermes-shared/skills/   ~/.hermes/skills/
   rsync -a --delete /tmp/hermes-shared/memories/ ~/.hermes/memories/
   cp /tmp/hermes-shared/SOUL.md ~/.hermes/SOUL.md
   [ -d /tmp/hermes-shared/scripts ] && rsync -a /tmp/hermes-shared/scripts/ ~/.hermes/scripts/

   # Convert ~/.hermes itself into a git checkout (so future pulls are trivial)
   cd ~/.hermes
   [ -d .git ] || { git init -b main && git remote add origin git@github.com:<username>/hermes-shared.git; }
   cp /tmp/hermes-shared/.gitignore ~/.hermes/.gitignore
   git fetch origin main
   git reset --hard origin/main      # working tree == HEAD; config.yaml/auth.json untouched (gitignored)
   git status                         # should be clean except for .skills_prompt_snapshot.json (also ignored)
   ```

### Phase 3 — Automatic sync via cron (VPS or always-on device)

Install `~/bin/hermes-sync` (template in `templates/hermes-sync.sh`), then crontab `*/30 * * * *`. The script does:
1. `git pull --rebase origin main` (with reset fallback if rebase conflicts)
2. If `memories/`, `SOUL.md`, or `scripts/` changed locally, auto-commit and push back

Verify the first run by hand: `~/bin/hermes-sync && tail ~/.hermes/hermes-sync.log`.

## Critical pitfalls

### 1. Windows CRLF noise floods the first commit

On Windows, the first `git add .` of a 700-file Hermes home produces ~700 lines of `LF will be replaced by CRLF` warnings, drowning the actual output. Set `core.autocrlf false` **before the first `git add`** — Hermes skills and Python scripts should stay LF. Don't use `core.autocrlf=true` (the Windows default for git) or you'll mangle shell scripts that VPS Linux later runs.

```bash
git config core.autocrlf false   # do this RIGHT AFTER git init, before any git add
```

### 2. The `.gitignore` must also exclude curator caches under `skills/`

Hermes auto-generates `skills/.bundled_manifest`, `skills/.curator_state`, `skills/.usage.json`, and creates timestamped backups in `skills/.curator_backups/`. These will be `git add .`'d on the first push if your `.gitignore` only excludes top-level cache patterns. Add explicit `skills/.curator_state`, `skills/.usage.json`, `skills/.bundled_manifest`, `skills/.curator_backups/` lines. If you already pushed them, `git rm -rf --cached skills/.curator_backups skills/.bundled_manifest skills/.curator_state skills/.usage.json` + commit + push.

### 3. After `git init` on an existing populated dir, `git status` shows everything as "D" (deleted) until first commit lands

Symptom: you `git init`, set remote, `git fetch origin main`, then run `git reset --soft origin/main`. Status shows hundreds of files as deleted. This is because the index was empty and HEAD now points to a commit that has all those files — so files exist on disk and in HEAD but the index thinks they should be deleted. **Fix: `git reset --hard origin/main`** (working tree is already correct; we just want index to match HEAD).

This is safe because `config.yaml`, `auth.json`, `sessions/`, etc. are in `.gitignore` — `git reset --hard` will not touch them. **Always verify with `test -f ~/.hermes/config.yaml && echo SAFE || echo LOST`** after the hard reset.

### 4. `paramiko` long SSH session drops during VPS rsync/clone

The clone step in Phase 2 can take 30s-2min depending on skill count. paramiko sessions in a wrapping process (Hermes terminal tool, etc.) may drop. See `paramiko-remote-deploy` skill, Pitfall 6b — use fire-and-poll or short-command-batching. Don't try one giant exec_command for the whole Phase 2.

### 5. Don't sync `config.yaml` even though it's tempting

Users frequently ask "can't we just sync config.yaml too?" **No.** Different devices need different `base_url` (workstation hits local NewAPI :3000, VPS hits public :3002), different `provider` choices, different model preferences (gpt-5.4 vs gpt-5.3-codex), different `user_id` for cache stickiness. If a setting genuinely should be shared, put it in a small `config_shared.yaml` that each device sources/merges manually — but the main `config.yaml` stays per-device.

### 6. Don't sync `cron/` or cron job IDs

Each device's cron jobs have unique job IDs assigned by Hermes. If you sync `cron/cron.db`, both devices try to run the same jobs, double-sending Telegram messages and double-running scrapers. Cron jobs must be reinstalled per-device using the user's preferred cron skill (Hermes cron, or system crontab).

### 7. SSH keys are per-device, not shared

Generate a fresh ed25519 keypair on every device and add each public key to GitHub separately. Don't copy `~/.ssh/id_ed25519` between machines. Benefits: if one device is compromised, you revoke just that key without breaking the others. Title each GitHub SSH key by device (`Workstation-<user>`, `VPS-<region>-<role>`).

### 8. `git pull` clobbering local memory edits

If the workstation edits MEMORY.md while VPS auto-sync is mid-push, the next workstation `git pull` may conflict. The `hermes-sync` script uses `git pull --rebase` to minimize merge commits, plus a `reset --hard origin/main` fallback when rebase fails. Accept that **conflicts on MEMORY.md will lose VPS-side edits** — workstation is the authoritative editor. If you want VPS-side memory edits to win sometimes, the user must manually `git pull` on the workstation before editing.

## Verification checklist (after Phase 2 or Phase 3)

1. `cd ~/.hermes && git status` → clean (or only ignored runtime caches in "untracked").
2. `cd ~/.hermes && git log --oneline -1` → shows the same commit on both devices.
3. `test -f ~/.hermes/config.yaml && echo SAFE` on the new device → config.yaml survived.
4. `ls ~/.hermes/memories/` → MEMORY.md + USER.md present.
5. `ls ~/.hermes/skills/ | wc -l` → matches workstation's skill count.
6. From the VPS: `~/bin/hermes-sync && tail ~/.hermes/hermes-sync.log` → "Already up to date" first run.
7. Edit MEMORY.md on workstation, push, wait 30 min (or run `~/bin/hermes-sync` on VPS), confirm VPS sees the edit.
8. Hermes can still start on the new device: `hermes chat -q "ping"` returns a normal reply (config.yaml + memories both loaded).

## Skill structure

- `templates/hermes-shared.gitignore` — battle-tested .gitignore for `$HERMES_HOME` (excludes config.yaml, sessions, auth, runtime caches, curator state)
- `templates/hermes-sync.sh` — bash script for auto-pull + auto-push, drop in `~/bin/` and crontab `*/30 * * * *`
- `scripts/clone_to_device.sh` — full Phase 2 script: backup → clone → rsync merge → convert to git checkout → verify
- `references/three-way-sync-conflicts.md` — what to do when workstation + VPS both edit MEMORY.md concurrently (rare but real)

## Related skills

- `paramiko-remote-deploy` — for remote-driving the VPS Phase 2 from the workstation (SFTP, sudo, etc.)
- `hermes-context-recovery` — for resuming if a sync setup task is interrupted mid-way
