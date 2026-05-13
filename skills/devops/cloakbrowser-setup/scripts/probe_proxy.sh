#!/bin/bash
# Diagnose a residential proxy: is it alive, what country does it exit, is it datacenter-IP-blocked?
# Usage: ./probe_proxy.sh "http://user:pass@host:port"
#
# Returns:
#   - exit IP and country (verify region param worked)
#   - wrong-password test (distinguishes IP block from auth issue)
#   - timing data (fast = good, 30s timeout = packet drop)

PROXY="$1"
if [ -z "$PROXY" ]; then
  echo "Usage: $0 'http://user:pass@host:port'"
  exit 1
fi

# Extract user/host for wrong-pass test
HOST_PORT=$(echo "$PROXY" | sed -E 's|.*@||')
USER=$(echo "$PROXY" | sed -E 's|http://||; s|:.*||')

echo "=== 1. Source IP (your current outbound) ==="
curl -s --max-time 10 https://api.ipify.org && echo ""

echo ""
echo "=== 2. Proxy connectivity (correct creds) ==="
START=$(date +%s)
IP=$(curl -s --max-time 30 -x "$PROXY" https://api.ipify.org)
ELAPSED=$(( $(date +%s) - START ))
if [ -n "$IP" ]; then
  echo "OK  exit_ip=$IP  elapsed=${ELAPSED}s"
  echo ""
  echo "=== 3. Exit IP geo (verify country matches what you paid for) ==="
  curl -s --max-time 15 "https://ipapi.co/$IP/json/" | grep -E '"country_name"|"city"|"org"|"asn"'
else
  echo "FAIL no response in ${ELAPSED}s"
  echo ""
  echo "=== 3. Wrong-password test (distinguishes IP-block vs auth) ==="
  START=$(date +%s)
  HTTP_CODE=$(curl -s --max-time 15 -o /dev/null -w "%{http_code}" -x "http://${USER}:WRONGPASS@${HOST_PORT}" http://api.ipify.org)
  ELAPSED=$(( $(date +%s) - START ))
  echo "wrong-pass HTTP code: $HTTP_CODE  elapsed=${ELAPSED}s"
  if [ "$HTTP_CODE" = "000" ] && [ $ELAPSED -ge 14 ]; then
    echo ""
    echo ">>> DIAGNOSIS: source IP is blocked by proxy provider (silent drop)."
    echo ">>> Fix: route through residential network (v2rayN TUN, SSH tunnel, or clean VPS)."
  elif [ "$HTTP_CODE" = "407" ]; then
    echo ""
    echo ">>> DIAGNOSIS: auth issue. Check username/password and region syntax."
  fi
fi
