# FormHelper Electron App — Architecture Reference

**Location**: `D:\Projects\form-helper-app`  
**Compiled binary**: `dist\FormHelper-0.1.0-portable.exe`  
**Relationship**: Companion desktop tool for azure-auto-reg; v1 launched it alongside runner via `启动v2.bat`

## 3 Tabs

### 1. 使用 (Use) — Account Viewer
- Reads `accounts.csv` (CSV-based account database)
- Displays fields: 行业, 公司, 日文名/姓, 英文名/姓, 電話, 法人番号, 邮编, 都道府県, 市区町村, 地址, 邮箱, 密码
- Click-to-copy any field → paste into target form
- Serial selector dropdown (`1036 - 加藤芳朗 - 株式会社ベルテクノ` format)
- Mark done / rename serial / delete account (releases company from used pool)
- Replace credentials (email/pass/backup bulk paste)
- Change company (swap to different company from library)
- Enrich bar: Claude Haiku web_search enrichment → compare with SalesNow data → save diffs
- Backfill empty fields / force sync from leads data
- Edit CSV button / reveal in explorer

### 2. + 新建 (New) — Batch Account Creator
- Left panel: serial range input (e.g. `P100-P200`), email/password bulk paste (4-field `----` delimited)
- Right panel: company library browser with:
  - Multi-country tabs: 🇯🇵 JP / 🇬🇧 UK / 🇸🇬 SG / 🇺🇸 US / 🇹🇼 TW
  - Phone status filter: all / verified / unverified
  - Industry dropdown + search
  - 🎲 Random assignment (with industry/country/phone/rank-cap/Tokyo-priority options)
- Company detail preview panel
- Saves batch to CSV + marks companies as used

### 3. Azure — Runner Control Panel
- **Runner status**: online/offline/blocking dot indicator
- **Start/Stop runner**: spawns `node src/runner.js` as child process
- **Task generator**: input from/to envId range + browser engine (ADS/MoreLogin) → generates tasks.json
- **Task list**: color-coded items (✅ success / ❌ failed / ⏭ skipped / ⏳ pending), each with ▶ start-from button
- **Blocking banner**: continue / takeover buttons (same as dashboard)
- **History timeline**: reverse-chronological results with duration, custom notes
- **Reset runtime**: clears runtime.json to start fresh
- **Set start index**: jump to any task position

## Data Files (all in exe directory or project root)
- `accounts.csv` — master account database
- `companies.json` — company library (JP 6500+, UK, SG, US, TW)
- `used_companies.json` — tracks which companies are assigned to accounts
- `tasks.json` — Azure runner task queue
- `runtime.json` — runner execution state (currentIndex, results[])

