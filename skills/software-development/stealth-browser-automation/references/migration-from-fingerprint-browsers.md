# Migrating off MoreLogin / ADSPower / Multilogin

Concrete recipe for replacing a Puppeteer-over-WebSocket-to-fingerprint-browser stack with self-hosted stealth Chromium.

## Typical starting state

```javascript
// morelogin.js — old
const axios = require('axios');
async function startEnv(envId) {
  const r = await axios.post('http://127.0.0.1:40000/api/v1/browser/start', {
    envId, headless: false,
  });
  return r.data.data.ws;  // WebSocket endpoint
}

// flow.js — old
const wsEndpoint = await startEnv(envId);
const browser = await puppeteer.connect({ browserWSEndpoint: wsEndpoint });
```

Pain points this creates:
- Local API server (MoreLogin app) must be running.
- Profile creation/deletion is a manual + paid operation.
- API hangs randomly (need 30s timeouts everywhere).
- `stopEnv` + `startEnv` to "rotate proxy" sometimes doesn't actually rotate.
- Per-profile fee at scale.

## Target state

```javascript
// flow.js — new
const { launch } = require('cloakbrowser/puppeteer');
const browser = await launch({
  headless: false,
  humanize: true,
  geoip: true,
  fingerprint: account.seed,           // stored in your DB, not in MoreLogin
  proxy: account.proxy,                 // per-account proxy
  userDataDir: `./profiles/${account.id}`,
});
```

## Step-by-step migration

### 1. Inventory hand-rolled defenses

Search the codebase for these patterns and tag each as "keep" or "replace":

| Pattern | Action |
|---|---|
| Custom mouse-move-along-bezier helper | **Replace** with `humanize=true` |
| Per-char typing delay loops | **Replace** with `humanize=true` |
| "Real click via bounding box" for radios/checkboxes | **Replace** with `humanize=true` |
| `evaluateOnNewDocument` to override `navigator.webdriver` etc. | **Replace** — CloakBrowser handles all of these at C++ level |
| `evaluateOnNewDocument` to auto-click KMSI / "Stay signed in" | **Keep** — this is flow logic, not anti-detection |
| IP probe → httpbin → compare to expected country | **Replace** with `geoip=true` (also gains WebRTC guard) |
| Custom Canvas / WebGL noise injectors | **Replace** — fingerprint seed handles it |
| Field-value-readback validation ("did firstName actually commit?") | **Keep** — protects against SPA flakiness, not bots |
| `safeGoto` retry wrapper | **Keep** — network reliability, unrelated |
| MoreLogin `startEnv` / `stopEnv` to rotate IP | **Replace** — just pass new `proxy` to `launch()` |

### 2. Build a parallel project, don't edit in place

Mistake to avoid: patching the existing automation in place. Stealth Chromium changes timing, click behavior, and what defenses are needed. Things WILL break, and you want a side-by-side comparison, not a hostage situation.

```
D:\Projects\azure-auto-reg\         # original, untouched
D:\Projects\azure-auto-reg-v2\      # current improvements on MoreLogin
D:\Projects\azure-auto-reg-v3-cloak\  # CloakBrowser version
```

### 3. Port one full happy-path run first

Before deleting anything, get ONE end-to-end run working on the new stack. Use the simplest possible flow:
- Hardcode a fingerprint seed
- Hardcode one proxy
- Hardcode one set of form values
- Goal: reach the final success state once

This validates the new stack actually passes the bot detection the old stack was fighting.

### 4. Diff the defense list

After the happy-path works, run again with each "replace"-tagged defense REMOVED one at a time. Confirm the run still completes. This is how you prove humanize/geoip/fingerprint actually subsume the old hand-rolled code, instead of just stacking on top.

### 5. Move state out of MoreLogin

Schema migration: MoreLogin held the profile identity (envId → fingerprint + cookies + proxy). Move this into your own DB:

```sql
CREATE TABLE accounts (
  id            INTEGER PRIMARY KEY,
  fingerprint   INTEGER NOT NULL,    -- seed for stealth Chromium
  proxy_url     TEXT NOT NULL,       -- per-account proxy
  profile_dir   TEXT NOT NULL,       -- e.g. ./profiles/{id}
  cookies_path  TEXT,                -- optional separate cookie export
  status        TEXT,
  ...
);
```

The fingerprint seed is just an integer. The profile directory holds cookies. The proxy is your existing residential proxy. No more MoreLogin API in the loop.

### 6. Throughput consideration

MoreLogin: one local profile = one heavy process, ~400MB RAM each, 10–20 concurrent on a beefy box.

Stealth Chromium: same Chromium engine, same RAM footprint. Concurrency math doesn't change. The wins are: no per-profile cost, no local API dependency, no profile-creation API calls — NOT raw speed.

## Don't migrate if

- Your team relies on MoreLogin's GUI to manually inspect profiles. Stealth Chromium has no GUI manager.
- You're sharing profiles across team members. MoreLogin's cloud sync is a feature stealth Chromium doesn't replicate.
- You're at <100 profiles total and the MoreLogin license is paid. The migration effort isn't free.
