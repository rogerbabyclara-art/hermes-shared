#!/usr/bin/env node
/**
 * Backfill azure_status / azure_stage for historical successful runs that
 * pre-date the status persistence feature.
 *
 * Use case:
 *   You added `azure_status` write paths to the runner. Older accounts that ran
 *   before this code shipped have status='', but their `logs/flow/<name>/`
 *   contains a `*-reached-payment.png` screenshot, proving they succeeded.
 *   This script reads those screenshots and writes the appropriate status fields
 *   so the UI shows ✅ for them instead of —.
 *
 * Safety:
 *   - Skips any account already in `success` state (never overwrites a recent record).
 *   - Skips any account whose log dir has no `reached-payment` screenshot.
 *   - Does NOT touch `events[]` array — only updates azure_status / azure_stage /
 *     azure_last_msg / azure_finished_at / azure_screenshot.
 *
 * Usage:
 *   cd <project-root>
 *   node scripts/backfill-azure-status.js                 # dry-run, prints what would change
 *   node scripts/backfill-azure-status.js --apply         # actually writes proxies.json
 *
 * Customize:
 *   - `STATUS_FIELD_PREFIX` if your fields are named differently (e.g. 'azureStatus' instead of 'azure_status').
 *   - `LOG_DIR_PATTERN` if your screenshot directory layout differs.
 *   - `SUCCESS_SCREENSHOT_PATTERN` to match the exact filename pattern that proves success.
 */

const fs = require('fs');
const path = require('path');

const APPLY = process.argv.includes('--apply');
const PROJECT_ROOT = process.cwd();

// ─── customize these for your project ────────────────────────────────────────
const STORE_MODULE = './proxy/store';                          // exports loadProxies, saveProxies
const LOG_DIR = path.join(PROJECT_ROOT, 'logs', 'flow');       // per-account screenshot dirs
const SUCCESS_SCREENSHOT_PATTERN = /reached-payment\.png$/i;   // the smoking gun
const SUCCESS_STAGE = 'reached_payment';
const SUCCESS_MSG = '历史成功记录回填 (基于 reached-payment 截图)';
// ─────────────────────────────────────────────────────────────────────────────

const store = require(path.resolve(PROJECT_ROOT, STORE_MODULE));
const data = store.loadProxies(PROJECT_ROOT);
if (!data || !Array.isArray(data.accounts)) {
  console.error('store.loadProxies did not return { accounts: [] }');
  process.exit(1);
}

let updated = 0;
let skipped_already_success = 0;
let skipped_no_screenshot = 0;

for (const acc of data.accounts) {
  if (acc.azure_status === 'success') {
    skipped_already_success++;
    continue;
  }
  const accLogDir = path.join(LOG_DIR, acc.name);
  if (!fs.existsSync(accLogDir)) {
    skipped_no_screenshot++;
    continue;
  }
  const files = fs.readdirSync(accLogDir).sort();           // sort gives chronological order if filenames are timestamped
  const successShots = files.filter((f) => SUCCESS_SCREENSHOT_PATTERN.test(f));
  if (successShots.length === 0) {
    skipped_no_screenshot++;
    continue;
  }
  const latestShot = successShots[successShots.length - 1];
  const shotPath = path.join(accLogDir, latestShot);
  const shotStat = fs.statSync(shotPath);

  // Parse mtime as finished_at — that's when the screenshot was written = run finished
  const finishedAt = shotStat.mtime.getTime();

  console.log(
    `[backfill] ${acc.name}: status='' → success, screenshot=${latestShot}, finished_at=${new Date(finishedAt).toISOString()}`
  );

  if (APPLY) {
    acc.azure_status = 'success';
    acc.azure_stage = SUCCESS_STAGE;
    acc.azure_last_msg = SUCCESS_MSG;
    acc.azure_finished_at = finishedAt;
    acc.azure_reason = '';
    acc.azure_screenshot = shotPath;
  }
  updated++;
}

console.log('');
console.log(`Summary: ${updated} to update, ${skipped_already_success} already success, ${skipped_no_screenshot} no screenshot`);

if (APPLY) {
  store.saveProxies(PROJECT_ROOT, data);
  console.log(`✓ Wrote proxies.json (${updated} accounts updated)`);
} else {
  console.log('(dry-run; rerun with --apply to write)');
}
