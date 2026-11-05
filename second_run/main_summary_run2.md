# Run 2 — REMnux MCP Server Setup

**Date:** 2026-09-25
**Host:** Windows 11 Pro
**Guest:** REMnux v2026.6.26 (Ubuntu 24.04 LTS, noble), VM `remnux-noble-amd64-virtualbox`
**MCP server:** `@remnux/mcp-server` v0.1.75
**Status:** WORKING — connected, tools executing, 78/88 available
**Guide:** https://github.com/REMnux/remnux-mcp-server

---

## 1. What changed since run 1

REMnux was refreshed to a clean snapshot. Everything from `first_run/` (§3 of that doc) about
sshd, host keys, and port forwards was reset. The ARM64 QEMU work is gone from the guest.

Recovered in this run:

| Item | Before refresh | Now |
|---|---|---|
| VM power state | running | powered off → booted headless |
| sshd host keys | present | **absent** (`ssh-keygen -A` had not run on the clean image) |
| NAT port forward 2222 | present | **absent** from the `.vbox` config |
| `~/files/samples`, `~/files/output` | present | **absent** (default MCP work dirs) |
| `@remnux/mcp-server` in guest | n/a | v0.1.75 installed at `/usr/lib/node_modules` |

The old ARM64 QEMU stack (`~/arm64-vm/`) is not present. That work is not needed for the MCP
server — the MCP server runs the REMnux analysis toolkit, which is a separate concern from the
ARM64 emulation VM.

---

## 2. Architecture chosen

**Scenario 3 from the guide: HTTP transport, server inside REMnux, Claude Code on Windows.**

```
Windows host                              REMnux guest (VM)
-----------                              ------------------
claude (MCP client)                       remnux-mcp-server
  |  HTTP + Bearer token                    |  --mode=local
  |  POST /mcp                              |  --transport=http
  |                                         |  --http-host=0.0.0.0
  +--- 127.0.0.1:3000 --(VirtualBox NAT)-->+  guest :3000
```

Reasons:

- No SSH password stored on the Windows host. The alternative (`--mode=ssh`) requires
  `--password=malware` in plaintext in `C:\Users\VJU_LONGBCSE2023\.claude.json`; the package has
  no `--identity-file` flag, and `ssh2`'s agent path needs a Unix socket, which Windows OpenSSH's
  agent does not provide.
- The MCP server process itself lives inside the disposable VM, matching the guide's stated threat
  model ("the security boundary is the disposable container/VM").
- Token auth mandatory for non-loopback bind — satisfied with a 256-bit random token.

### Sandbox note

`--sandbox` is enabled. Because the server runs **inside** the guest in local mode,
`upload_from_host` resolves paths on the **REMnux machine**, not on Windows. So there is no
Windows-side ingest root to confine. The server defaults confinement to `samplesDir`:

```
REMnux MCP server started (upload_from_host confined to /home/remnux/files/samples)
```

Host → guest file transfer uses `scp` (see §6), not the MCP tools. A Windows path passed to
`upload_from_host` would fail with "No such file or directory" — that is the sandbox working, not
a defect.

---

## 3. Configuration

### NAT port forwards on the VM

Two rules, both re-added this run:

| Rule | Host | Guest | Purpose |
|---|---|---|---|
| `ssh` | 127.0.0.1:2222 | 22 | SSH admin access from Windows |
| `mcp` | 127.0.0.1:3000 | 3000 | MCP HTTP endpoint |

```powershell
$vb = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $vb controlvm "remnux-noble-amd64-virtualbox" natpf1 "ssh,tcp,127.0.0.1,2222,,22"
& $vb controlvm "remnux-noble-amd64-virtualbox" natpf1 "mcp,tcp,127.0.0.1,3000,,3000"
```

Bound to `127.0.0.1` on the host side, so neither is reachable from the LAN.

### Server launch (inside guest)

```bash
MCP_TOKEN=$(cat ~/mcp_token.txt) nohup remnux-mcp-server \
  --mode=local \
  --transport=http \
  --http-host=0.0.0.0 \
  --http-port=3000 \
  --sandbox \
  > ~/mcp-server.log 2>&1 &
```

Log: `~/mcp-server.log` in the guest.

### Claude Code registration (Windows)

```powershell
$token = Get-Content "C:\Users\VJU_LONGBCSE2023\Desktop\EM\second_run\mcp_token.txt"
claude mcp add --scope user remnux --transport http http://127.0.0.1:3000/mcp `
  --header "Authorization: Bearer $token"
