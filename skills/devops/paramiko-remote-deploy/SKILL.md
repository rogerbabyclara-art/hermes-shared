---
name: paramiko-remote-deploy
description: Automate remote Linux VPS deployment from Windows (or any host) using Python paramiko over SSH — install packages, write system config files, manage systemd services, generate keys/UUIDs, all without an interactive shell. Use when scripting Xray/Hermes/Docker/nginx deployments to fresh VPS instances, when `ssh user@host 'cmd'` one-liners get unwieldy, or when plink/native ssh hits hostkey/TTY/sudo dead ends. Covers sudo-password injection, SFTP-vs-redirect file writes, hostkey auto-add, parsing tool output across versions, and Tencent Cloud / Alibaba Cloud security-group gotchas.
when_to_use: scripting one-shot remote deploys to fresh VPS; SSH automation from Windows where plink/ssh interactive prompts kill scripts; writing system files (/etc, /usr/local/etc) on remote where sudo redirects fail
version: 1.0.0
languages: all
---

# paramiko-remote-deploy

When you script a remote Linux deploy from a non-Linux workstation (Hermes on Windows, agent on macOS, CI on anything), `ssh user@host 'big script'` and `plink -batch` both have failure modes that bite repeatedly: hostkey prompts, sudo password prompts, redirect-into-system-path permission losses, lost stderr, lost return codes. **paramiko** sidesteps all of them but has its own set of well-known traps. This skill is the playbook.

## When to reach for paramiko vs. plain ssh

| Situation | Tool |
|---|---|
| One-line probe (`uname -a`, `cat /etc/os-release`) | plain `ssh` |
| Multi-step deploy with conditionals, parsing output | **paramiko** |
| Need SFTP file uploads alongside commands | **paramiko** |
| Fresh VPS, unknown hostkey, password auth, no SSH config | **paramiko** (AutoAddPolicy) |
| Interactive `sudo` password prompt | **paramiko** with stdin injection |
| Long-running remote command needing live output | `ssh -t` or paramiko + channel.recv_ready loop |

## Standard template

Use this skeleton for any new deploy script. Copy from `templates/paramiko_deploy_skeleton.py`.

```python
import paramiko, json, base64

HOST = "<ip>"
USER = "<ubuntu|root>"
PWD  = "<pass>"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # fresh VPS, no known_hosts
client.connect(HOST, port=22, username=USER, password=PWD, timeout=15)

def run(cmd, label, timeout=120, sudo=True):
    if sudo and USER != "root":
        full = f"echo '{PWD}' | sudo -S -p '' bash -c {repr(cmd)}"
    else:
        full = cmd
    _, stdout, stderr = client.exec_command(full, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    print(f"\n===== {label} =====\n$ {cmd[:160]}")
    if out: print(out)
    # filter sudo password echo noise
    if err and "sudo:" not in err and "password" not in err.lower():
        print(f"[stderr] {err}")
    return out, err
```

## Critical pitfalls (every one of these has bitten real sessions)

### 1. `sudo bash -c 'cmd > /system/path'` loses the redirect

`>` is parsed by the OUTER shell, which runs as the unprivileged user. sudo only sees `cmd`; the file write happens in the parent shell with no privileges. You get `bash: line 1: /usr/local/etc/.../config.json: Permission denied` even though sudo "succeeded".

**Wrong:**
```python
run(f"echo '{b64}' | base64 -d > /usr/local/etc/xray/config.json")
# Permission denied on the redirect
```

**Right — SFTP put to /tmp, then sudo cp:**
```python
sftp = client.open_sftp()
with sftp.open("/tmp/staged_config.json", "w") as f:
    f.write(cfg_text)
sftp.close()
run("cp /tmp/staged_config.json /usr/local/etc/xray/config.json && "
    "chown root:root /usr/local/etc/xray/config.json && "
    "chmod 644 /usr/local/etc/xray/config.json")
```

**Also right — `sudo tee` for short payloads:**
```python
run(f"echo '{b64}' | base64 -d | sudo -S -p '' tee /usr/local/etc/xray/config.json > /dev/null", sudo=False)
```
(Note: pass `sudo=False` to the helper because the sudo is already inline; the outer redirect to `/dev/null` is fine because it goes to a world-writable path.)

### 2. Hostkey verification kills scripts

`plink -batch` rejects unknown hosts. `echo y | ssh ...` hangs forever waiting for password. The fix is paramiko's `AutoAddPolicy()` — accepts the new host's key and stores it. For production with stable hosts, switch to `RejectPolicy()` after first connect, or pre-populate `~/.ssh/known_hosts` via `ssh-keyscan`.

### 3. Reinstalling the VPS changes the hostkey

After OS reinstall, paramiko throws `BadHostKeyException` if you've cached a previous key. Two options:
- Stay on `AutoAddPolicy()` for throwaway/dev VPS — it silently overwrites.
- Pre-clear: `ssh-keygen -R <ip>` before reconnecting, or use `WarningPolicy()` to log and continue.

### 4. Default user is NOT root on cloud images

- Tencent Cloud Ubuntu: `ubuntu` / your set password (root login disabled by default)
- AWS Ubuntu: `ubuntu` / key-only
- Alibaba CentOS: `root` / your set password
- Tencent OpenCloudOS: `root` / your set password

If the first `paramiko.connect()` raises `AuthenticationException` on a freshly-installed image, the username changed — try `ubuntu` before assuming wrong password.

