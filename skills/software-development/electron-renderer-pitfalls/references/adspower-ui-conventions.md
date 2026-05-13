# AdsPower / MoreLogin UI conventions for multi-account browser managers

When the user says "按 ADS 思维做" (do it AdsPower style), they mean the conventions below. AdsPower and MoreLogin converged on the same idioms because users running 20-200 fingerprint browser profiles all need the same workflows. Diverging from these patterns generates pushback every time.

## Table column order (left to right)

```
☐ │ Seq │ Name │ Status │ IP·Region │ Tags │ Latest event │ User notes │ Last opened │ Actions
```

Reasoning:
- Checkbox first — multi-select is the primary interaction at scale
- Seq number (auto, padded `001-100`) — quick visual count, NOT the account identity
- Name — the actual account identity (e.g. `azure-589`)
- Status — single colored pill, no multi-state mess
- IP/Region — combined cell with IP id + last-tested geo subtitle
- Tags — colored chips, click `+` to add, click `×` on chip to remove
- **Latest event** ≠ **User notes**. Two separate columns. Backend events go in events column, user types only into notes column. NEVER cross-contaminate.
- Last opened — `fmtAgo()` timestamp, helps user spot stale profiles
- Actions — narrow right-aligned column with icon buttons

## Status pill states

| State | Color | Icon | When |
|---|---|---|---|
| `● Open` | `#56d364` (green) | bullet | Browser process alive |
| `🔒 Locked` | `#d29922` (yellow) | lock | `lock_status=in_use` but no live process (rare; usually a stale lock) |
| `Idle` | `#8b949e` (gray) | — | Default state |

Implementation: when browser child process exits (any reason — user closed window, crash, kill), automatically `clearLock()` and append `closed` event. Then "Locked but not Open" should almost never happen in practice; if it does, it indicates a sync bug.

## Action buttons (one-click, no modal)

| Button | Icon | Behavior |
|---|---|---|
| Open | `▶` | Lock + launch browser. No confirm. |
| Close | `⏹` | Kill browser + unlock. No confirm. |
| Test proxy | `测` / `Test` | Run IP check via main-process fetch (not in browser). Result → events log, not notes. |
| Replace IP | `🔁` | **Keep confirm** — destructive (marks old IP dead). |
| Delete account | `🗑` | **Keep confirm** — destructive. |

**Rule:** Confirm modals ONLY for destructive irreversible ops. Everything else is one-click.

## Tag chips with color presets

Default 10 presets (Chinese context — Azure account registration workflow):

```js
[
  { name: "已注册",   color: "#2ea043" },  // green
  { name: "注册中",   color: "#1f6feb" },  // blue
  { name: "注册失败", color: "#f85149" },  // red
  { name: "已充值",   color: "#a371f7" },  // purple
  { name: "已实名",   color: "#79c0ff" },  // sky blue
  { name: "已绑卡",   color: "#56d364" },  // light green
  { name: "风控",     color: "#d29922" },  // amber
  { name: "封号",     color: "#6e1414" },  // dark red
  { name: "待跟进",   color: "#bc8cff" },  // lavender
  { name: "VIP",      color: "#ffa657" },  // orange
]
```

Render style: semi-transparent fill + solid border using the same color.
```css
background: ${color}1f;   /* alpha 12% */
border: 1px solid ${color};
color: ${color};
```

Provide a `⚙ Tag presets` settings modal where user can rename, recolor, add, remove.

## Batch action bar

Appears when ≥1 row selected. Sticks to top of table. Pattern:

```
[● 5 selected] [▶ Batch Open] [⏹ Batch Close] [🏷 Add Tag] [✂ Remove Tag]
[📝 Set Note] [🗑 Batch Delete] [✕ Cancel selection]
```

- Batch Open: concurrency 5, 600-800ms jitter, auto-lock each. Shows live progress in button text (`Opening 3/20`).
- Batch Close: kill processes + unlock + clear `_running` flag.
- Add/Remove Tag: opens the chip picker modal, applies to all selected.
- Set Note: opens the input modal — **but this is the ONLY case where bulk-overwriting notes is acceptable**, because it's an explicit user action on selected rows.
- Batch Delete: confirm modal showing count.

## Search / filter

Single search box, debounced 120ms, matches across:
- Account name
- Tags
- User notes
- IP host:port
- Last-tested IP
- Last-tested geo
- Linked CSV serial

Plus a `☐ Only show open` checkbox for quick filter to running profiles.

## User notes vs event log — the critical distinction

This is the convention users get angriest about when violated.

| Column | Source | Mutability |
|---|---|---|
| **User notes** | Only user typing into the input | Only via explicit user edits |
| **Event log** | Backend appends every state transition | Append-only, capped at 100 entries |

**Concrete rule:** If your backend handler is tempted to write `account.notes = (account.notes || "") + " [tested OK]"` — STOP. That goes in `account.events.push({ts, kind, msg})`.

Event kinds to support:
- `opened` — browser launched, include IP/region in msg
- `closed` — browser exited, include exit code
- `test-ok` — proxy test passed, include resolved IP
- `test-fail` — proxy test failed, include error
- `replace-ip` — IP swapped, include old → new
- `error` — anything else worth logging

In the table row, show only the **latest** event (truncated to ~40 chars) plus "N events total". Make the cell clickable → opens a modal with full history (scrollable list) plus a `🗑 Clear events` button.

## Row inline edit (notes only)

Double-click the notes cell → swap to `<input>`. Enter saves, Esc cancels, blur saves. Do NOT support inline-edit on:
- Name (changing it would break IP binding references)
- Tags (chip UI is more appropriate)
- Anything backend-owned

## Browser window identification (when 20 windows are open)

When user opens 20 profiles at once, the Windows taskbar is a sea of identical Chromium icons. Mitigations:
- Inject a custom `<title>` like `[C001] {original-title}` via `page.evaluateOnNewDocument`
- Optionally inject a favicon angle badge (colored corner with the seq number)
- Both behind env vars `SERIAL` / `BADGE_COLOR` so they're easy to toggle

This is opt-in — users who prefer pure AdsPower experience can turn it off. But keep the code, since the painful "which window is which" problem hits everyone eventually.

## What NOT to add

These were repeatedly rejected by the user:
- ❌ "Group" / "Workspace" hierarchy — flat list with tags is enough
- ❌ "Platform" column — tags handle this
- ❌ Quick-status buttons like `[✓ Done] [✗ Failed]` — use tags instead, keeps UI clean
- ❌ Rename via double-click on name — too risky for binding integrity
- ❌ Confirm modals for lock/unlock/open/close — one-click only
- ❌ Auto-navigate to `ipinfo.io` on launch — default to `about:blank`

## Color palette (dark theme, matches GitHub dim)

```
--bg-canvas:    #0d1117
--bg-surface:   #161b22
--bg-elevated:  #1f262e
--border:       #30363d
--border-soft:  #21262d
--text-primary: #e6edf3
--text-muted:   #8b949e
--text-dim:     #6e7681
--accent:       #58a6ff   (links, focus rings)
--success:      #56d364
--warning:      #d29922
--danger:       #f85149
--purple:       #a371f7
```
