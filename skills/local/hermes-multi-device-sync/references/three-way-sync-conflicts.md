# Three-way sync: handling concurrent edits

## The problem

Workstation and VPS can both edit syncable files between sync intervals:

- Hermes auto-edits `memories/MEMORY.md` and `memories/USER.md` during normal chat (memory tool calls).
- User edits `SOUL.md` or skills on the workstation manually.
- VPS may auto-edit `memories/MEMORY.md` if running its own Hermes (Telegram bot, cron-driven agent).

With `cron */30` on VPS and ad-hoc commits on workstation, conflicts are rare but real.

## Conflict matrix

| Workstation state | VPS state | Outcome with `git pull --rebase` |
|---|---|---|
| Clean | Clean | No-op. |
| Has unpushed commits | Clean | Workstation push goes through. VPS picks up next cron. |
| Clean | Has unpushed commits | VPS push goes through. Workstation picks up next pull. |
| Has unpushed commits to **different files** | Has unpushed commits to **different files** | Rebase succeeds, both sides merge cleanly. |
| Has unpushed commits to **same file** (e.g. MEMORY.md) | Has unpushed commits to **same file** | Rebase fails. `hermes-sync.sh` falls back to `git reset --hard origin/main` — **VPS-side edits to that file are lost**. |

## Why we let VPS-side edits lose

1. The workstation is where the user actually edits files. VPS-side memory edits are mostly auto-generated runtime notes ("user said X today") — losing them rarely matters.
2. The alternative (manual conflict resolution per cron run) is unworkable for an unattended VPS.
3. If a particular VPS-side edit really matters, the user can `git pull` on the workstation before editing.

## When VPS-side edits DO matter (escape hatch)

If the user runs a long-term VPS-driven Hermes (Telegram bot conversing for hours) and wants those memories preserved:

1. Switch the workstation workflow to **pull before edit**:
   ```bash
   cd $HERMES_HOME && git pull --rebase origin main
   # then edit MEMORY.md / use Hermes / make commits
   git push origin main
   ```
2. Cron the workstation's auto-push at a high frequency (e.g. every 5 min) so VPS sees workstation edits quickly.
3. Avoid editing MEMORY.md manually on the workstation during long VPS sessions. Use Hermes' memory tool from the side you're on, not both at once.

## Recovery if a conflict already destroyed VPS edits

The `hermes-sync.log` and reflog can usually retrieve them:

```bash
cd ~/.hermes
git reflog --all | head -20            # find the pre-reset commit SHA
git show <sha>:memories/MEMORY.md      # see the lost content
# manually merge what you want back into current MEMORY.md, commit, push
```

The `hermes-sync.sh` log records every commit and reset, so even week-old VPS edits can be recovered as long as git GC hasn't run (default 90 days).

## Future work

If the user accumulates 3+ devices, this naive last-writer-wins model breaks down. Options at that point:
- Switch to an **append-only memory log** (one file per session, never edited) instead of a single MEMORY.md, with a periodic compaction job that runs only on the workstation.
- Use a CRDT-backed sync layer (Yjs, Automerge) — overkill for now.
- Designate one device as "memory primary" — others can read but never write MEMORY.md.

For 2 devices (workstation + VPS) the current scheme is fine.
