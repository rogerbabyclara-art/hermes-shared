"""Paramiko remote-deploy skeleton.

Copy this file, fill in HOST/USER/PWD, then add your deploy steps in the
'STEPS' section. The helper `run()` handles sudo password injection,
output filtering, and timeout. Use SFTP (sftp.open) for any file write
into a system path — do NOT redirect into /etc or /usr/local via sudo bash.
"""
import paramiko
import base64
import json
import re

# ---------- connection config ----------
HOST = "<vps-ip>"
USER = "ubuntu"           # try 'ubuntu' first on Tencent/AWS Ubuntu, 'root' on Alibaba/Tencent CentOS
PWD  = "<password>"
PORT = 22

# ---------- connect ----------
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # fresh VPS; switch to RejectPolicy in prod
client.connect(HOST, port=PORT, username=USER, password=PWD, timeout=15)


def run(cmd, label, timeout=120, sudo=True):
    """Run a remote command. Handles sudo password injection and filters echo noise."""
    if sudo and USER != "root":
        # repr() guarantees proper single-quote escaping for bash -c
        full = f"echo '{PWD}' | sudo -S -p '' bash -c {repr(cmd)}"
    else:
        full = cmd
    print(f"\n===== {label} =====")
    print(f"$ {cmd[:200]}{'...' if len(cmd) > 200 else ''}")
    _, stdout, stderr = client.exec_command(full, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    if out:
        print(out)
    if err and "sudo:" not in err and "password" not in err.lower():
        print(f"[stderr] {err}")
    return out, err


def sftp_put_str(remote_path, content):
    """Upload a string as a file to remote. Use this for staging into /tmp,
    then `sudo cp /tmp/foo /etc/foo` to land system files (avoids redirect-loses-sudo)."""
    sftp = client.open_sftp()
    with sftp.open(remote_path, "w") as f:
        f.write(content)
    sftp.close()
    print(f"===== SFTP put {remote_path} ({len(content)} bytes) =====")


# ---------- STEPS ----------
# Replace below with your deploy steps. Examples:

# 1) Probe environment
run("uname -a && cat /etc/os-release | head -3", "probe")

# 2) Install packages
run("apt-get update -qq && apt-get install -y -qq curl unzip", "install deps", timeout=240)

# 3) Write a system config file (the right way)
config_text = json.dumps({"example": True}, indent=2)
sftp_put_str("/tmp/staged_config.json", config_text)
run("cp /tmp/staged_config.json /etc/example/config.json && "
    "chown root:root /etc/example/config.json && "
    "chmod 644 /etc/example/config.json", "deploy config")

# 4) Restart service + verify
run("systemctl restart example && sleep 2 && systemctl is-active example", "restart")
run("ss -tlnp 'sport = :443'", "verify listener")

# ---------- close ----------
client.close()
print("\n===== done =====")
