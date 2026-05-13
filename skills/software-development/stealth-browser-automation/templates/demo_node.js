// Minimal CloakBrowser smoke test (Node).
// Run: node demo_node.js
//
// Requires:  npm install cloakbrowser puppeteer-core
//            python -m cloakbrowser install   (one-time, 535MB)
//
// Expected: visible Chromium opens, loads BrowserScan, 10s pause, closes.

const { launch } = require('cloakbrowser/puppeteer');

(async () => {
  const browser = await launch({
    headless: false,
    humanize: true,
    geoip: true,
    fingerprint: 12345,
  });

  const page = await browser.newPage();
  console.log('Loading BrowserScan...');
  await page.goto('https://www.browserscan.net/');

  console.log('Inspect the score for 10s, then auto-close.');
  await new Promise(r => setTimeout(r, 10000));

  await browser.close();
  console.log('Done.');
})();
