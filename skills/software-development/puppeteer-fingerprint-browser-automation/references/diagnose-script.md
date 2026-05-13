# Diagnostic Script Pattern for Node.js Automation Runners

## Purpose

When the user asks "what's happening?" or "why did P492 fail?", the agent should NOT guess from memory or re-read raw log files. Instead, run a structured diagnostic script that produces machine-readable output the agent can interpret instantly.

## Location

`scripts/diagnose.js` in the project root. Register in package.json:

```json
"diagnose": "node scripts/diagnose.js",
"diagnose:errors": "node scripts/diagnose.js --errors",
"diagnose:live": "node scripts/diagnose.js --live"
```

## Data sources

The script reads these files (all relative to project root):

| File | Format | Contains |
|------|--------|----------|
| `config/runtime.json` | JSON | `currentIndex`, `results[]` (status/reason/duration/screenshot), `lastRunAt` |
| `config/tasks.json` | JSON array | `[{envId, browser, note}]` — full task list |
| `logs/progress.jsonl` | JSONL | Every event: task.start, task.update (stage changes), task.failure, task.finish, block.start, block.clear, failed.add |
| `logs/progress.txt` | Plain text | Human-readable snapshot (current task, blocking status, recent completions) |
| `logs/flow/<envId>/` | Directory of PNGs | Screenshots at each stage — naming convention includes timestamp + stage |

## CLI modes

### Default (full report)
```
node scripts/diagnose.js
```
Outputs: file health → runtime state → result statistics → failure analysis → auto-diagnosis → recent 5 events

### Single envId trace
```
node scripts/diagnose.js --env P492
```
Shows: all runtime.json results for that envId, all jsonl events chronologically, all screenshot filenames. This is the go-to for "why did X fail?"

### Errors only
```
node scripts/diagnose.js --errors
```
Failure analysis section only, with error categorization and repeat-failure detection.

### Recent events
```
node scripts/diagnose.js --recent 30
```
Last N events from jsonl, formatted with icons and timestamps.

### Live snapshot
```
node scripts/diagnose.js --live
```
Reads progress.txt — shows what the runner is doing right now (or was doing when it last wrote).

## Error categorization logic

Map raw error reason strings to human-readable categories for pattern detection:

```js
const categories = {
  'captcha|人機|人工接管超時': '🤖 captcha/人機验证',
  '都道府県|下拉.*找不到|no_match': '🗾 都道府県匹配',
  'Navigation timeout': '⏰ 页面导航超时',
  'frame.*detach': '💥 Frame Detached',
  '個人使用.*radio': '🔘 個人使用向け 找不到',
  'missing_romaji|missing_kana': '📛 姓名数据缺失',
  'form1.*卡住': '🔄 Form1 卡住循环',
  'form2.*填写失败': '📝 Form2 填写失败',
  '予期しないエラー|Unexpected error': '💢 Azure 后端错误',
};
```

Group failures by category, sort by count descending, show top 3 samples per category.

## Auto-diagnosis checks

The script should automatically flag:

1. **Stalled runner** — last result > 30min ago with pending tasks
2. **Consecutive failures** — 3+ of last 5 results are failures (especially same reason = systematic)
3. **Low success rate** — effective rate < 50% after 5+ attempts
4. **Known bug patterns** — 都道府県 failures (v2 includes fix should prevent these)
5. **Captcha storm** — 3+ captcha failures = IP/proxy may be flagged
6. **Data quality** — high skip rate from missing romaji/kana names
7. **Browser compat** — frame detached frequency (MoreLogin/ADS version issue)
8. **Log bloat** — progress.jsonl > 5MB → suggest archival

## Design notes

- Pure Node.js, no dependencies beyond `fs` and `path`
- Reads files synchronously (diagnostic tool, not production server)
- All timestamps displayed in Asia/Shanghai timezone (user preference)
- Duration formatting: `<60s` → `Xs`, `>=60s` → `XmYs`
- Unicode icons for quick visual scanning in terminal output
