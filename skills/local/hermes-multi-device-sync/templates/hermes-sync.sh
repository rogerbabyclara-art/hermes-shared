#!/bin/bash
# hermes-sync — bidirectional sync between $HERMES_HOME and origin/main on GitHub.
# Drop in ~/bin/hermes-sync, chmod 755, then crontab:
#   */30 * * * * /home/<user>/bin/hermes-sync >> /home/<user>/.hermes/hermes-sync.cron.log 2>&1
#
# Behavior:
#   1. git pull --rebase origin main (with reset --hard fallback if rebase conflicts)
#   2. If memories/, SOUL.md, or scripts/ have local changes, auto-commit + push back
#
# Safe to run by hand any time. Logs to ~/.hermes/hermes-sync.log.

set -e
cd "$HOME/.hermes"
LOG="$HOME/.hermes/hermes-sync.log"
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) sync start ===" >> "$LOG"

# Pull (rebase) — fall back to hard reset on conflict
git pull --rebase origin main >> "$LOG" 2>&1 || {
    echo "PULL FAILED, aborting rebase and hard-resetting to origin/main" >> "$LOG"
    git rebase --abort 2>/dev/null || true
    git fetch origin main >> "$LOG" 2>&1
    git reset --hard origin/main >> "$LOG" 2>&1
}

# Stage local changes to syncable paths
git add memories/ SOUL.md scripts/ 2>/dev/null || true

# If there's something staged, commit and push
if ! git diff --cached --quiet; then
    git commit -m "Auto-sync from $(hostname): $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG" 2>&1
    git push origin main >> "$LOG" 2>&1 && echo "PUSHED" >> "$LOG"
fi

echo "=== sync end ===" >> "$LOG"
