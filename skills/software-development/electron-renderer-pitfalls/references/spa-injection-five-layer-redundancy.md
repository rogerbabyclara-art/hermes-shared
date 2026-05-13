# SPA-resilient label injection — five-layer redundancy template

Companion to `electron-renderer-pitfalls` Pitfall 21. This is the full reference template for injecting a per-environment visual label (favicon + title + in-page badge) that survives:

- SPA route changes (`pushState` / `replaceState`)
- Site rewrites of `<head>` and `<title>`
- Tabs created via `puppeteer.connect()` race
- Operator F5 refresh, tab restore, `target=_blank`
- Pages that aggressively replace DOM (Microsoft login, Azure portal)

## Why so many layers

Any ONE layer fails under some condition:

| Layer | What it does | What kills it |
|---|---|---|
| `evaluateOnNewDocument` | Inject at document creation | `puppeteer.connect()` race; not all new pages caught |
| Favicon `<link rel=icon>` | Tab strip indicator | SPA rewrites `<head>`; many monitors hide tab strip |
| Title prefix | Window title / taskbar | SPA replaces title repeatedly; multi-window operators don't see taskbar |
| In-page badge | Fixed overlay div in viewport | Some SPAs full-replace `document.body` |
| MutationObserver on `<head>` | Re-inject favicon/title on site rewrites | innerHTML replacement on wrapper bypasses subtree:false |
| MutationObserver on `<body>` | Re-inject badge on body rewrites | Subtree:true is expensive; childList-only misses deep mutations |
| 2s interval `getElementById` | Sanity check | Pitfall 9 risk — only cheap check is allowed |
| `puppeteer.connect()` re-inject | Catch missed tabs | Race if user opens tab between connect and listener attach |

Five layers together = no single failure leaves the operator without an environment indicator.

## Full template (CJS — single source of truth)

```js
// proxy/label-inject.js
'use strict';

function buildLabelInjectScript(envName, serial, labelColor) {
  envName = envName || 'unnamed';
  serial = serial || '';
  labelColor = labelColor || '#2ea043';

  // Short label for favicon: "C001" -> "001", "P-589" -> "P589"
  let shortLabel = envName.replace(/^C0*/i, '').slice(-4) || envName.slice(-4);
  if (!shortLabel) shortLabel = '?';

  const titlePrefix = serial ? `${envName} · ${serial} · ` : `${envName} · `;

  return `