### 5. sudo password injection: `echo $PWD | sudo -S` quoting

When you wrap a complex command in `sudo -S bash -c '...'`, the inner single quotes can conflict with the outer single quotes. Use Python's `repr()` on the inner command to get a properly-escaped Python string-literal that bash accepts:

```python
full = f"echo '{PWD}' | sudo -S -p '' bash -c {repr(cmd)}"
```

`-p ''` suppresses the password prompt printout. `-S` reads password from stdin. Always swallow `sudo:` and `password` lines from stderr so they don't pollute logs.

### 6. exec_command timeout kills long apt installs

`apt-get install` with hundreds of MB can exceed paramiko's default 15s. Pass `timeout=240` (or higher) explicitly for any install/download step. Watch for `socket.timeout` exceptions and bump.

### 6b. Multi-minute installs drop the SSH channel — use fire-and-poll, not one long exec_command

Even with `timeout=900`, paramiko's channel can die mid-install with `SSHException: SSH session not active`. Causes: NAT idle timeout, no keepalive, ServerAliveInterval not set on the agent side, the wrapping host's process supervisor (e.g. Hermes terminal tool clamping background waits to 180s). Symptom: `git clone` of a big repo or `pip install` of a heavy package starts fine, then the Python script crashes with `SSH session not active` even though the remote process is **still running** on the VPS.

**Don't try to keep one channel alive for 10 minutes.** Instead, kick off the long task in a way that survives channel loss, then poll:

**Pattern A — nohup the long task, poll for completion:**
```python
# Kick off, return immediately
client.exec_command(
    "nohup bash /tmp/install.sh > /tmp/install.log 2>&1 < /dev/null & echo $!",
    timeout=30
)
# Reconnect periodically and check
while True:
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, PWD, timeout=15)
    _, o, _ = c.exec_command("pgrep -f install.sh | wc -l", timeout=20)
    running = int(o.read().strip())
    _, o, _ = c.exec_command("ls /usr/local/bin/<artifact> 2>/dev/null && echo OK || echo PENDING", timeout=20)
    done = "OK" in o.read().decode()
    c.close()
    if not running or done: break
    time.sleep(15)
```

**Pattern B — set keepalive on the transport BEFORE long exec:**
```python
client.get_transport().set_keepalive(30)   # send NOOP every 30s
```
Helps for moderately long commands (1-3 min) but won't save you past ~5 min if the wrapping host kills the script process itself.

**Pattern C — escape paramiko entirely for the long phase**: SFTP-put the install script, then run it via `at now` or systemd-run as a detached unit. Poll with fresh connections.

**Key insight from real session**: the install was still progressing on the VPS (`ps aux` showed `git clone hermes-agent` happily running) — the Python script's channel just died. Always check the remote state with a fresh connection before assuming the install failed. **"My side dropped" ≠ "the install died".**

**When running this from inside Hermes**: the `terminal` tool caps foreground at 600s and clamps `process(action=wait)` to ~180s. A 10-minute install will appear to "fail" from inside the agent even when both paramiko AND the install are fine. Default to **fire-and-poll from the start** for any deploy you expect to exceed 3 minutes — don't try to ride one foreground call through.

### 7. Tool output formats drift across versions

Auto-parsing CLI output is fragile. Real example: `xray x25519` changed from `PublicKey: xxx` (v25) to `Password (PublicKey): xxx` (v26). Write regexes to accept both shapes:

```python
re.search(r"(?:Password|PublicKey|公钥)[^:]*:\s*([A-Za-z0-9_\-]+)", out)
```

When possible, prefer JSON output flags (`--json`, `-o json`) over text-scraping.

### 8. Cloud security groups are NOT the same as VPS firewall

Opening `iptables -I INPUT -p tcp --dport 443 -j ACCEPT` on the VPS does NOTHING if the cloud provider's security group blocks 443 at the network edge. After any deploy that opens a new port, remind the user (or programmatically check via cloud API if available) to open the port in the cloud console security group. Default policies:
- Tencent Cloud: only 22 + ICMP open
- AWS: only 22
- Alibaba: only 22 + a few specific ports

### 9. Don't leave script files with passwords on disk

These deploy scripts hold passwords in plaintext. Either: (a) read from env vars, (b) put them under a path that gets cleaned, or (c) delete after run. At minimum, prefix throwaway scripts with `_tmp_` so they're greppable for cleanup later.

## Skill structure

- `templates/paramiko_deploy_skeleton.py` — copy-paste starter with helper `run()`, SFTP put, password injection, output filtering
- `references/xray-reality-deploy.md` — full worked example: fresh Ubuntu 22 → Xray VLESS Reality on :443 with `www.microsoft.com` SNI
- `scripts/probe_vps.py` — generic VPS recon script (OS, kernel, listening ports, installed proxies, firewall, exit IP, CPU). Run first on any new VPS before deploying.

## Verification checklist after any deploy

1. `systemctl is-active <service>` returns `active`
2. `ss -tlnp 'sport = :<port>'` shows the service binding
3. From the VPS itself: `curl -k --resolve <domain>:<port>:127.0.0.1 https://<domain>/` returns expected HTTP
4. Cloud security group has the port open (manual or programmatic check)
5. From an external client: actually connect and pass traffic. Don't claim "deployed" until external traffic verified.
