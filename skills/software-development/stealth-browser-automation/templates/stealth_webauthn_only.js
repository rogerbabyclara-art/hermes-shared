/**
 * Drop-in replacement for legacy `stealth.js` files inherited from
 * MoreLogin / ADSPower / puppeteer-extra-stealth era.
 *
 * Why this exists: see stealth-browser-automation pitfall #16. CloakBrowser's
 * C++ binary already returns correct values for webdriver / plugins / UA /
 * WebGL / languages / timezone / Canvas / WebRTC. Every JS prototype hook in
 * the legacy stealth.js leaves a `toString()` shape difference that
 * FingerprintJS 2024+ checks as a stealth-plugin signature — i.e. the legacy
 * file is now a *regression*, not a defense.
 *
 * What we keep:
 *   - WebAuthn / passkey API rejection. This is *business logic*, not
 *     fingerprint stealth. Microsoft login auto-prompts "Save passkey?" via
 *     an OS-level Windows Security Center dialog after successful auth.
 *     puppeteer can't dismiss OS windows. The only way to suppress the
 *     dialog is to make `navigator.credentials.create()` reject before MS
 *     server ever decides to offer passkey enrollment — server sees the
 *     failure and falls back to standard login flow.
 *
 * What we delete vs the typical legacy file:
 *   - navigator.webdriver defineProperty (binary already handles)
 *   - navigator.plugins hardcoded 5-entry PDF Viewer list (binary returns 1)
 *   - navigator.languages hardcoded ja (set via launch({locale}) instead)
 *   - WebGL Intel/Iris hardcoded strings (collapses entropy across seeds)
 *   - permissions.query Notification patch (binary handles)
 *   - chrome.runtime stub (binary handles)
 *   - iframe.contentWindow webdriver hook (binary handles)
 *   - delete window.cdc_* (puppeteer-core doesn't even inject these)
 *
 * Same exports as the legacy file — drop-in replacement, callers do not change:
 *   { applyStealth, applyStealthToBrowser, STEALTH_SCRIPT }
 *
 * Validation after dropping in:
 *   1. `node --check stealth.js`
 *   2. `node -e "console.log(require('./stealth.js').STEALTH_SCRIPT.length)"`
 *      — expect ~860 chars (vs ~4500 legacy)
 *   3. DevTools self-check on a fresh account — see
 *      stealth-browser-automation references/fingerprint-audit-checklist.md
 *      Required deltas after the swap:
 *        webdriver_toString → "function get webdriver() { [native code] }"
 *        plugins.length    → 1 (not 5)
 *        webgl_renderer    → ANGLE-prefixed Windows GPU (not "Intel Iris OpenGL Engine")
 */

const STEALTH_SCRIPT = `
(() => {
  // Disable WebAuthn / passkey API — prevents Microsoft login's "Save passkey?"
  // OS-level dialog (Windows Security Center) that puppeteer cannot dismiss.
  // Rejecting navigator.credentials.create() at the JS layer makes the MS
  // server fall back to standard login flow instead of offering passkey enroll.
  try {
    if (navigator.credentials) {
      navigator.credentials.create = () => Promise.reject(new DOMException('NotAllowedError', 'NotAllowedError'));
      navigator.credentials.get = () => Promise.reject(new DOMException('NotAllowedError', 'NotAllowedError'));
    }
    // isUserVerifyingPlatformAuthenticatorAvailable() → false signals to MS
    // that no platform authenticator exists, so they don't push passkey UI.
    if (window.PublicKeyCredential) {
      window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable = () => Promise.resolve(false);
      window.PublicKeyCredential.isConditionalMediationAvailable = () => Promise.resolve(false);
    }
  } catch (e) {}
})();
`;

/**
 * Inject stealth script into a single page. Must be called before page.goto().
 *
 * @param {import('puppeteer-core').Page} page
 */
async function applyStealth(page) {
  await page.evaluateOnNewDocument(STEALTH_SCRIPT);
}

/**
 * Inject into every current and future page on a browser instance.
 * Handles popups (OAuth, passkey-enroll redirect) via targetcreated.
 *
 * @param {import('puppeteer-core').Browser} browser
 */
async function applyStealthToBrowser(browser) {
  const pages = await browser.pages();
  for (const p of pages) {
    await applyStealth(p).catch(() => {});
  }
  browser.on('targetcreated', async (target) => {
    if (target.type() !== 'page') return;
    const p = await target.page().catch(() => null);
    if (p) await applyStealth(p).catch(() => {});
  });
}

module.exports = { applyStealth, applyStealthToBrowser, STEALTH_SCRIPT };