(function() {
  if (window.__cloakLabelInjected) return;
  window.__cloakLabelInjected = true;

  var ENV_NAME = ${JSON.stringify(envName)};
  var SERIAL = ${JSON.stringify(serial)};
  var TITLE_PREFIX = ${JSON.stringify(titlePrefix)};
  var SHORT_LABEL = ${JSON.stringify(shortLabel)};
  var LABEL_COLOR = ${JSON.stringify(labelColor)};

  // ============ Layer 1: favicon ============
  function makeFavicon() {
    try {
      var c = document.createElement('canvas');
      c.width = 64; c.height = 64;
      var g = c.getContext('2d');
      g.fillStyle = LABEL_COLOR;
      var r = 12;
      g.beginPath();
      g.moveTo(r, 0); g.lineTo(64-r, 0); g.quadraticCurveTo(64, 0, 64, r);
      g.lineTo(64, 64-r); g.quadraticCurveTo(64, 64, 64-r, 64);
      g.lineTo(r, 64); g.quadraticCurveTo(0, 64, 0, 64-r);
      g.lineTo(0, r); g.quadraticCurveTo(0, 0, r, 0);
      g.closePath(); g.fill();
      g.fillStyle = '#fff';
      g.font = 'bold ' + (SHORT_LABEL.length >= 4 ? 22 : 30) + 'px Arial, sans-serif';
      g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillText(SHORT_LABEL, 32, 34);
      return c.toDataURL('image/png');
    } catch (e) { return null; }
  }

  function applyFavicon() {
    var url = makeFavicon();
    if (!url) return;
    window.__cloakSilent = true;
    try {
      document.querySelectorAll("link[rel*='icon']").forEach(function(l) {
        l.parentNode && l.parentNode.removeChild(l);
      });
      var link = document.createElement('link');
      link.rel = 'icon'; link.type = 'image/png'; link.href = url;
      (document.head || document.documentElement).appendChild(link);
      var link2 = document.createElement('link');
      link2.rel = 'shortcut icon'; link2.type = 'image/png'; link2.href = url;
      (document.head || document.documentElement).appendChild(link2);
    } finally {
      setTimeout(function() { window.__cloakSilent = false; }, 0);
    }
  }

  // ============ Layer 2: title prefix ============
  function applyTitle() {
    var orig = document.title || '';
    if (orig.indexOf(TITLE_PREFIX) === 0) return;
    // Strip old bracket-style [Cxxx · serial] + new colon-style Cxxx · serial · residue
    var clean = orig
      .replace(/^\\[.*?\\]\\s*/, '')
      .replace(/^C\\d+\\s*(?:·[^·]*·\\s*)?/, '');
    window.__cloakSilent = true;
    try { document.title = TITLE_PREFIX + clean; }
    finally { setTimeout(function() { window.__cloakSilent = false; }, 0); }
  }

  // ============ Layer 3: in-page floating badge ============
  function applyBadge() {
    try {
      var doc = document;
      if (!doc.body) return;
      var BID = '__cloak_env_badge__';
      var old = doc.getElementById(BID);
      if (old && old.dataset.label === ENV_NAME) return;
      if (old) old.parentNode && old.parentNode.removeChild(old);
      window.__cloakSilent = true;
      try {
        var box = doc.createElement('div');
        box.id = BID;
        box.dataset.label = ENV_NAME;
        var label = SERIAL ? (ENV_NAME + ' · ' + SERIAL) : ENV_NAME;
        box.textContent = label;
        box.style.cssText = [
          'all: initial',                       // immune to page CSS
          'position: fixed',
          'top: 6px',
          'left: 6px',
          'z-index: 2147483647',                // top of stack
          'background: ' + LABEL_COLOR,
          'color: #ffffff',
          'font: 700 16px/1 -apple-system,"Segoe UI","Microsoft YaHei",Arial,sans-serif',
          'padding: 6px 12px',
          'border-radius: 8px',
          'box-shadow: 0 2px 8px rgba(0,0,0,0.35), 0 0 0 2px rgba(255,255,255,0.25) inset',
          'letter-spacing: 0.5px',
          'pointer-events: none',               // don't eat clicks
          'user-select: none',
          'white-space: nowrap',
          'opacity: 0.92'
        ].join(';');
        doc.body.appendChild(box);
      } finally {
        setTimeout(function() { window.__cloakSilent = false; }, 0);
      }
    } catch (e) {}
  }

  function tick() { applyFavicon(); applyTitle(); applyBadge(); }

  // ============ Initial fire ============
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', tick);
  } else { tick(); }
  window.addEventListener('load', tick);
  document.addEventListener('visibilitychange', function() {
    if (!document.hidden) tick();
  });

  // ============ Layer 4: head MutationObserver ============
  function watchHead() {
    var head = document.head || document.getElementsByTagName('head')[0];
    if (!head) { setTimeout(watchHead, 200); return; }
    try {
      var mo = new MutationObserver(function() {
        if (window.__cloakSilent) return;
        tick();
      });
      mo.observe(head, { childList: true, subtree: true });
    } catch (e) {}
  }
  watchHead();

  // ============ Layer 5: body MutationObserver (badge recovery) ============
  function watchBody() {
    if (!document.body) { setTimeout(watchBody, 200); return; }
    try {
      var mo2 = new MutationObserver(function() {
        if (window.__cloakSilent) return;
        if (!document.getElementById('__cloak_env_badge__')) applyBadge();
      });
      mo2.observe(document.body, { childList: true });   // childList only — cheap
    } catch (e) {}
  }
  watchBody();

  // ============ Layer 6: SPA navigation interception ============
  try {
    var _ps = history.pushState, _rs = history.replaceState;
    history.pushState = function() {
      var r = _ps.apply(this, arguments);
      setTimeout(tick, 50);   // 50ms delay: let SPA finish DOM mutations first
      return r;
    };
    history.replaceState = function() {
      var r = _rs.apply(this, arguments);
      setTimeout(tick, 50);
      return r;
    };
    window.addEventListener('popstate',   function() { setTimeout(tick, 50); });
    window.addEventListener('hashchange', function() { setTimeout(tick, 50); });
  } catch (e) {}

  // ============ Layer 7: low-frequency sanity check ============
  // ONLY a cheap getElementById here. If you add anything else, you're back in Pitfall 9.
  setInterval(function() {
    if (!document.getElementById('__cloak_env_badge__')) tick();
  }, 2000);
})();
`;
}

module.exports = { buildLabelInjectScript };
```

