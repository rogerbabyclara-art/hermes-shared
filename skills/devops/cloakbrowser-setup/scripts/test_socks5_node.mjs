// test_socks5_node.mjs
// Verify a SOCKS5 proxy works from Node, bypassing any Electron/CJS issues.
// Usage:
//   node test_socks5_node.mjs <host> <port> <user> <pass>
//   node test_socks5_node.mjs us.cliproxy.io 3010 'user-region-JP-sid-x-t-60' 'mypass'
//
// Use this when:
//   - Electron app says all IPs fail but you suspect it's the SocksProxyAgent ESM trap
//   - You want to confirm credentials work before debugging app code
//   - You want to verify TUN mode is actually routing Node traffic (re-run after enabling TUN)
//
// Exit codes:
//   0 = success (proxy returned an IP)
//   1 = SOCKS5 NotAllowed (provider blocks source IP, or bad creds, or geo-block)
//   2 = timeout (proxy unreachable from this network)
//   3 = unexpected error
//
// Diagnostic value: this script uses dynamic import() so it works the same way the
// Electron CJS code should — if this works but the Electron app doesn't, the bug
// is in your Electron integration (probably you did `require('socks-proxy-agent')`
// instead of `await import(...)`).

import https from "https";

const [, , host, port, user, pass] = process.argv;
if (!host || !port) {
  console.error("Usage: node test_socks5_node.mjs <host> <port> [<user> <pass>]");
  process.exit(3);
}

const { SocksProxyAgent } = await import("socks-proxy-agent");
const auth = user ? `${encodeURIComponent(user)}:${encodeURIComponent(pass || "")}@` : "";
const url = `socks5://${auth}${host}:${port}`;
console.log(`Using proxy: socks5://${user ? user + ":***@" : ""}${host}:${port}`);

const agent = new SocksProxyAgent(url);
const t0 = Date.now();

const req = https.request(
  {
    host: "ipinfo.io",
    port: 443,
    path: "/json",
    method: "GET",
    agent,
    timeout: 20000,
    headers: { "User-Agent": "skill-probe/1.0", Accept: "application/json" },
  },
  (res) => {
    let body = "";
    res.on("data", (c) => (body += c.toString("utf8")));
    res.on("end", () => {
      const ms = Date.now() - t0;
      try {
        const j = JSON.parse(body);
        console.log(`✓ OK ${ms}ms`);
        console.log(`  exit_ip: ${j.ip}`);
        console.log(`  country: ${j.country}`);
        console.log(`  city:    ${j.city}`);
        console.log(`  org:     ${j.org}`);
        process.exit(0);
      } catch (e) {
        console.error(`✗ Bad JSON after ${ms}ms: ${body.slice(0, 200)}`);
        process.exit(3);
      }
    });
  }
);

req.on("error", (e) => {
  const ms = Date.now() - t0;
  if (/NotAllowed/i.test(e.message)) {
    console.error(`✗ NotAllowed after ${ms}ms — provider rejects this source IP or credentials`);
    console.error(`  Common causes:`);
    console.error(`    1. Your source IP is geo-blocked (e.g. mainland China → 711proxy)`);
    console.error(`    2. Username/zone/region syntax doesn't match what provider expects`);
    console.error(`    3. Account out of credit or suspended`);
    console.error(`  Try: enable v2rayN TUN mode, re-run this script`);
    process.exit(1);
  }
  if (/timeout|ETIMEDOUT|ECONNREFUSED/i.test(e.message)) {
    console.error(`✗ Network failure after ${ms}ms: ${e.message}`);
    process.exit(2);
  }
  console.error(`✗ Error after ${ms}ms: ${e.message}`);
  process.exit(3);
});

req.on("timeout", () => {
  console.error(`✗ TIMEOUT after ${Date.now() - t0}ms`);
  req.destroy();
  process.exit(2);
});

req.end();
