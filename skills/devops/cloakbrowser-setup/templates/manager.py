# Batch proxy + identity manager for CloakBrowser
# Replicates MoreLogin-style "account list, click to open" via CSV + CLI.
#
# Usage (PowerShell):
#   python manager.py list                    # list all identities
#   python manager.py test                    # batch test which proxies work
#   python manager.py open <identity_name>    # launch browser bound to identity
#
# CSV columns: name, proxy, fingerprint_seed, note
# Discipline: one account = one row, NEVER change a row's proxy or seed
# (mixing triggers "device changed" fraud signals).

import csv
import sys
import time
import requests
from pathlib import Path
from cloakbrowser import launch

CSV_FILE = Path(__file__).parent / "proxies.csv"


def load_accounts():
    with open(CSV_FILE, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cmd_list():
    accounts = load_accounts()
    print(f"\n{len(accounts)} identities:\n")
    print(f"{'name':<24} {'seed':<10} {'note':<24}")
    print("-" * 60)
    for a in accounts:
        print(f"{a['name']:<24} {a['fingerprint_seed']:<10} {a['note']:<24}")


def cmd_test():
    accounts = load_accounts()
    print(f"\nTesting {len(accounts)} proxies...\n")
    for a in accounts:
        try:
            r = requests.get(
                "https://api.ipify.org?format=json",
                proxies={"http": a["proxy"], "https": a["proxy"]},
                timeout=15,
            )
            ip = r.json().get("ip", "?")
            # Verify country to catch silent fallback to wrong region
            geo = requests.get(f"https://ipapi.co/{ip}/json/", timeout=10).json()
            country = geo.get("country_name", "?")
            org = geo.get("org", "?")[:30]
            print(f"  OK  {a['name']:<24} -> {ip} ({country}, {org})")
        except Exception as e:
            print(f"  ERR {a['name']:<24} -> {type(e).__name__}")


def cmd_open(name):
    accounts = load_accounts()
    a = next((x for x in accounts if x["name"] == name), None)
    if not a:
        print(f"Not found: {name}")
        print("Available: " + ", ".join(x["name"] for x in accounts))
        return

    print(f"Launching: {a['name']}")
    print(f"  proxy: {a['proxy']}")
    print(f"  seed:  {a['fingerprint_seed']}")

    browser = launch(
        headless=False,
        humanize=True,
        geoip=True,
        proxy=a["proxy"],
        args=[f"--fingerprint={a['fingerprint_seed']}"],
    )
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://ipinfo.io/", timeout=60000)

    print("Browser open. Ctrl+C to close.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python manager.py [list|test|open <name>]")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "test":
        cmd_test()
    elif cmd == "open":
        cmd_open(sys.argv[2] if len(sys.argv) > 2 else "")
    else:
        print(f"Unknown command: {cmd}")
