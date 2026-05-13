# Account Management Panel UX (AdsPower / MoreLogin Style)

When building an Electron / desktop UI that manages 20–200 stealth-browser profiles, the user expects an **AdsPower-style** interaction model. The architectural reference (`multi-account-proxy-binding.md`) tells you the data shape; this file tells you how the UI on top of it should behave.

Operators (the user's team) run 10–30 browser windows at once. Anything that costs them an extra click per profile costs them 30 clicks per task. The whole design pressure is "remove friction from bulk operation".

## Hard rules (these will get corrected if you violate them)

1. **No confirm dialogs for routine actions.** `[▶ 打开]`, `[⏹ 关闭]`, `[测试]`, `[换IP]` — all of these must be one-click. The user explicitly compared to AdsPower / MoreLogin: those tools never ask "are you sure you want to open?". Only keep `confirm()` on **destructive irreversible** actions: delete account, delete IP, bulk delete.

2. **No modal between intent and action for the happy path.** A previous design used a "▶ 开始使用 → 输入本次用途备注 → [🔒 锁定并启动浏览器]" modal. The user killed it: "这个地方没有必要，按 ADS MoreLogin 那种思维就行". Replace such modals with direct action. If you think a piece of metadata "should" be collected at start-time, you're wrong — collect it after the fact via a separate column that the user can tag/edit when they care to.

3. **Never auto-write into user-owned freeform fields.** The `notes` (备注) column is for the operator's own text. Do NOT append `[换IP @ 2026-05-13]` to it on system events. Do NOT add `[测试 OK 37.x.x.x]`. The user said: "备注栏信息只能我手填，不要因为其他事件发生了影响我自己的备注信息". For system events, add a **separate event log column** (`events` / `事件`) that shows the latest event only, with double-click opening a full history modal. The notes column is sacred user territory.

4. **No default external start-page** like `https://ipinfo.io/` or any verification site. The user complained: "这个就去掉吧，老是不显示，还影响判断". Two reasons it bites you: (a) when the proxy is slow or in handshake retry, the page hangs and the operator can't tell whether the profile is broken or just loading; (b) the operator usually wants to open and immediately navigate to the actual work target, so a forced ipinfo redirect costs them a tab close. **Default to `about:blank`.** If you want to provide IP verification, put it as an explicit `[测试]` button per row, not as the launch URL.

5. **Process exit must sync UI state.** When the user closes the browser window manually (clicks the OS [×]), the child process exits, and your `child.on('exit', ...)` handler MUST also clear the account's `lock_status` (set back to `idle`) and reset `lock_started_at`. Otherwise the table keeps showing 🔒 锁定 on a profile that has no browser running, and the operator can't tell what's actually open. The user caught this: "已经关闭的窗口还显示锁定，会不会影响判断". Don't only clear `ACTIVE_BROWSERS` — clear the persisted lock too.

## Layout (the canonical AdsPower clone)

```
┌────────────────────────────────────────────────────────────────────────┐
│ [🔄] [📦 批量建] [+ 单加]  [🔍 搜索框]  ☐ 仅看已打开    N 个 · M 已打开 │
├────────────────────────────────────────────────────────────────────────┤
│ (出现条件: selected.size > 0)                                          │
│ 已选 5 个 [▶ 批量打开] [⏹ 批量关闭] [🏷 标签] [📝 备注] [🗑 删] [✕]    │
├────────────────────────────────────────────────────────────────────────┤
│ ☐│ # │名称 │状态     │IP·地区          │标签       │备注 │上次打开│操作│
├────────────────────────────────────────────────────────────────────────┤
│ ☐│001│C001 │● 已打开 │ip-001 37.19...  │azure ×    │...  │2分前   │... │
│  │   │     │         │JP/Tokyo/Datacamp│ 已注册 ×  │     │        │    │
└────────────────────────────────────────────────────────────────────────┘
```

### Required columns (in this order)
- **Checkbox** — row multi-select. Click toggles `selected` set.
- **# (index)** — `001`, `002`, ... padded 3 digits. Operator uses this as visual anchor, NOT as identity.
- **Name** — the profile identifier (e.g. `C001`). The user's own naming scheme — don't try to merge it with another scheme (CSV serial etc.).
- **Status** — single pill: `● 已打开` (green) / `🔒 锁定` (yellow) / `空闲` (gray). One element, three states. Don't show two badges side-by-side. Running implies locked, so running > locked > idle in display priority.
- **IP · Region** — show the bound IP id, last-tested IP, and `JP/Tokyo/ASN/ISP`. Two lines is fine. Clicking the IP id jumps to the IP-pool sub-tab and flashes the corresponding row.
- **Tags** — chip-style multi-tags. `+` button at end to add. `×` on each chip to remove. Empty state: `—`. **Provide at least 10 preset colors** assigned deterministically by hashing the tag string (so `已注册` is always the same color across all rows). Do NOT make the user pick a color per tag.
- **Notes** — single-line truncated text. Click to edit inline (input replaces cell), Enter saves, Esc cancels. Empty state: italic gray "点击添加备注".
- **Last opened** — `2分前` / `1小时前` / `—`. Auto-updated when `proxyOpenBrowser` succeeds. This column is read-only.
- **Actions** — row-level buttons. Right-aligned. The visible primary button toggles by state: `[▶ 打开]` when idle, `[⏹ 关闭]` when running. Plus `[测]` `[🔁]` `[🗑]`.

### Selection model
- **Per-row checkbox** in column 1.
- **Header checkbox** for "select all currently filtered/visible". Not "select everything in DB" — that's a footgun with 200+ rows. Use `indeterminate` state when partial.
- **Batch bar appears/disappears** based on `selected.size > 0`. Don't make it a permanent toolbar — it eats vertical space when not needed.
- **Shift+click on a row checkbox = range select.** This is non-negotiable — every spreadsheet-like UI has it (Excel, AdsPower, Gmail) and operators muscle-memory it. Without it, selecting rows 5-20 is 16 clicks; with it, 2 clicks. Implementation: track `lastSelectedName` (the name of the last individually-clicked checkbox); on `click`, if `e.shiftKey && lastSelectedName && lastSelectedName !== name`, find both indices in the **currently filtered/visible** list (not the full DB list — Shift+click within the filtered view is what users expect), iterate inclusive range, set every checkbox to the **current click's `checked` state** (so Shift+click can both bulk-select AND bulk-deselect), then re-render the whole table to sync all the `<input type=checkbox>` DOM states + row-highlight classes. Always update `lastSelectedName` to the just-clicked row, including in the Shift+click branch (otherwise consecutive Shift+clicks pivot around a stale anchor). **Pitfall**: Shift+click on text-bearing cells (`user-select: text` on name / IP / notes columns) makes the browser select a giant black-highlighted text range across N rows because Shift extends the document selection. Add `try { window.getSelection().removeAllRanges(); } catch (_) {}` as the first line of the Shift+click branch. **Ctrl+click toggling** is a nice-to-have but not required — every checkbox click already toggles, so Ctrl just lets the user click anywhere on the row (not just the checkbox); add it only after Shift is in.

### Search and filter
- **One search box** that matches against name, tag, notes, IP, geo, linked CSV serial — anything textual. Debounce 100–150ms.
- **`☐ 仅看已打开` checkbox** for the most common operational filter (the user is mid-task and wants to see only what's running). Do not add 5 more filter checkboxes — they go unused and add visual noise.

### Inline editing
- **Double-click** the notes cell → replace with `<input>`, focus, select-all. Enter or blur = save (call `proxyBatchUpdate([name], { notes: v })`). Esc = abandon.
- **Do NOT allow inline-edit of the name** unless you also have a backend rename handler that updates all IP `bound_to` references atomically. Otherwise show a toast: "名称暂不支持改 (会破坏 IP 绑定)".

### Tag chip interaction
- Click `+` → prompt() for new tag → add. (Prompt is fine here; it's per-tag-per-account.)
- Click `×` on chip → remove that tag from that account immediately, no confirm.
- Batch operations from the batch bar:
  - `[🏷 加标签]` — prompts once, applies `add_tag` to all selected.
  - `[✂ 去标签]` — prompts once, applies `remove_tag` to all selected.

### Tag preset management modal (the "add/delete/recolor tags" panel)

When operators have a fixed vocabulary of tags (`VIP`, `已注册`, `待清理`, `实测中`, ...) they want one place to manage that vocabulary instead of typing free-form every time. This is a separate `[🏷 标签管理]` button in the top toolbar — distinct from the per-row tag chip `+` button. Rules:

1. **Toolbar entry button must be solid (not `ghost`).** Operators repeatedly missed the `ghost`-styled "⚙ 标签预设" button — it looked like dimmed disabled text — and asked "where's the tag management UI?" *to the AI*. If it's an essential feature, it gets a solid `compact` style with a clear emoji label like "🏷 标签管理". `ghost` styling is for tertiary/diagnostic actions, not core features.

2. **Provide a color-chip quick-pick row inside the modal.** Native `<input type="color">` opens the OS color picker, which is overkill for "pick from our 9 brand-consistent tag colors". Lay out 6–10 small (~22×22px) rounded color swatches above the picker, each `data-color="#hex"`, with hover+active states. Clicking a swatch sets the `<input type="color">` value AND toggles an `.active` class on the chosen swatch for visual feedback. This is what the user means by "可以添加内容颜色, 内容可删可加" — they want palette-style picking, not OS color wheel every time. Recommended palette (covers the common semantic axes): green `#2ea043` / blue `#1f6feb` / purple `#a371f7` / yellow `#f5c842` / orange `#fb8500` / red `#f85149` / cyan `#39c5cf` / pink `#ff7eb6` / gray `#8b949e`.

3. **Inline edit existing tag rows.** Each existing preset is a row with editable name input, editable color input, and `[删]` button. Edits save on `change` event (debounced if needed), no separate "save" button. This is the same UX pattern as the notes inline-edit.

4. **Re-render the account table after any preset change.** Changing a preset color changes how the chip looks across all rows. Call `renderAccounts()` after every modal mutation.

### Search and filter
- Concurrency 5 (not 1, not 20). The user runs ~20 windows; 5 parallel keeps the IO + proxy handshake spread out without overwhelming the residential proxy provider.
- Inter-launch jitter 600–800ms. Without it, a vendor like 711proxy will rate-limit the second/third connection.
- **Show live progress** by polling `proxyList()` every 1.5s during the batch and updating the button: `"打开中 3/20"`. The handlers themselves don't need a progress channel; polling is good enough and resilient to single-step failures.

## Optional column: Events (system event log, distinct from notes)

When you need to record system-generated events (test result, IP replacement, login success/failure) without polluting `notes`:

- Add an `events: []` array to the account schema, capped at e.g. 50 entries.
- Each event: `{ ts: <unix>, kind: "test_ok" | "test_fail" | "ip_replaced" | ..., msg: "37.19.x.x JP/Tokyo" }`.
- Display column shows **only the latest** event, truncated. Double-click opens a modal showing the full timeline.
- This is the answer to "I want to see what happened to this profile without you touching my notes".

## What NOT to add (until asked)

These were explicitly declined by the user; don't speculatively build them:
- Groups / folders. ("分组先不做")
- Per-account "platform" field (Facebook / Twitter / Azure / ...). ("平台也不做")
- Favicon labels / window-title injection in the BROWSER itself (separate skill — see `multi-window-visual-labeling.md`). The user wants management UI to be AdsPower-like, but does NOT want the browser windows themselves visually modified — too invasive, looks like a bot.
- Auto-status badges (`✓ 完成` / `✗ 失败`) on every event. User said "后面如果有状态按钮要加再告诉你". Wait for the ask.

## Implementation footnotes

- **Persisted lock + in-memory ACTIVE_BROWSERS must stay in sync.** Whenever you mutate one, mutate the other. The single most common UI bug in this class of app is "table says locked, but no Chromium running" or vice versa. Always update both in the same handler. On `child.on('exit')`, you don't know whether exit was user-initiated (window closed) or crash — treat both the same: clear lock_status, clear lock_started_at, leave notes/tags/events untouched.
- **Don't put confirm on `🔁 换IP`.** Yes, it marks the old IP `dead`. But the user has a reserve pool exactly for this. The whole point of the button is rapid failover; gating it behind a dialog defeats it. The user explicitly removed the confirm in mid-session.
- **Keep confirm on delete-account and delete-IP.** These are the only routine actions that are irrecoverable from the UI. The user did NOT ask to remove these confirms.

## Validation checklist before showing the user

- [ ] Single-click `[▶ 打开]` opens the browser, no intermediate dialog.
- [ ] Closing the browser window manually (OS [×]) makes the row return to `空闲` within ~2 seconds.
- [ ] Running `[测试]` updates the IP/geo column but **does NOT** modify `notes`.
- [ ] Running `[🔁 换IP]` updates the bound IP but **does NOT** modify `notes`.
- [ ] Default launch URL is `about:blank`, not `ipinfo.io` or any other external page.
- [ ] Tag chips have ≥10 visually distinct background colors, assigned by hash, consistent across rows.
- [ ] Selecting a row reveals the batch bar; deselecting all hides it.
- [ ] Header checkbox is `indeterminate` when some-but-not-all visible rows are selected.
- [ ] Search box matches across name + tag + notes + IP + geo.
