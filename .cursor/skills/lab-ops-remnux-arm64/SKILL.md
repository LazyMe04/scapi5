---
name: lab-ops-remnux-arm64
description: Boots and operates the REMnux VM, remnux MCP HTTP server, and nested ARM64 QEMU guest. Use when the user mentions REMnux, QEMU, ARM64 guest, VBoxManage, port 2222, 2232, 3000, MCP token, ssh remnux, or snapshot restore.
---

# Lab ops — REMnux and ARM64 QEMU

Authoritative narratives: `first_run/remnux-ssh-setup.md`, `second_run/main_summary_run2.md`. Guest scripts live at `~/arm64-vm/`; copies in `second_run/` are the edit source.

## Ports (do not collapse these)

| Listener | What it is |
|---|---|
| Windows `127.0.0.1:2222` | VirtualBox NAT → REMnux `:22` (`ssh remnux`) |
| Windows `127.0.0.1:2232` | SSH tunnel → REMnux loopback `:2222` → QEMU hostfwd → ARM64 guest `:22` |
| Windows `127.0.0.1:3000` | VirtualBox NAT → REMnux MCP HTTP `:3000` |
| REMnux `127.0.0.1:2222` | QEMU user-mode forward to ARM64 sshd |

`PORT_OPEN` on 2232 is QEMU completing TCP, not a ready guest. Ready = SSH banner / kex. Login from Windows needs `-i %USERPROFILE%\.ssh\id_ed25519`. Login from inside REMnux to the guest will fail key auth (wrong key); that is expected.

## Cold start — REMnux + MCP

VM name: `remnux-noble-amd64-virtualbox`. Guest user `remnux` / `malware`. sshd is disabled at boot on purpose.

```powershell
$vb = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $vb startvm "remnux-noble-amd64-virtualbox" --type headless
& $vb guestcontrol "remnux-noble-amd64-virtualbox" --username remnux --password malware `
  run --exe /bin/bash --wait-stdout --wait-stderr -- -c `
  "echo malware | sudo -S bash -c 'ssh-keygen -A; chmod 600 /etc/ssh/ssh_host_*_key; systemctl start ssh'"
netstat -ano | Select-String ":2222|:3000"
& $vb controlvm "remnux-noble-amd64-virtualbox" natpf1 "ssh,tcp,127.0.0.1,2222,,22"
& $vb controlvm "remnux-noble-amd64-virtualbox" natpf1 "mcp,tcp,127.0.0.1,3000,,3000"
```

If host keys already exist, still `chmod 600` private keys (`0644` makes sshd exit with "no hostkeys"). After snapshot restore: `ssh-keygen -R "[127.0.0.1]:2222"`.

Start MCP inside the guest (token file is `second_run/mcp_token.txt` on Windows; do not commit it):

```bash
MCP_TOKEN=$(cat ~/mcp_token.txt) nohup remnux-mcp-server \
  --mode=local --transport=http --http-host=0.0.0.0 --http-port=3000 --sandbox \
  > ~/mcp-server.log 2>&1 &
```

`--sandbox` confines `upload_from_host` to `/home/remnux/files/samples` on the guest.

NAT binds are loopback-only. `natpf1` is the VirtualBox 7.2 subcommand. Git Bash: `MSYS_NO_PATHCONV=1` for VBoxManage paths.

## Cold start — ARM64 guest

Do not use firmware/GRUB boot. Ubuntu 24.04 ARM64 cloud image has no `/grub/grub.cfg` on root; shim hangs at 100% CPU. Use `~/arm64-vm/start-arm64.sh` (`-kernel` / `-initrd`, `-cpu max`, `-smp 1`).

```powershell
ssh remnux "~/arm64-vm/start-arm64.sh"
ssh -N -f -L 2232:127.0.0.1:2222 remnux
ssh remnux "~/arm64-vm/wait-guest.sh"
ssh -p 2232 -i "$env:USERPROFILE\.ssh\id_ed25519" -o StrictHostKeyChecking=no ubuntu@127.0.0.1
```

`wait-guest.sh` reports ready on kex only; ignore `Permission denied` from REMnux's own key.

Expect TCG 10–20x slowdown. `-smp 2` starves REMnux sshd. MCP may drop under boot load; the server process can still be alive.

Verify: `uname -m` → `aarch64`. x86_64 binary → `Exec format error` (126). Snapshot `cloudinit-done` skips ~35 min cloud-init; use it before every malware rehearsal (see malware-isolation skill).

## GUI from SSH (REMnux)

Lift `DISPLAY=:0`, `XAUTHORITY=$(ls /run/user/1000/.mutter-Xwaylandauth.*)`, `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR` from a live GUI process. Cookie filename is random; glob it.

## Verify layers separately

VM running → NAT forwards present → guest sshd/MCP listening → token accepted → tool call. Do not treat one layer as proof of the next.