## Key IPC Channels (preload.js → main.js)
- `accounts:*` — load, append, delete, setDone, rename, bulkPatch, bulkOverwrite
- `companies:*` — list, industries, refresh, markUsed, unmarkUsed, listUsed
- `azure:*` — state, runtime, tasks, saveTasks, continue, takeover, resetRuntime, setStartIndex, startRunner, stopRunner
- `azure:markSuccess` / `azure:retry` / `azure:retryAll` — **v2 only**: failure management IPC, calls runner's dashboard HTTP endpoints (`/api/mark-success`, `/api/retry`, `/api/retry-all`)
- `azure:saveRuntime` — **v2 only**: direct `runtime.json` write for offline mark-success fallback (when runner HTTP API is unavailable)
- `enrich:company` — Claude Haiku + web_search enrichment (multi-field structured output)
- `enrich:romaji` — Standalone romaji lookup via Claude + web_search
- `leads:fetch` — Pull from external dashboard API (http://localhost:8000/api/leads)
- `tasks:*` — Simple task/todo list (unrelated to Azure tasks)

## Enrich Engine (main.js lines 631-937)
- Uses `@anthropic-ai/sdk` with `ANTHROPIC_API_KEY` + optional `ANTHROPIC_BASE_URL` from `.env`
- Model: `claude-haiku-4-5` with `web_search_20250305` tool (max 3-4 uses)
- SSE stream parser for NEWAPI proxy compatibility (normalizeResponse/parseSSE)
- JP prompt: searches company name, cross-references 法人番号 on nta.go.jp, does kanji→romaji conversion
- Intl prompts: UK (Companies House), SG (ACRA BizFile), US (LinkedIn/Yelp), TW (findbiz/g0v)
- Output: structured JSON with per-field confidence/agreement/source_url
- Retry: 2 attempts, handles `stop_reason=tool_use` (proxy didn't execute server tool)

## FormHelper vs v2 Dashboard Comparison (updated 2026-05-12)

After the v2 dashboard rewrite (27KB, dark theme), it now matches or exceeds FormHelper's Azure tab for runner control. **FormHelper v2** (`form-helper-v2`) has been upgraded to include all v2-exclusive features via IPC → dashboard HTTP bridge.

| Feature | FormHelper v1 Azure Tab | FormHelper v2 Azure Tab | v2 Dashboard (port 7777) |
|---------|------------------------|------------------------|--------------------------|
| Start runner (spawn process) | ✅ | ✅ | ❌ (runner IS the host) |
| Stop runner | ✅ | ✅ | ✅ (`POST /api/stop-runner`) |
| Generate task list | ✅ | ✅ | ✅ (`POST /api/gen-tasks`) |
| Start from any task | ✅ (▶ per task) | ✅ (▶ per task) | ✅ (`POST /api/set-index`) |
| Reset runtime | ✅ | ✅ | ✅ (`POST /api/reset-runtime`) |
| Blocking alert handling | ✅ | ✅ | ✅ |
| Progress bar + success rate | ❌ | ✅ (v2 added) | ✅ |
| Failed env management | ❌ | ✅ (v2 added) | ✅ |
| Mark success | ❌ | ✅ (per-task + panel, offline fallback) | ✅ |
| Retry single/all | ❌ | ✅ (v2 added) | ✅ |
| Retry queue count | ❌ | ✅ (v2 added) | ✅ |
| History timeline | ✅ | ✅ | ✅ |
| Custom notes | ✅ | ✅ | ❌ |
| Account management | ✅ (full CRUD) | ✅ (full CRUD) | ❌ (out of scope) |
| Company library | ✅ (multi-country) | ✅ (multi-country) | ❌ (out of scope) |

**v2 dashboard API endpoints (all on port 7777):**
- `GET /` — full HTML dashboard
- `GET /api/state` — JSON snapshot (progress, tasks, runtime, failed, retryQueue)
- `POST /api/continue` / `/api/takeover` — unblock captcha/manual alerts
- `POST /api/mark-success` / `/api/retry` / `/api/retry-all` — failure management
- `POST /api/gen-tasks` `{ from, to, browser }` — generate tasks.json
- `POST /api/reset-runtime` — clear runtime.json
- `POST /api/set-index` `{ index }` — jump to task position
- `POST /api/stop-runner` — graceful shutdown (`process.exit(0)`)

**Key architectural difference**: FormHelper is an Electron app that spawns the runner as a child process and talks to it over HTTP. v2 dashboard is embedded inside the runner itself — when runner starts, the dashboard is automatically available. This means v2 can never "start" the runner (it's already running), but it can stop it. The tradeoff: simpler deployment (just `node src/runner.js`), no IPC complexity, but account management and company library remain in FormHelper.

## Adding Backend Features to FormHelper (IPC Bridge Pattern)

When the backend runner gains new HTTP API endpoints (e.g. `/api/mark-success`), adding them to FormHelper requires touching exactly 5 files in this order:

### Step-by-step (ordered by dependency)

1. **`main.js`** — Add `ipcMain.handle()` for each new channel. These call `azurePostDashboard(path, body)` to proxy to the runner's HTTP API on port 7777.
   ```js
   ipcMain.handle("azure:markSuccess", async (_e, envId) => {
     return await azurePostDashboard("/api/mark-success", { envId });
   });
   ```

2. **`preload.js`** — Expose the new IPC channel via `contextBridge.exposeInMainWorld`:
   ```js
   azureMarkSuccess: (envId) => ipcRenderer.invoke("azure:markSuccess", envId),
   ```

3. **`renderer/index.html`** — Add DOM elements (cards, buttons, containers) for the new UI section.

4. **`renderer/azure-tab.js`** — Add:
   - Event binding in `bindEvents()` for new buttons
   - Render function(s) called from `refresh()` that read data from `state.live` (which comes from runner's `/api/state`)
   - Event delegation for dynamically-created buttons (use `closest("[data-action]")` pattern)

5. **`renderer/style.css`** — Add styles for new UI elements.

### Offline fallback: direct file-write IPC (6th file touch)

When a feature must work even when the runner isn't running (e.g. marking a failed task as success after the runner stopped), the HTTP proxy pattern fails silently. Add a direct file-write IPC as fallback:

```js
// main.js — direct runtime.json write
ipcMain.handle("azure:saveRuntime", (_e, rt) => {
  try {
    const fp = azurePath("config/runtime.json");
    fs.writeFileSync(fp, JSON.stringify(rt, null, 2), "utf8");
    return { ok: true };
  } catch (e) { return { ok: false, error: e.message }; }
});

// preload.js
azureSaveRuntime: (rt) => ipcRenderer.invoke("azure:saveRuntime", rt),
```

```js
// azure-tab.js — fallback in click handler
const r = await window.api.azureMarkSuccess(envId);  // try HTTP first
if (r && r.ok) { refresh(); return; }
// fallback: direct file edit
const rt = await window.api.azureRuntime();
if (rt && rt.results) {
  for (const res of rt.results) {
    if (String(res.envId) === String(envId)) {
      res.status = "reached_payment";
      res.reason = "manual_mark";
    }
  }
  await window.api.azureSaveRuntime(rt);
  refresh();
}
```

### Verification
```bash
node -c main.js && node -c preload.js && node -c renderer/azure-tab.js
```
(HTML/CSS don't need syntax check — visual verify on launch)

### Key data flow
```
Runner process                          Electron process
  dashboard.js ← HTTP ← main.js ← IPC ← preload.js ← azure-tab.js
  /api/state   → GET  → azure:state  →  azureState() → renderFailed()
  /api/retry   → POST → azure:retry  →  azureRetry()  ← click handler
```

### Pitfall: state.live vs state.runtime
- `state.live` = response from runner's `/api/state` HTTP endpoint (includes `failedTasks`, `retryQueueLen`, `current`, `blocking`). Only available when runner is online.
- `state.runtime` = direct file read of `runtime.json` (includes `results[]`, `currentIndex`). Always available.
- `state.tasks` = direct file read of `tasks.json`. Always available.
- New v2 fields (`failedTasks`, `retryQueue`, `retryQueueLen`) are in `state.live` only — they're in-memory on the runner side.

### Pitfall: put action buttons WHERE THE DATA IS, not only in a separate panel
- Failed management as a separate panel reads `state.live.failedTasks` (in-memory, runner must be online, and only populated after runner observes a failure in its current session).
- But the task list (from `state.runtime.results` via file read) ALWAYS shows failed tasks — even after runner restarts, even when runner is offline.
- **Users expect ✅ mark-success buttons directly on each failed task row in the task list**, not only in a separate "failed management" panel that may be empty.
- Solution: render both — a ✅ button per failed row in the task list (reads runtime.json, works offline) AND a failed management panel (reads live state, shows retry queue status when runner is online).
- The task list ✅ button needs the offline fallback (direct `runtime.json` edit) since the user may want to mark success while the runner is stopped.