```

Stored in `C:\Users\VJU_LONGBCSE2023\.claude.json`, user scope, so it is available in every
project. Token file kept at `second_run/mcp_token.txt`.

Verify: `claude mcp list` → `remnux: http://127.0.0.1:3000/mcp (HTTP) - ✔ Connected`

---

## 4. Boot-from-cold sequence

After any guest reboot or snapshot restore, all four steps are needed. Steps 1–2 exist because
sshd and the forwards are not persistent by design.

```powershell
# 1. Boot the VM
$vb = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $vb startvm "remnux-noble-amd64-virtualbox" --type headless

# 2. Wait for Guest Additions, then start sshd
#    (only needed if you want SSH; the MCP server is started in step 4 over SSH,
#     so you do need it)
& $vb guestcontrol "remnux-noble-amd64-virtualbox" --username remnux --password malware `
  run --exe /bin/bash --wait-stdout --wait-stderr -- -c `
  "echo malware | sudo -S bash -c 'ssh-keygen -A; systemctl start ssh'"

# 3. Re-add port forwards if missing (check first with netstat)
netstat -ano | grep LISTENING | Select-String ":2222|:3000"
& $vb controlvm "remnux-noble-amd64-virtualbox" natpf1 "ssh,tcp,127.0.0.1,2222,,22"
& $vb controlvm "remnux-noble-amd64-virtualbox" natpf1 "mcp,tcp,127.0.0.1,3000,,3000"

# 4. Start the MCP server in the guest
ssh remnux "MCP_TOKEN=`$TOKEN nohup remnux-mcp-server --mode=local --transport=http --http-host=0.0.0.0 --http-port=3000 --sandbox > ~/mcp-server.log 2>&1 &"
```

Stale host key after a snapshot restore — clear it once:

```powershell
ssh-keygen -R "[127.0.0.1]:2222"
```

---

## 5. Verified capabilities

Handshake and tool execution confirmed over raw JSON-RPC.

| Check | Result |
|---|---|
| `initialize` | protocolVersion 2024-11-05, server 0.1.75, tools + resources advertised |
| `get_server_info` | connector_mode `local`, transport `http`, remnux_version `2026.6.26` |
| `run_tool` | `file /bin/ls && yara --version` → ELF x86-64 PIE, YARA 4.5.0, exit 0, 246 ms |
| `check_tools` | 88 tracked, **78 available**, 10 missing |
| `claude mcp list` | ✔ Connected |

Available and relevant to this project: `ghidra`, `yara`/`yara-forge`, `radare2`, `capa`,
`apkid`, `apktool`, `autoit-ripper`, `cfr` (Java decompiler), `capinfos`, `strings`, `file`,
`upx`, `binwalk`, `volatility`.

Missing (not needed for the current work): `apkid` and others in the 10-item gap — check the
`check_tools` output for the current list.

The server's own `instructions` field carries a prompt-injection warning: treat all tool output
as untrusted data, not instructions. Malware authors embed strings in samples designed to steer
an AI analyst. Keep that active when reading `strings` or `run_tool` output.

---

## 6. Workflow for EM/IoT research

Transfer a sample Windows → REMnux, then analyze via MCP:

```powershell
scp "C:\path\to\sample" remnux:~/files/samples/
```

Then from Claude Code, using the `remnux` MCP tools:

```
analyze_file  {"file": "sample", "depth": "standard"}
extract_iocs  (text output from an analysis)
run_tool      {"command": "capa -vv", "input_file": "sample"}
```

The MCP session is already registered, so the tools appear in the tool list of any new Claude
Code session in any directory. **This session predates the registration** — the `remnux` tools
become available on the next session start. Raw JSON-RPC was used to verify in the meantime.

Results land in the guest's `~/files/output/`. Pull them with:

```powershell
scp remnux:~/files/output/report.json "C:\Users\VJU_LONGBCSE2023\Desktop\EM\second_run\out\"
```

Downloaded artifacts are password-protected archives by default (`infected`).

### 6.1 Transfer + GUI test (verified 2026-09-25)

End-to-end check that the host→guest path and the guest GUI path both work.

**Image generation** — `second_run/make_test_image.py` (Pillow 12.2.0 on Windows, Python 3.12.10).
Produces a 900×600 RGB PNG: title bar, a simulated EM trace waveform, a transfer legend, footer.
Output `second_run/em_test_image.png`, 17,351 bytes.

**Transfer** — `scp` over NAT forward `127.0.0.1:2222` into `~/files/samples/`.

| Side | SHA256 |
|---|---|
| Windows | `ad80878ade6aef0bb2b3323e086658b982f76e6cb854aaad6e66d6ff68428577` |
| Guest | `ad80878ade6aef0bb2b3323e086658b982f76e6cb854aaad6e66d6ff68428577` |

Identical. Guest `file` reports `PNG image data, 900 x 600, 8-bit/color RGB, non-interlaced`.

**Printing to the user's terminal** — no new window was needed. The visible gnome-terminal window is
bash PID 1870 on `/dev/pts/0` (child of `gnome-terminal-server` PID 1721). Writing ANSI escapes
straight to `/dev/pts/0` puts the banner on screen.

**Image display** — ImageMagick `display`, guest PID 4225.

#### GUI-from-SSH findings

Three obstacles, all now known:

1. **No display environment over SSH.** `DISPLAY` is empty in an SSH session. The values must be
   lifted from a live GUI process: `DISPLAY=:0`, `WAYLAND_DISPLAY=wayland-0`,
   `XDG_RUNTIME_DIR=/run/user/1000`, `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus`
   — all readable from `/proc/1721/environ`.
2. **X apps fail without `XAUTHORITY`.** The session is Wayland; Xwayland exists only for X11
   compatibility and its auth cookie lives in `/run/user/1000/.mutter-Xwaylandauth.XXXXXX`.
   Without it: `Authorization required, but no authorization protocol specified`. `zenity`, `feh`,
   and `xdg-open` all died on this.
3. **No Wayland-native image viewer installed.** No `eog`, `eom`, `loupe`, `gpicview`, `sxiv`,
   `ristretto`, or `firefox`. `xdg-mime query default image/png` returns `display-im6.q16.desktop`,
   so the default handler is ImageMagick `display` — X11-only, so it needs the `XAUTHORITY` fix.

Reusable incantation for GUI work on the guest from Windows:

```bash
ssh remnux 'export DISPLAY=:0 \
  XAUTHORITY=$(ls /run/user/1000/.mutter-Xwaylandauth.*) \
  WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000; setsid <app> &'
