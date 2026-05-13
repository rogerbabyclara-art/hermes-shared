# AdsPower-Style Multi-Account Manager UI

The affirmative companion to the "UI paradigm for multi-profile managers" section
in `SKILL.md`. SKILL.md tells you what NOT to do; this file tells you what the
finished pattern looks like, so you can build it on the first try instead of
iterating through three rounds of "this is unnecessary, do it like AdsPower".

Validated against `D:\Projects\form-helper-v2` renderer in 2026-05.

## Mental model

The user manages N (20–500) browser profiles. Each profile = one CloakBrowser
identity + one residential proxy + one downstream account (Azure / Google /
Twitter / whatever). The UI is **a table of profiles + a batch action bar**.
That is the entire abstraction.

Existing reference implementations the user expects you to match:
- **AdsPower** — the gold standard, Chinese market
- **MoreLogin** — similar
- **Multilogin / Kameleo / GoLogin / Dolphin{anty}** — same paradigm

Things these tools all share, and you must replicate:
1. Row checkbox + "select all visible" header checkbox
2. Floating batch action bar that appears when ≥1 row selected
3. Search box that filters table live (substring match across multiple columns)
4. `仅看已打开` / `Only show opened` quick filter
5. Click-to-edit cells for `name`, `notes` (and sometimes `tags`)
6. Tag chips with inline `×` to remove, `+` to add
7. Status pill column (one of: `空闲 / 锁定 / 已打开` or `idle / locked / running`)
8. Single-row action buttons stacked at the right: `[▶/⏹] [测] [🔁] [🗑]`
9. NO modal between clicking action and the action happening
10. NO confirm dialog unless the action is irreversible

## Column layout (9 columns)

```
☐ checkbox | # seq | 名称 | 状态 | IP·地区 | 标签 | 备注 | 上次打开 | 操作
   36px      54px   120px   80px    170px    200px   flex     100px     200px
```

- **seq** is the row index in the filtered view, NOT the account ID. Pad with
  zeros to width 3 (`001`, `002`). Lets the user say "row 47 failed" without
  hunting for the actual account name.
- **状态/status** is a single pill: green `● 已打开` (process alive), yellow
  `🔒 锁定` (locked but browser not running), gray `空闲`. Don't combine status
  with other info — keep it one short word.
- **IP·地区** is two stacked lines: `ip-001 37.19.205.154` (top, monospace,
  clickable to jump to IP pool sub-tab) and `JP / Tokyo / Datacamp` (bottom,
  smaller, gray).
- **标签** holds tag chips + a `+` button. Chips have inline `×`.
- **备注** is the dumping-ground free-text cell. Double-click → inline edit.
- **上次打开** is `fmtAgo(last_opened_at)` — relative time (`2分前`, `1小时前`).
  Tells the user which profiles have been neglected.

## Top bar (account sub-tab)

```html
<div class="proxy-top-bar">
  <button>🔄 刷新</button>
  <button class="green">📦 批量建账号</button>
  <button>+ 单加</button>
  <input class="proxy-search" placeholder="搜索: 编号 / 名称 / 标签 / 备注 / IP / 地区" />
  <label><input type="checkbox" id="flt-running" /> 仅看已打开</label>
  <span class="stats">100 个账号 · 0 已打开 · 0 锁定</span>
</div>
```

## Batch bar (appears when selected.size > 0)

```html
<div class="proxy-batch-bar hidden">
  <span>已选 <b>N</b> 个</span>
  <button class="green">▶ 批量打开</button>
  <button>⏹ 批量关闭</button>
  <button>🏷 加标签</button>
  <button>✂ 去标签</button>
  <button>📝 改备注</button>
  <button class="red">🗑 批量删</button>
  <button class="ghost">✕ 取消选择</button>
</div>
```

Show/hide is just `bar.classList.toggle("hidden", selected.size === 0)`.

`Set<string>` of account names is the single source of truth for selection.
Re-rendering rows uses `selected.has(name)` to set `checked` and a CSS class
(`proxy-row-sel`) for highlighting. Persist across re-renders — do not clear
the set when you `reload()`.

## Selection semantics

- **Row checkbox** toggles one entry in the Set.
- **Header checkbox** is a tri-state:
  - All visible rows selected → checked
  - Some visible rows selected → indeterminate (`cb.indeterminate = true`)
  - None → unchecked
  - Clicking it: if `checked` → add all currently-filtered rows to Set; if not → remove them.
- "Visible" means **after filter is applied**. Header checkbox should NOT
  select hidden rows. This is what AdsPower does.

## Filtering

Live filter on `input` event (debounce 120ms). Search is substring,
case-insensitive, joined across:

```js
[a.name, a.notes, (a.tags||[]).join(" "),
 ip?.host + ":" + ip?.port, ip?.last_test_ip, ip?.last_test_geo,
 a.linked_csv_serial].join(" ").toLowerCase().includes(q)
```

`仅看已打开` checkbox additionally filters to `a._running || a.lock_status === "in_use"`.

## Inline edit (double-click pattern)