## ESM consumer (single source of truth via createRequire)

```js
// proxy/launcher.mjs
import { launch } from 'cloakbrowser/puppeteer';
import { createRequire } from 'module';
const _require = createRequire(import.meta.url);
const { buildLabelInjectScript: _buildLabel } = _require('./label-inject.js');

function buildInjectScript(envName, serial, labelColor) {
  return _buildLabel(envName, serial, labelColor);  // delegate, never copy
}

// usage at launch:
const browser = await launch({ ...opts });
const page = (await browser.pages())[0] || await browser.newPage();
await page.evaluateOnNewDocument(buildInjectScript(ACCOUNT_NAME, SERIAL, LABEL_COLOR));
```

## Post-connect re-injection (Layer 8 — `puppeteer.connect()` race)

```js
// azure/flow.js (CJS)
const { buildLabelInjectScript } = require('../proxy/label-inject');

async function applyStealthToBrowser(browser, accountInfo) {
  const script = buildLabelInjectScript(accountInfo.name, accountInfo.serial, accountInfo.color);
  // 1. Catch existing tabs at connect time
  for (const page of await browser.pages()) {
    try { await page.evaluate(script); } catch (_) {}
  }
  // 2. Catch future tabs (user-opened or window.open)
  browser.on('targetcreated', async (t) => {
    try {
      const p = await t.page();
      if (!p) return;
      await p.evaluate(buildLabelInjectScript(accountInfo.name, accountInfo.serial, accountInfo.color));
    } catch (_) {}
  });
}
```

## Title-stripping regex hygiene

When users complain the title shows `Cxxx · serial · Cxxx · serial · page-title` (double prefix), it's a regex bug in `applyTitle`. The `clean` step must strip BOTH:
- Old bracket format: `^\[.*?\]\s*`
- New colon format: `^C\d+\s*(?:·[^·]*·\s*)?`

Test cases to verify the strip works:
- `[C011 · serial1] Sign up` → `Sign up`
- `C011 · serial1 · Sign up` → `Sign up` (after one route change re-applying prefix)
- `Sign up` (fresh load) → `Sign up`

The non-capturing `(?:·[^·]*·\s*)?` makes serial optional, since some accounts may not have one.

## Pitfalls during build-out

1. **`pointer-events: none` is mandatory on the badge** — without it, clicks on the top-left corner of any page get eaten. This is the #1 bug operators report when first deploying this.
2. **Don't skip `all: initial` on the badge style** — pages with aggressive CSS resets (`* { all: revert; }`) can punch holes in your styling otherwise.
3. **The 2s interval (Layer 7) MUST stay cheap** — `getElementById` + early-return. The instant you make it do DOM measurements / encoding / network, you're back in Pitfall 9.
4. **`subtree: true` on the body observer is too expensive** on rich pages like Azure portal (10000+ mutations per second). Stick to `childList` on direct body children.
5. **The `__cloakSilent` flag is shared across favicon, title, AND badge** — make sure all three writers set it before mutating and clear it via `setTimeout(..., 0)` after. Skipping any one creates an infinite re-injection loop.
6. **`z-index: 2147483647` is the signed-int32 max** — using anything smaller can lose to pages that themselves use very high z-indexes (Microsoft account chooser uses `1000000000`+).

## When this is NOT the right answer

- If you only need to identify ONE browser, the favicon + title alone are fine. The badge is for **multi-environment** operator workflows where 20-100 browsers are open and the operator needs to glance at any one and know which account it is.
- If the site is NOT a SPA (static HTML, full reloads on every nav), Layers 6/7 are overkill — Layer 1+2+3+4 are sufficient.
- If you control the rendering (Electron BrowserWindow rendering your own HTML), use the window title via `BrowserWindow.setTitle()` and skip page injection entirely.

## Related skills

- `cloakbrowser-setup` — multi-profile manager UI conventions
- `puppeteer-fingerprint-browser-automation` — the broader stealth-automation envelope this label scheme lives inside
