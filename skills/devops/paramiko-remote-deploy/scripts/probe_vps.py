"""Generic VPS recon — run this FIRST on any new remote before deploying.

Tells you: OS, kernel, RAM, disk, listening ports, installed proxy tools,
running services, firewall state, exit IP, CPU count. Catches surprises
(an existing nginx/xray on the box, wrong-distro install path, etc.)
before you waste time."""
import paramiko, sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "<vps-ip>"
USER = sys.argv[2] if len(sys.argv) > 2 else "ubuntu"
PWD  = sys.argv[3] if len(sys.argv) > 3 else "<password>"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=22, username=USER, password=PWD, timeout=15)

cmds = [
    ("hostname",                                   "hostname"),
    ("uname -a",                                   "kernel"),
    ("cat /etc/os-release | head -5",              "distro"),
    ("uptime",                                     "uptime"),
    ("free -h",                                    "memory"),
    ("df -h /",                                    "disk"),
    ("ss -tlnp 2>/dev/null | head -30",            "listening ports"),
    ("which xray sing-box v2ray nginx docker",     "installed tools"),
    ("systemctl list-units --type=service --state=running 2>/dev/null | head -25", "running services"),
    ("ufw status 2>/dev/null || iptables -L INPUT -n | head -10", "firewall"),
    ("curl -s -4 --max-time 8 ifconfig.me",        "exit IP"),
    ("getconf _NPROCESSORS_ONLN",                  "CPU cores"),
]

for cmd, label in cmds:
    _, stdout, stderr = client.exec_command(cmd, timeout=20)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    print(f"\n===== {label} ({cmd}) =====")
    if out: print(out)
    if err: print(f"[stderr] {err}")

client.close()
