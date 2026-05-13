# Multi-window visual labeling (favicon + title)

## When you need this

You're running **10+ stealth browser windows concurrently** for an account farm / parallel ops / batch scraping, and the operator can't tell which window is which. Default Chromium gives every tab the same favicon and a title controlled by the page — when 20 `[Microsoft Sign In]` tabs are open in the Windows taskbar, mistakes happen: wrong credentials pasted, wrong proxy assumed, wrong account flagged as done.

This is **not a bot-detection concern** (the labels live in the renderer, the page can see them — but no detector cares that a tab title is prefixed `[C001]`). It's a **human factors** concern. Skip this for headless / fully automated flows; mandatory for human-in-the-loop multi-window operations.

## The technique

Inject a small client-side script into every page (including future pages) that:

1. **Rewrites `document.title`** to prefix the env/account label, e.g. `[C001 · 589] Microsoft Sign In`.
2. **Replaces the favicon** with a canvas-drawn colored square containing the env's short label (e.g. white "001" on green background).
3. **Watches for the page changing them back** via MutationObserver on `<title>` and a periodic re-apply for favicon — single-page apps (SPAs) reset both during navigation, so a one-shot injection isn't enough.

End result: Windows taskbar shows 20 distinct colored icons in a row, hovering any one reveals `[C001 · 589] page-title`. Operator picks the right window in milliseconds.

## Three Puppeteer integration points (all three needed)

Get this right and the labels stick across page navigations, popups, OAuth redirects, and SPA route changes:

```js
const injectScript = buildInjectScript(envName, serial, labelColor);

// 1. evaluateOnNewDocument — fires on EVERY future navigation, before page scripts
async function injectInto(page) {
  await page.evaluateOnNewDocument(injectScript);
  // also run NOW for the current document (evaluateOnNewDocument only catches future navs)
  try { await page.evaluate(injectScript); } catch (_) {}
}

// 2. All currently-open pages
for (const p of await browser.pages()) await injectInto(p);

// 3. All future pages (new tabs, window.open(), OAuth popups)
browser.on('targetcreated', async (target) => {
  const p = await target.page();
  if (p) await injectInto(p);
});
```

Missing any of the three = labels disappear in some scenario. Operators will report "the C003 window lost its label after the OAuth redirect" — that's missing `evaluateOnNewDocument`. "The popup didn't have a label" — that's missing `targetcreated`. "It worked initially but disappeared" — that's the page changing `<title>` after load without your MutationObserver.

## The injected script (canonical form)

Key design notes embedded as comments:

```js
(function() {
  if (window.__cloakLabelInjected) return;  // idempotent — script runs many times
  window.__cloakLabelInjected = true;

  const ENV_NAME = "C001";           // injected by launcher
  const SERIAL = "589";              // optional, second identifier
  const TITLE_PREFIX = "[C001 · 589] ";
  const SHORT_LABEL = "001";         // 3-4 chars MAX for favicon legibility at 16px
  const LABEL_COLOR = "#2ea043";

  // ---- favicon ----
  function makeFavicon() {
    const c = document.createElement('canvas');
    c.width = 64; c.height = 64;   // 64x64 source, Chromium downscales to 16x16 in taskbar
    const g = c.getContext('2d');
    // rounded square background (looks cleaner than full square at 16x16)
    g.fillStyle = LABEL_COLOR;
    roundedRect(g, 0, 0, 64, 64, 12);
    g.fill();
    // bold white text, font-size depends on label length
    g.fillStyle = '#ffffff';
    g.font = 'bold ' + (SHORT_LABEL.length >= 4 ? 22 : 30) + 'px Arial';
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(SHORT_LABEL, 32, 34);
    return c.toDataURL('image/png');
  }

  function applyFavicon() {
    const url = makeFavicon();
    // remove ALL existing icon links — sites often have multiple (apple-touch, mask-icon, etc.)
    document.querySelectorAll("link[rel*='icon']").forEach(l => l.remove());
    for (const rel of ['icon', 'shortcut icon']) {
      const link = document.createElement('link');
      link.rel = rel; link.type = 'image/png'; link.href = url;
      (document.head || document.documentElement).appendChild(link);
    }
  }

  // ---- title ----
  function applyTitle() {
    const orig = document.title || '';
    if (orig.startsWith(TITLE_PREFIX)) return;       // already prefixed
    const clean = orig.replace(/^\[.*?\]\s*/, '');   // strip prior prefix variant
    document.title = TITLE_PREFIX + clean;
  }

  // ---- observe page changing them ----
  function watch() {
    const titleEl = document.querySelector('title');
    if (!titleEl) {
      // <title> not in DOM yet — observe head until it shows up
      const head = document.head || document.documentElement;
      const hobs = new MutationObserver(() => {
        if (document.querySelector('title')) { hobs.disconnect(); watch(); }
        applyTitle(); applyFavicon();
      });
      hobs.observe(head, { childList: true, subtree: true });
      return;
    }
    new MutationObserver(applyTitle).observe(titleEl, {
      childList: true, characterData: true, subtree: true
    });
  }

  // initial run + watcher start
  const tick = () => { applyFavicon(); applyTitle(); };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { tick(); watch(); });
  } else { tick(); watch(); }

  // safety net — some SPAs replace title/favicon outside MutationObserver's scope
  // (e.g. via SSR hydration that doesn't trigger mutations in the way you'd expect)
  setInterval(tick, 2500);
})();
```

