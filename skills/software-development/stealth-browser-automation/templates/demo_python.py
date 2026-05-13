# Minimal CloakBrowser smoke test (Python, cloakbrowser >= 0.3.x).
# Verifies install + stealth Chromium binary + the four canonical knobs.
# Run: python demo_python.py
#
# Expected: a visible Chromium window opens, loads BrowserScan, you get
# 30 seconds to read the trust score (should be 95%+), then auto-closes.
#
# IMPORTANT: the import is `from cloakbrowser import launch` — NOT
# `from cloakbrowser.playwright import async_playwright` (that wrapper was
# removed in 0.3.x). If you copy this from the project README you'll hit
# ImportError. The signature is:
#   launch(headless=True, proxy=None, args=None, stealth_args=True,
#          timezone=None, locale=None, geoip=False, backend=None,
#          humanize=False, ...)
# `fingerprint` is NOT a top-level kwarg — pass it via args=[...].

import time
from cloakbrowser import launch

SEED = 12345  # change this to get a new identity (canvas/webgl/UA/fonts all rotate)

browser = launch(
    headless=False,                   # visible — always start visible while learning
    humanize=True,                    # bezier mouse + real keyboard rhythm + scroll
    geoip=True,                       # WebRTC + timezone/locale match egress IP
    args=[f"--fingerprint={SEED}"],   # seed via Chromium arg (not a top-level kwarg)
    # proxy="http://user:pass@host:port",  # uncomment to add a proxy
)

context = browser.new_context()
page = context.new_page()

print("Loading BrowserScan...")
page.goto("https://www.browserscan.net/", timeout=60000)

print("Inspect the score for 30s, then auto-close.")
time.sleep(30)

browser.close()
print("Done.")
