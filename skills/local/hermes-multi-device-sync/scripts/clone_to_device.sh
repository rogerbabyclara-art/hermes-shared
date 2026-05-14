#!/bin/bash
# clone_to_device.sh — Phase 2 of hermes-multi-device-sync
# Run ONCE on a new device (after SSH key is added to GitHub and verified).
# Merges the GitHub-hosted shared portable bits into the existing ~/.hermes/
# without touching config.yaml, auth.json, sessions/, etc.
#
# Usage:
#   GITHUB_USER=<username> REPO=hermes-shared bash clone_to_device.sh
#
# Pre-checks:
#   1. ssh -T git@github.com returns "Hi $GITHUB_USER!"
#   2. ~/.hermes exists (i.e. hermes is already installed on this device)
#   3. config.yaml in ~/.hermes is already configured for this device

set -e

GITHUB_USER="${GITHUB_USER:?set GITHUB_USER, e.g. rogerbabyclara-art}"
REPO="${REPO:-hermes-shared}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
TMPDIR="/tmp/hermes-shared"

echo "==> Pre-flight"
ssh -o StrictHostKeyChecking=no -T git@github.com 2>&1 | head -2
test -d "$HERMES_HOME" || { echo "ERROR: $HERMES_HOME not found — install hermes first"; exit 1; }
test -f "$HERMES_HOME/config.yaml" || echo "WARN: no config.yaml in $HERMES_HOME — make sure to configure before running hermes"

echo "==> Backing up existing ~/.hermes"
BACKUP="$HOME/.hermes_backup_$(date -u +%Y%m%dT%H%M%SZ)"
cp -a "$HERMES_HOME" "$BACKUP"
echo "Backup: $BACKUP"

echo "==> Pre-trusting github.com"
mkdir -p ~/.ssh
ssh-keyscan github.com 2>/dev/null >> ~/.ssh/known_hosts
sort -u ~/.ssh/known_hosts -o ~/.ssh/known_hosts

echo "==> Cloning shared repo to $TMPDIR"
rm -rf "$TMPDIR"
git clone "git@github.com:${GITHUB_USER}/${REPO}.git" "$TMPDIR"

echo "==> Merging portable bits into $HERMES_HOME (config.yaml/auth.json untouched)"
rsync -a --delete "$TMPDIR/skills/"   "$HERMES_HOME/skills/"
rsync -a --delete "$TMPDIR/memories/" "$HERMES_HOME/memories/"
cp "$TMPDIR/SOUL.md" "$HERMES_HOME/SOUL.md"
[ -d "$TMPDIR/scripts" ] && rsync -a "$TMPDIR/scripts/" "$HERMES_HOME/scripts/"

echo "==> Converting $HERMES_HOME to a git checkout"
cd "$HERMES_HOME"
if [ ! -d .git ]; then
    git init -b main
    git remote add origin "git@github.com:${GITHUB_USER}/${REPO}.git"
fi
cp "$TMPDIR/.gitignore" "$HERMES_HOME/.gitignore"
git fetch origin main
git reset --hard origin/main   # safe: gitignored files (config.yaml etc.) NOT touched

echo "==> Verification"
test -f "$HERMES_HOME/config.yaml" && echo "  config.yaml: SAFE" || echo "  config.yaml: LOST (restore from $BACKUP)"
echo "  HEAD: $(git log --oneline -1)"
echo "  memories: $(ls memories/ | tr '\n' ' ')"
echo "  skills count: $(ls skills/ | wc -l)"
echo "  git status:"
git status -s

echo ""
echo "==> DONE."
echo "Next step: install ~/bin/hermes-sync (see templates/hermes-sync.sh)"
echo "          and add to crontab: */30 * * * * \$HOME/bin/hermes-sync >> \$HOME/.hermes/hermes-sync.cron.log 2>&1"