## Short-label extraction rules

Favicons at 16x16 in the taskbar can fit ~3-4 characters legibly. Rules that work:

- `C001` → `001` (strip leading `C0*`)
- `P-589` → `589` (strip non-digit prefix)
- Long arbitrary names (`team-alpha-account-37`) → take the last 4 chars (`nt37`)
- Empty fallback → `?`

Don't try to cram `C001` (4 chars) at 30px font; either drop the prefix or shrink to 22px when length ≥ 4. The version above does both.

## Color coding strategy

Single color across all windows is fine when the number is what matters. But if you want **at-a-glance grouping** (operator sees "all my green windows are batch A"), assign color by index bucket:

```js
const PALETTE = ['#2ea043','#1f6feb','#a371f7','#fb8500','#e6394b','#0a8754'];
const labelColor = PALETTE[Math.floor(envIndex / 10) % PALETTE.length];
// C001-C010 green, C011-C020 blue, C021-C030 purple, ...
```

Don't randomize per-launch — operators build muscle memory for "C00x is green".

## Pitfalls

0. **Two-process architectures need TWO injection points, not one** — Pattern: a *launcher* process spawns CloakBrowser and exposes its `wsEndpoint`; a separate *worker* process (different code path, e.g. a registration flow) later `puppeteer.connect()`s to that endpoint and calls `browser.newPage()` to do work. The launcher's `targetcreated` listener fires for the new tab, BUT there is a **race**: the worker calls `page.goto(...)` immediately after `newPage()`, and `evaluateOnNewDocument` might not be registered yet (the launcher's `targetcreated` handler is async — `await target.page()` → `await page.evaluateOnNewDocument(...)` — and during that window the worker has already started the goto). Result: the first navigation in the new tab has NO injected script, so no favicon/title for the duration of the page lifetime — until the page itself triggers a new navigation (often never, on SPA-heavy sites like Azure signup). Symptom: \"labels work when I open the browser standalone, but disappear the moment my automation takes over.\" **Fix: the worker process must ALSO inject the same script** right after `puppeteer.connect()`, attaching its own `targetcreated` listener AND running `evaluateOnNewDocument` + `evaluate` on every already-open page. The `__cloakLabelInjected` idempotency guard ensures double-injection is harmless. Concretely:

   ```js
   // worker side, after puppeteer.connect()
   const browser = await puppeteer.connect({ browserWSEndpoint: wsEndpoint });
   const injectScript = buildInjectScript(envName, serial, labelColor);
   async function injectLabel(p) {
     try {
       await p.evaluateOnNewDocument(injectScript);
       try { await p.evaluate(injectScript); } catch (_) {}
     } catch (_) {}
   }
   browser.on('targetcreated', async (t) => {
     try { const p = await t.page(); if (p) await injectLabel(p); } catch (_) {}
   });
   for (const p of await browser.pages()) await injectLabel(p);
   // NOW it's safe to call browser.newPage() + page.goto(...)
   ```

   Don't try to fix this by adding `await sleep(500)` in the launcher's targetcreated — that races on slow machines. Don't try to coordinate via IPC — too much coupling. Just inject on both sides; the idempotency guard makes it cheap. Factor the inject-script builder into a shared module (CJS / ESM as needed; if launcher is `.mjs` and worker is `.js`, expose the builder as a tiny CJS file the worker can `require()` directly and the launcher can `import` via dynamic `import()` or duplicate locally — script content is small).