```

Note the cookie filename carries a random suffix — glob it, do not hardcode it.

---

## 7. Security posture

| Control | State |
|---|---|
| MCP token | 256-bit random, required, verified — server refuses non-loopback bind without it |
| NAT binds | `127.0.0.1` only, host side — not LAN-reachable |
| `--sandbox` | on, `upload_from_host` confined to `/home/remnux/files/samples` |
| DNS rebinding protection | **off** — the server warns about this when binding `0.0.0.0` |
| Blocking guard | null-byte and catastrophic-command (`rm -rf /`, `mkfs`) blocks in `src/security/blocklist.ts` |
| Host-side shell | none — all `docker`/`ssh` calls use argument vectors, no shell interpolation |

The DNS-rebinding warning is expected and acceptable here: the only path to the socket is a
loopback NAT forward on the Windows host, and the token gate sits in front of it. If the server
is ever rebound to a routable address, put a reverse proxy in front and terminate TLS there.

---

## 8. Lessons from run 1 applied here

1. **Check which service owns a port before tunneling** — same trap as run 1's 2222 collision.
   The port forward was missing entirely this time, not colliding. `netstat` first.
2. **A clean snapshot means re-derive, do not assume.** Host keys, forwards, and work dirs were
   all absent. Each had to be regenerated from the setup doc.
3. **VBoxManage from Git Bash needs `MSYS_NO_PATHCONV=1`** — otherwise `/bin/bash` is rewritten to
   `C:/Program Files/Git/usr/bin/bash` and guestcontrol fails with a confusing path error.
4. **`natpf1` is the current subcommand** — `portforward4` was removed in VirtualBox 7.2.
5. **npm global install needs sudo in the guest** — REMnux ships a root-owned older copy of the
   package at `/usr/lib/node_modules`.
6. **Separate "server up" from "reachable"** — same layering discipline as run 1. VM running →
   forwards present → guest listening → token accepted → tool call succeeds. Verify each layer.

---

## 9. ARM64 emulation VM (QEMU system emulation, rebuilt)

`first_run/` §3 left this half-finished — the ARM64 guest never accepted a login. The clean
snapshot removed it entirely, so it was rebuilt from scratch with the run-1 failure modes
designed out.

### 9.1 Design decisions

| Question | Choice | Reason |
|---|---|---|
| Emulation level | `qemu-system-aarch64`, full Ubuntu 24.04 ARM64 | Run 1 showed `qemu-user-static` covers only static binaries. Network, filesystem, process and libc behavior all need a real OS. |
| CPU model | `-cpu max` | Run 1 used `-cpu cortex-a72`, listed as a suspect when the guest never came up. `max` exposes the widest feature set. |
| Console | `-serial file:logs/console.log` | Run 1's `-serial mon:stdio` showed nothing. On `-M virt` the console is virtio, not ttyAMA0, so a file sink is at least persistable — though it also captured 0 bytes, see §9.4. |
| Seed disk wiring | explicit `if=none` + `virtio-blk-pci,serial=cidata` | Run 1 used bare `if=virtio`, which does not guarantee the seed lands as a second block device. Cloud-init NoCloud only runs if the guest finds a `cidata` volume. |
| Password auth | `ssh_pwauth: false`, key only | Removes the plaintext-hash-in-user-data step entirely. No fallback password means no password to leak. |
| Disk | 12 GiB qcow2 overlay, `growpart` + `resize_rootfs` in the seed | The 619 MB base image auto-grows on first boot. Overlay keeps the base pristine and revertible. |
| Network | user-mode NAT, `hostfwd=tcp:127.0.0.1:2222-:22` on the REMnux loopback only | Guest can reach out; nothing inbound except SSH. No extra C2 forward — project isolation. |

### 9.2 Layout in the guest

```
~/arm64-vm/
├── images/
│   ├── ubuntu-24.04-server-cloudimg-arm64.img   619 MB base (pristine)
│   └── ubuntu-arm64-malware-test.qcow2          12 GiB overlay, backing file above
├── seed/
│   ├── user-data                                cloud-config
│   ├── meta-data                                instance-id: arm64-run2-001
│   └── cloud-init-seed.iso                      374,784 bytes
├── logs/
│   ├── console.log                              -serial file: sink
│   └── wait-guest.log                           login poll history
├── start-arm64.sh
├── stop-arm64.sh
└── wait-guest.sh
```

Installed via `apt-get install qemu-system-arm qemu-utils cloud-image-utils qemu-user-static` —
all 8.2.2 from the Ubuntu 24.04 archive. Guest has 70 GB free, 2 vCPU, **no hardware
virtualization** (`grep -c 'vmx|svm' /proc/cpuinfo` → 0), so everything is TCG software
emulation. Expect 10–20x slowdown versus native.

### 9.3 ROOT CAUSE of the run-1 failure

**The Ubuntu 24.04 ARM64 cloud image cannot be booted by the `-M virt` UEFI firmware on its own.**

The image is a *hybrid* image with three relevant partitions:

| Part | Size | FS | Contents |
|---|---|---|---|
| 15 | 104 MB | fat32 | ESP: shim + grub **only**, no kernel |
| 16 | 968 MB | ext4 | `bls_boot`: the real `vmlinuz` + `initrd.img` |
| 1 | 2683 MB | ext4 | root — `/boot` is **empty**, no `/grub/grub.cfg` |

The boot chain is broken in the middle:

1. Firmware loads `/EFI/BOOT/BOOTAA64.EFI` (shim) — succeeds.
2. Shim loads `grubaa64.efi` — succeeds.
3. Grub runs `/EFI/ubuntu/grub.cfg`, which contains exactly:

   ```
   search.fs_uuid cd92325d-9106-478d-983c-8c0115fa5e81 root
   set prefix=($root)'/grub'
   configfile $prefix/grub.cfg
   ```

4. That means: find the volume with UUID `cd92325d…`, then load `<that volume>/grub/grub.cfg`.
   **That file does not exist.** The root volume has no `/grub` directory at all.
5. Grub has nothing to chain-load. It retries the search indefinitely.

The visible symptom is a QEMU process pinned at **99–100% CPU** with the overlay disk growing
to only a few MB and then stalling, and a guest SSH port that accepts TCP but never presents a
banner. That is exactly what run 1 saw, and without console output there was no way to tell a
hung boot from a working one.

**Fix: bypass the firmware chain entirely.** Extract `vmlinuz` and `initrd.img` from partition
16 and pass them to QEMU directly with `-kernel` / `-initrd` / `-append`. This sidesteps the
broken shim→grub chain, gives full control of the kernel command line, and — critically —
makes the boot visible on the PL011 serial console.

Kernel command line used:

```
root=LABEL=cloudimg-rootfs rw console=ttyAMA0,115200 earlycon=pl011,0x9000000 net.ifnames=0
```

`console=ttyAMA0` plus `earlycon=pl011,0x9000000` is what finally produced output. Run 1's
`-serial mon:stdio` was pointed at a virtio console that carries nothing on this machine.

The first attempt at this also used `-smp 2`, which starved the host — see §9.6.

### 9.4 Extracting the kernel

`qemu-nbd` does not work inside the REMnux VM: there is no `/dev/nbd*` and the `nbd` module
cannot be loaded, because REMnux is itself already a guest. The working route is:

1. `sudo qemu-img convert -O raw -S 4k <base>.img /tmp/base-arm64.raw`
2. `sudo losetup -fP --show /tmp/base-arm64.raw` → `/dev/loop6`
3. `sudo mount /dev/loop6p16 /tmp/mnt-bls`
4. copy `vmlinuz-*` and `initrd.img-*` out
5. `sudo umount`, `sudo losetup -d`, delete the raw file

Scripted as `~/arm64-vm/extract-kernel.sh` so the kernel can be re-pulled if the base image is
ever replaced. Note the raw conversion writes a 3.5 GB file — check free space first. Also
note `/dev/loop6` can vanish between commands in one SSH session; the script attaches, mounts,
copies, and detaches in a single run with an `EXIT` trap.

### 9.5 Scripts

`start-arm64.sh` — direct kernel boot. Single-instance pidfile guard, preflight existence check
on all four required files, explicit `if=none` + `virtio-blk-pci` drive pairing, `-display none`,
`-serial file:logs/console.log`, `-no-reboot`. Defaults `-smp 1`; overridable with `GUEST_SMP`.

`stop-arm64.sh` — ACPI powerdown via `SIGTERM`, 20s grace, then `SIGKILL`, then prints the last
console lines.

`wait-guest.sh` — runs inside REMnux, polls guest SSH, logs every attempt to
`logs/wait-guest.log`. Reports `ARM64_GUEST_READY` on reaching kex, `ARM64_TIMEOUT` otherwise.

**The poller reports readiness only — it never reports auth failure, by design.** cloud-init
injects the *Windows* host public key into the ARM64 guest. This script runs *inside REMnux*, so
whatever key it offers is by definition the wrong one, and ssh will always answer
`Permission denied (publickey)` — even when the guest is perfectly healthy and reachable from
Windows over the `-L 2232` tunnel. An earlier version exited 1 on that string and produced a
false `ARM64_AUTH_FAILED` alarm on a guest that was up and working. Reaching kex at all is the
real readiness signal; authentication truth belongs to a Windows-side login carrying the correct
key.

`extract-kernel.sh` — §9.4.

### 9.6 Verified working

| Check | Result |
|---|---|
| Console output | 116 KB of kernel log, `earlycon: pl11` confirmed |
| cloud-init | `CLOUD_INIT_COMPLETE after 2081.58 seconds` |
| Seed key injection | `authorized_keys` table logged, fingerprint `ac:ad:65:a8:…` matches the Windows host key |
| **SSH login from Windows** | `GUEST_LOGIN_OK`, `uname -m` → **aarch64** |
| Kernel | 6.8.0-139-generic |
| cloud-init marker | `/tmp/cloudinit-done` contains `ARM64_CLOUDINIT_DONE` |
| Python | 3.12.3 |
| Sudo | passwordless (`SUDO_OK`) |
| Root disk | auto-grew 619 MB → 11 GB via `growpart` + `resize_rootfs` in the seed |
| Network | NAT IP `10.0.2.15/24`; outbound `HTTP 200`, 254,968 bytes fetched from `archive.ubuntu.com` |
| **Arch enforcement** | x86_64 binary on the aarch64 guest → `Exec format error`, exit 126. Native ARM64 `/bin/ls` → exit 0 |
| MCP server | survived the TCG load; one transient disconnect while the boot saturated both cores |
| Snapshot | internal qcow2 snapshot tag `cloudinit-done` created |

The arch-enforcement test is the important one. It proves this is a genuine aarch64 kernel
rejecting foreign binaries, not transparent emulation silently accepting everything. Any ARM64
malware test result from this VM is architecturally meaningful.

**`PORT_OPEN` does not mean the guest is ready.** QEMU's user-mode hostfwd completes the TCP
handshake itself, before the guest OS is running. Run 1 read that as progress. It is evidence
only that the forward exists. A real SSH banner is the first honest signal.

**TCG starves the host.** With `-smp 2` on a 2-vCPU guest, QEMU consumed both cores and even
`ssh remnux` from Windows began timing out at the banner exchange — REMnux's own sshd got no
CPU. `-smp 1` fixes it. When the host feels unresponsive during emulation, check QEMU CPU
before suspecting the network.

**The MCP client can drop under load.** During the first TCG boot, the remnux HTTP server
became slow enough that the Claude Code MCP client disconnected. The server process itself
stayed alive throughout. Under heavy emulation, expect transient MCP disconnects; they are load
artifacts, not a broken install.

**`scp -P 2232 remnux:…` hits the wrong host.** Port 2232 is the Windows→ARM64 tunnel, not
REMnux. To move a file between REMnux and the ARM64 guest, either stream it
(`ssh remnux "cat /file" | ssh -p 2232 … "cat > /file"`) or use the VirtualBox shared folder.

### 9.7 Access path (working)

```
Windows :2232 --(ssh -L)--> REMnux localhost:2222 --(QEMU hostfwd)--> ARM64 guest :22
```

```powershell
ssh -N -f -L 2232:127.0.0.1:2222 remnux
ssh -p 2232 -i "$env:USERPROFILE\.ssh\id_ed25519" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ubuntu@127.0.0.1
```

Note this is the *same* port pair as run 1. The confusion there is that Windows `2222` is the
VirtualBox forward to REMnux itself, whereas the QEMU forward lives on REMnux's loopback and is
only reachable through the tunnel. `2232` is the Windows-side tunnel port and is free.

`-i` is required on the ARM64 login from Windows. Without it the client offers whatever key the
Windows agent defaults to, which is not the one cloud-init injected. (An attempt to log in from
*inside* REMnux to `127.0.0.1:2222` fails for the mirror-image reason: that uses REMnux's key,
not the host's.)

### 9.8 Cold-start procedure

```powershell
$vb = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $vb startvm "remnux-noble-amd64-virtualbox" --type headless
ssh remnux "~/arm64-vm/start-arm64.sh"                    # boots, returns immediately
ssh -N -f -L 2232:127.0.0.1:2222 remnux                   # tunnel (once per Windows session)
ssh remnux "~/arm64-vm/wait-guest.sh"                     # blocks until READY
ssh -p 2232 -i "$env:USERPROFILE\.ssh\id_ed25519" ubuntu@127.0.0.1
```

Watch progress without blocking: `ssh remnux "tail -f ~/arm64-vm/logs/console.log"`.

#### Fast restart from the snapshot

A cold start re-runs every cloud-init stage and took **2081s (~35 min)** to reach
`CLOUD_INIT_COMPLETE`. Applying the snapshot skips that entirely — the guest resumes from a
post-cloud-init state:

```powershell
ssh remnux "~/arm64-vm/stop-arm64.sh && qemu-img snapshot -a cloudinit-done ~/arm64-vm/images/ubuntu-arm64-malware-test.qcow2 && ~/arm64-vm/start-arm64.sh"
```

Use this before **every** malware run. A compromised guest must not poison the next test, and
`snapshot -a` is the reset that guarantees it. (Note: `stop-arm64.sh` must run first — QEMU
holds a write lock on the image, and `qemu-img` will refuse without it.)

#### Verified after snapshot round-trip

The guest was stopped, snapshotted, and rebooted from the snapshot, then re-verified end to end:

| Check | Result |
|---|---|
| SSH login from Windows | `GUEST_LOGIN_OK`, `uname -m` → `aarch64` |
| Kernel | 6.8.0-139-generic, 20 min uptime |
| `cloud-init status` | `done` |
| Injected key | `SHA256:rK1lqGAj3PaKgJUlUyBnnCMETS6V/1/kxn6T61LOLCM` — matches the Windows host key |
| Sudo | `SUDO_OK` |
| Python | 3.12.3 |
| Network | `10.0.2.15/24`; `HTTP 200`, 254,968 bytes from `archive.ubuntu.com` |
| Disk | `/dev/vda1` 11G, 8.8G free |
| Arch enforcement | x86_64 binary → `Exec format error`, exit **126**; native ARM64 → exit **0** |

`/tmp/cloudinit-done` may be absent on a snapshot-resumed boot. That marker is written by
`runcmd` in the seed and is a diagnostic only — it does not gate login. Use
`cloud-init status` as the real signal.