```js
tbody.addEventListener("dblclick", (e) => {
  const cell = e.target.closest("td[data-edit]");
  if (!cell) return;
  const field = cell.dataset.edit;          // "name" / "notes"
  const tr = cell.closest("tr"); const name = tr.dataset.name;
  const cur = /* current value */;
  const oldHtml = cell.innerHTML;
  cell.innerHTML = `<input class="ad-inline-edit" value="${escapeHtml(cur)}" />`;
  const input = cell.querySelector("input");
  input.focus(); input.select();
  let done = false;
  const commit = async () => {
    if (done) return; done = true;
    const v = input.value.trim();
    if (v !== cur) { await api.proxyBatchUpdate([name], { notes: v }); await reload(); }
    else cell.innerHTML = oldHtml;
  };
  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); commit(); }
    else if (ev.key === "Escape") { done = true; cell.innerHTML = oldHtml; }
  });
});
```

Gotcha: **renaming is not safe** if your backend keys other records by `name`
(IP bindings, lock state, browser profile dir). Either:
- Disable rename and show a toast "名称暂不支持改"
- Implement a real rename IPC that updates all the back-references atomically

Don't half-do it — a half-rename leaves orphaned profile dirs and dangling
IP bindings.

## Tag chips

```html
<span class="ad-chip">azure<span class="ad-chip-x" data-act="tag-del" data-tag="azure">×</span></span>
<button class="ad-chip-add" data-act="tag-add">+</button>
```

Click `×` → `proxyBatchUpdate([name], { remove_tag: tag })`.
Click `+` → `prompt()` for tag text → `proxyBatchUpdate([name], { add_tag: v })`.

Tags are the user's open-ended status system. Don't predefine `["完成", "失败",
"已注册"]` — let them invent their own labels.

## Backend IPC shape

Six handlers cover the whole batch surface:

```js
// Single
ipcMain.handle("proxy:openBrowser", async (_e, name, startUrl) => { ... });
ipcMain.handle("proxy:closeBrowser", (_e, name) => stopBrowser(name));

// Batch
ipcMain.handle("proxy:batchOpen", async (_e, names, opts) => {
  // opts: { concurrency: 5, delayMs: 600, startUrl }
  // Spawn workers, each pulls next name from a shared index, calls launchBrowser.
  // Auto-lock if not already locked. Write last_opened_at on success.
  // Return { ok, results: [{name, ok, error, pid}], summary: {total, ok} }
});

ipcMain.handle("proxy:batchClose", async (_e, names) => {
  // stopBrowser + clear lock fields for each. Always succeeds (idempotent).
});

ipcMain.handle("proxy:batchUpdate", (_e, names, patch) => {
  // patch: { add_tag?, remove_tag?, set_tags?, notes? }
  // Apply to each matching account, save once at the end.
});

ipcMain.handle("proxy:batchDelete", (_e, names) => {
  // Unbind IPs (set bound_to=null), then filter accounts out, save.
  // Return { ok, deleted, unbound }
});
```

**Concurrency for batchOpen**: 5 workers + 600ms inter-launch delay is the
sweet spot for residential proxies. Higher concurrency triggers provider
rate-limits (711proxy NotAllowed bursts). Lower wastes time when launching 50+
profiles.

**Progress polling**: the renderer polls `proxy:list` every 1.5s during a
batch and counts `accounts.filter(a => names.includes(a.name) && a._running)`
to update the button text `打开中 N/M`. Simpler than emitting per-launch
events and good enough for human-scale feedback.

## State updates after actions

Every action handler ends with `await reload()`. `reload()` calls
`proxy:list`, replaces `cached`, re-renders both tables, syncs selection UI.
Don't try to partial-update — full re-render with a cached selection Set is
much simpler and fast enough for <500 rows.

## Open-row markers

```css
.proxy-row-running td:first-child { box-shadow: inset 3px 0 0 #2ea043; }
.proxy-row-locked:not(.proxy-row-running) td:first-child {
  box-shadow: inset 3px 0 0 #d29922;
}
```

Left edge of running rows is a 3px green bar. Locked-but-not-running is
yellow. Scrollable table → user can scan which rows are "live".

## What the user will NOT thank you for

These were proposed and shot down in session — don't suggest them again:

- **Window title injection** (`document.title = "[C001] " + ...`) via
  `evaluateOnNewDocument` — over-engineering, rejected.
- **Canvas-drawn favicon badges** with profile number/color — rejected.
- **"What is this session for?" modal** before opening a browser — rejected.
- **"Confirm stop?" dialog** — rejected. Stop is one click, period.
- **Auto-status-from-test-result** ("marking ip-005 dead because it failed
  once") — rejected. Tests are sampling-only.
- **Predefined status workflows** ("registering → registered → activated →
  funded"). User will invent their own with free-form tags as needed.
- **Multi-color per-row groupings** without being asked — rejected.

## What to defer until asked

- Grouping / folder tree
- Platform column (Azure / Google / TikTok)
- Status workflow buttons (`[✓ 完成]` / `[✗ 失败]`)
- Per-row colors
- Drag-to-reorder
- Export / import CSV
- Activity log per account
- VPS-side read-only dashboard

Build the data plane and the basic 9-column table first. The user will tell
you which of the above is next.