1. **Setting only `page.evaluate(script)` once on launch** — labels vanish after the first navigation because the new document has none of your DOM changes. You MUST use `evaluateOnNewDocument` for persistence across navs.

2. **Forgetting `targetcreated`** — works fine on the initial tab, fails on OAuth popups, `window.open()`, and `_blank` links. Every multi-account flow eventually hits an OAuth popup; if that window isn't labeled the operator loses track.

3. **MutationObserver on `<title>` only** — fails for pages that don't have `<title>` at script execution time (rare but happens with very fast-loading SPAs that hydrate `<head>` from JS). The script above handles this by first observing `<head>` until `<title>` appears.

4. **Putting the label in the URL fragment** — tempting (`example.com/page#env=C001`) but the page can read and act on this, plus it's invisible in the taskbar. Title + favicon is the only path to actual taskbar visibility.

5. **Canvas drawing on a page with strict CSP** — some sites set `Content-Security-Policy: img-src 'self'` which blocks `data:` URLs. The `<link rel="icon" href="data:...">` injection silently fails. Workaround: skip the favicon, keep just the title prefix; or detect CSP and warn. Rare but happens on government and bank sites.

6. **Title getting really long** — page titles like `(3) New message from Aaron - Microsoft Outlook Web App - example.com` plus a `[C001 · P-589] ` prefix exceeds the taskbar tooltip's useful length. Truncate to ~60 chars after prefixing if you need to.

7. **idempotency guard `__cloakLabelInjected`** — looks redundant but the script is invoked from BOTH `evaluateOnNewDocument` (fires before page scripts) AND a one-shot `page.evaluate` (for current document). Without the guard, the MutationObservers stack and you get N favicon refreshes per tick.

## Passing the env vars from a launcher

The cleanest split is: Electron / Node host process spawns a launcher subprocess via env vars, launcher reads them and builds the injection script. Avoid command-line args (quoting hell on Windows).

```js
// host (Electron main)
const env = {
  ...process.env,
  ACCOUNT_NAME: 'C001',                // env identifier
  SERIAL: '589',                        // optional second identifier (e.g. CSV row)
  LABEL_COLOR: '#2ea043',
  // ... other browser launch params
};
spawn(process.execPath, [launcherPath], { env });
```

```js
// launcher.mjs
const ENV_NAME = process.env.ACCOUNT_NAME || 'unnamed';
const SERIAL = process.env.SERIAL || '';
const LABEL_COLOR = process.env.LABEL_COLOR || '#2ea043';
const injectScript = buildInjectScript(ENV_NAME, SERIAL, LABEL_COLOR);
// ... attach to all current + future pages
```

This separation also means the data model that drives the labels (your account/env DB) is fully decoupled from the browser launching code — same launcher works whether labels come from a CSV, SQLite, or a REST API.

## Reference impl in this repo

`D:\Projects\form-helper-v2\proxy\launcher.mjs` has a working version (May 2026) wired into a 20+ concurrent CloakBrowser setup. Two identifiers per window: `ACCOUNT_NAME` = CloakBrowser profile dir (e.g. `C001`), `SERIAL` = independent account identity (e.g. CSV row `589` or `P-100`). Title shows both, favicon shows just the env's last 3-4 chars.
