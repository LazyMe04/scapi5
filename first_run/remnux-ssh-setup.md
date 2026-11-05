# SSH into REMnux on VirtualBox (Windows host) — Working Setup

Status: **working**. Connect with `ssh remnux`.

## Environment

| Item | Value |
|---|---|
| Host | Windows 11 Pro, built-in OpenSSH (`C:\WINDOWS\System32\OpenSSH\ssh.exe`) |
| VM name | `remnux-noble-amd64-virtualbox` |
| Guest | Ubuntu 24.04.3 LTS, REMnux v2026.6.26, Guest Additions 7.1.2 |
| NIC1 | NAT, guest IP `10.0.2.15` |
| NIC2 | Host-only (`VirtualBox Host-Only Ethernet Adapter`) |
| Port forward | `ssh,tcp,127.0.0.1,2222,,22` (shipped with the appliance) |
| Guest creds | `remnux` / `malware` |
| VBoxManage | `C:\Program Files\Oracle\VirtualBox\VBoxManage.exe` |

Connection path is host `127.0.0.1:2222` → guest `:22` over the NAT forward. The guest's
`10.0.2.15` is **not** reachable from the host — NAT is outbound-only, which is why the
forward exists.

## The problem that blocked it

Two independent issues, in order:

1. **sshd is disabled by default on REMnux.** Deliberate — it is a malware-analysis box, so
   default-off SSH reduces attack surface if a sample tries to pivot.
2. **Host keys shipped as `0644`.** `systemctl start ssh` failed with a generic control-process
   error. The real cause only appears under `sshd -t`:

   ```
   Permissions 0644 for '/etc/ssh/ssh_host_rsa_key' are too open.
   This private key will be ignored.
   sshd: no hostkeys available -- exiting.
   ```

   sshd re-checks key permissions on every start and *ignores* offending keys rather than
   refusing outright, so the surfaced error is the misleading "no hostkeys available".

## Fix and setup

All guest commands were run from the host over VirtualBox Guest Additions, so no console
access was needed. Equivalent commands typed directly in the REMnux terminal work identically.

### 1. Fix host key permissions and start sshd

In the REMnux terminal:

```bash
sudo chmod 600 /etc/ssh/ssh_host_*_key
sudo chmod 644 /etc/ssh/ssh_host_*_key.pub
sudo chown root:root /etc/ssh/ssh_host_*
sudo sshd -t && echo CONFIG_OK
sudo systemctl start ssh
systemctl is-active ssh          # -> active
```

Or driven from the Windows host without touching the VM console:

```powershell
$vb = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $vb guestcontrol "remnux-noble-amd64-virtualbox" --username remnux --password malware `
  run --exe /bin/bash --wait-stdout --wait-stderr -- -c `
  "echo malware | sudo -S bash -c 'chmod 600 /etc/ssh/ssh_host_*_key; chmod 644 /etc/ssh/ssh_host_*_key.pub; chown root:root /etc/ssh/ssh_host_*; systemctl start ssh'"
```

Note the argv form: `--exe /bin/bash -- -c "..."`. Passing `-- bash -lc "..."` fails with
`cannot execute binary file`, because the first token after `--` is argv[0], not an argument.

A harmless `Missing privilege separation directory: /run/sshd` warning may appear; systemd
creates the directory and the service still reaches `active`.

### 2. Install the host public key

```powershell
# Reuse the existing key, or create one:
#   ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\id_ed25519" -N '""'
$vb  = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
$pub = (Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub").Trim()
& $vb guestcontrol "remnux-noble-amd64-virtualbox" --username remnux --password malware `
  run --exe /bin/bash --wait-stdout --wait-stderr -- -c `
  "mkdir -p ~/.ssh; chmod 700 ~/.ssh; grep -qxF '$pub' ~/.ssh/authorized_keys 2>/dev/null || echo '$pub' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys"
```

### 3. Host SSH config

Appended to `C:\Users\VJU_LONGBCSE2023\.ssh\config`:

```
Host remnux
  HostName 127.0.0.1
  Port 2222
  User remnux
  IdentityFile ~/.ssh/id_ed25519
  ForwardX11 yes
  ForwardX11Trusted yes
```

## Usage

```powershell
ssh remnux                                  # shell
scp sample.exe remnux:~/                    # host -> guest
scp remnux:~/report.txt .                   # guest -> host
sftp remnux                                 # interactive transfer
ssh remnux gnome-calculator                 # GUI app, needs an X server on Windows
```

X11 forwarding is already enabled in the alias but needs an X server running on Windows —
[VcXsrv](https://sourceforge.net/projects/vcxsrv/) or [Xming](http://www.straightrunning.com/XmingNotes/).

VNC alternative, if X11 forwarding is awkward:

```bash
# on REMnux
sudo apt install -y tigervnc-standalone-server
vncpasswd
vncserver :1
```

```powershell
# on Windows, then point a VNC client at localhost:1
ssh -L 5901:localhost:5901 remnux
```

## Open item

sshd is **not enabled at boot** (`systemctl is-enabled ssh` → `disabled`), so it stops after a
VM restart. Two options:

- Re-run `sudo systemctl start ssh` after each boot — keeps the malware-VM attack surface minimal.
  The permission fix is persistent, so only the start command is needed.
- Or make it persistent: `sudo systemctl enable ssh`.

REMnux also ships an `sshd start` wrapper that does the same thing as the systemctl call.

## Troubleshooting

| Symptom | Cause / check |
|---|---|
| `Connection refused` on port 2222 | sshd not running in guest — `systemctl is-active ssh` |
| Port open but no SSH banner | same as above; port forward answers even when sshd is down |
| `systemctl start ssh` fails, vague error | run `sudo sshd -t` for the real reason — usually key permissions |
| `Permission denied (publickey,password)` | key not in guest `authorized_keys`, or `~/.ssh` perms wrong (`700` dir, `600` file) |
| `cannot execute binary file` from guestcontrol | argv error — use `--exe /bin/bash -- -c "cmd"` |

Useful host-side inspection commands:

```powershell
$vb = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $vb list runningvms
& $vb showvminfo "remnux-noble-amd64-virtualbox" --machinereadable | Select-String '^(nic|Forwarding)'
& $vb guestproperty enumerate "remnux-noble-amd64-virtualbox" | Select-String 'Net|IP'
```
