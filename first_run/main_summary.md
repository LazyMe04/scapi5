# Main Summary — IoT Malware EM Side-Channel Analysis Lab

**Session:** Plan phase → Initiation phase (ARM64 VM emulation bring-up)
**Date:** 2026-09-24
**Working directory:** `C:\Users\VJU_LONGBCSE2023\Desktop\EM`
**Host OS:** Windows 11 Pro
**Status:** VM running, guest login not yet achieved (see §3.6 Open Diagnosis)
**Language note:** English only in all outputs from this point forward.

---

## 1. Project Context

### 1.1 Research topic
Vietnamese graduate thesis on **Malware detection on IoT devices using Electromagnetic (EM) Side-Channel Analysis (SCA)**. The approach:
1. Collect EM emissions (electromagnetic radiation) from a physical IoT device while it executes software.
2. Known-good ("goodware") code produces a baseline EM signature; malware produces a different, distinguishable signature.
3. Machine learning (ML) / deep learning models classify goodware vs. malware from the EM traces.

### 1.2 Physical measurement concept (why hardware matters)
- EM signals come **only from physical hardware** — CPU switching, power rails, clock activity.
- The Raspberry Pi 5 (ARM64 / aarch64, Cortex-A76) is the measurement target.
- An EM probe sits near the CPU; the signal goes through an amplifier into an oscilloscope.
- A GPIO trigger (from `goodware_runner.py`) synchronizes oscilloscope capture with code execution.
- **Important consequence:** QEMU/emulation on a PC cannot produce EM signals. VMs are for analysis/preparation only; real EM traces require the physical Pi 5.

### 1.3 Source files (original EM folder)
| File | Size | Role |
|---|---|---|
| `goodware_runner.py` | 11 KB | Benign workload runner for Raspberry Pi 5/4. Hardware GPIO trigger (GPIO 17 or ACT LED) synchronized with oscilloscope capture. 5 workload profiles: `idle`, `crypto` (SHA-256/PBKDF2), `compress` (zlib), `math` (numpy/linalg), `network` (UDP loopback). `--dry-run` flag for PC testing without GPIO. |
| `SENTAN_Malware-IoT-SCA.pdf` | 943 KB | Reference research paper (Japanese SENTAN project) on malware + IoT side-channel analysis. |
| `task_ky_thuat.docx` | 27 KB | Technical task document. |
| `Nội dung 1.docx` | 3.5 MB | Thesis content part 1 (Vietnamese) — IoT malware overview, SEMA/DEMA attack theory, detection methods. |
| `Nội dung 2.docx` | 46 KB | Thesis content part 2 (Vietnamese). |
| `Content 2.docx` | 40 KB | Thesis content (Vietnamese). |
| `remnux-ssh-setup.md` | 5.9 KB | Working document describing SSH access to the REMnux VM (Windows host → VirtualBox NAT forward → REMnux guest sshd). |

### 1.4 Project goals
1. Statically analyze IoT malware in a safe, isolated environment.
2. Test malware on ARM64 emulation matching the Raspberry Pi 5 architecture before touching hardware.
3. Collect EM traces on the real Raspberry Pi 5 with an oscilloscope.
4. Build a labeled dataset (goodware vs. malware EM signatures) and train an ML classifier.

---

## 2. Plan Phase — Evolution of the Approach

### 2.1 Original plan (initial AI assistant proposal)
The first plan proposed downloading a full virtualization stack:
- VirtualBox (Windows host hypervisor)
- Debian AMD64 ISO (~600 MB) as a QEMU host
- Debian Wheezy ARM images (2013, from `people.debian.org/~aurel32`) — `debian_wheezy_armhf_standard.qcow2` + kernel `vmlinuz-3.2.0-4-vexpress` + `initrd.img-3.2.0-4-vexpress`
- MIPS images for router malware (`debian_wheezy_mips_standard.qcow2` + `vmlinuz-3.2.0-4-5kc-malta` + `initrd.img-3.2.0-4-5kc-malta`)
- Kali Linux (~4 GB, optional)

**Structure:** `Windows → VirtualBox → Debian x86 → QEMU → Debian ARM` — 4 virtualization layers, nested QEMU inside a VM.

**Rationale behind the original plan (asked by user later):**
- Windows cannot natively run ARM/MIPS binaries, so emulation was needed.
- QEMU runs best on Linux, so a Debian VM was proposed as host.
- The `aurel32` images were historically the most common way to test ARM IoT malware (popular in the 2016–2018 research period), because malware IoT binaries target ARM/MIPS ELF format.
- Kali was proposed as an optional additional pen-testing toolkit, not really needed.

### 2.2 Gemini critique (user ran `/copy`, asked "is this correct?")
User pasted a critique from Gemini. Three core points:
1. **Debian Wheezy is obsolete and wrong architecture** — released 2013 (13 years old, kernel 3.2, glibc too old to run modern malware/tools). It is ARM32 (`armhf`), while the Raspberry Pi 5 is ARM64 (`aarch64`, ARMv8.2-A). Malware compiled for ARM64 will never run on it.
2. **Over-engineering** — nested virtualization (VM inside VM) wastes 6–10 GB disk, is slow, and takes hours to set up pointlessly.
3. **EM side-channel cannot come from emulation** — EM emissions only come from physical hardware. A PC QEMU emulation can never be measured for EM. The VM is only needed for two things: (a) static analysis (strings, unpack, Ghidra) and (b) preliminary smoke testing (`qemu-user-static`).

**My evaluation:** Gemini ~80% correct. Valid points: outdated images, wrong architecture, nested-VM overhead, EM needs real hardware. One nuance Gemini underweighted: `qemu-user-static` is not always sufficient — malware needing network behavior, full syscalls, or full system libraries needs **system-mode emulation** (full OS). This is exactly what the user later requested.

### 2.3 Optimized plan (accepted)
| Component | Decision | Reason |
|---|---|---|
| REMnux OVA (~4 GB) | **KEEP** | Pre-packaged malware analysis distro (Ghidra, Cutter, UPX, YARA, Wireshark, Volatility, binfmt). Ubuntu-based. Only big download needed. |
| Debian AMD64 ISO | **DROP** | REMnux (Ubuntu) can host QEMU directly — no second OS needed. |
| Debian Wheezy ARM/MIPS images | **DROP** | Obsolete, wrong architecture for Pi 5. |
| Kali Linux | **DROP** | Redundant for malware analysis. |
| **QEMU ARM64 system emulation** | **ADD BACK** (user request) | User explicitly wanted ARM emulation to test malware scripts before running on real Pi 5. Full-system ARM64 VM (not just user-mode) covers network + syscall behavior. |

**Final architecture:**
```
Windows Host
└── VirtualBox
    └── REMnux VM (Ubuntu 24.04 LTS, REMnux v2026.6.26, Guest Additions 7.1.2)
        ├── qemu-user-static (quick binary smoke test)
        ├── qemu-system-aarch64 (full ARM64 system VM)
        │   └── Ubuntu 24.04 ARM64 cloud image (malware test environment)
        └── static tools: Ghidra, UPX, YARA, strings, readelf, binwalk
Real hardware: Raspberry Pi 5 (ARM64) + EM probe + amplifier + oscilloscope → EM traces → dataset → ML model
```

**Total download:** ~4.8 GB (REMnux ~4 GB + Ubuntu ARM64 cloud image ~800 MB), versus ~6.2 GB in the original plan and 4+ virtualization layers instead of 2.

### 2.4 Reports and documents produced
- `first_run/IoT_Malware_EM_Lab_Setup_Plan.docx` — the full lab plan report, generated as a Word document via python-docx. 12 sections: Executive Summary, Project Objectives, System Architecture, Resource Requirements, Phase 1 (VirtualBox + Host-Only network), Phase 2 (REMnux + QEMU install + shared folders), Phase 3 (ARM64 emulation), Phase 4 (malware analysis workflow), EM trace collection pipeline, workflow diagram, plan comparison, next steps.
- A copy of the same report also lives at `Mal/draft/IoT_Malware_EM_Lab_Setup_Plan.docx` (pre-existing project location).
- `first_run/generate_lab_report.py` — the python-docx generator script (25 KB) that produced the report.
- `first_run/main_summary.md` — this file.

### 2.5 Plan comparison summary
| Aspect | Original plan | Gemini critique | Accepted plan |
|---|---|---|---|
| Download size | ~6.2 GB | ~4 GB | ~4.8 GB |
| Virtualization layers | 4 (nested) | 1 (REMnux only) | 2 (VirtualBox + REMnux, QEMU directly inside) |
| ARM architecture | ARM32 (Wheezy 2013) | N/A | ARM64 (Ubuntu 24.04) |
| Pi 5 compatible | No | N/A | Yes |
| Pre-hardware testing | Full ARM VM (wrong arch) | User-mode only | Full ARM64 VM + user-mode |

---

## 3. Initiation Phase — ARM64 VM Bring-up (executed work)

### 3.1 Environment discovered on REMnux guest
Prior partial work existed (timestamps Sep 22–23, before this session's remote work):
- `~/arm64-vm/images/ubuntu-24.04-server-cloudimg-arm64.img` — **619 MB** (619,621,888 bytes), already downloaded.
- `~/arm64-vm/images/ubuntu-arm64-malware-test.qcow2` — 10 GiB snapshot disk, backing file = the Ubuntu image, `corrupt: false`, 196 KB initial size.
- `~/arm64-vm/start-arm64.sh` — existed, and a stale vim swap file `.start-arm64.sh.swp` indicated an interrupted edit session.
- `qemu-img` 8.2.2, `qemu-system-aarch64` 8.2.2, `qemu-aarch64-static` 8.2.2 all installed.
- SSH to REMnux working via the documented `remnux-ssh-setup.md` path (Windows `ssh remnux` → `127.0.0.1:2222` → VirtualBox NAT port-forward → REMnux guest port 22).

**Environment facts from `remnux-ssh-setup.md`:**
| Item | Value |
|---|---|
| Host | Windows 11 Pro, built-in OpenSSH |
| VM name | `remnux-noble-amd64-virtualbox` |
| Guest | Ubuntu 24.04.3 LTS, REMnux v2026.6.26, Guest Additions 7.1.2 |
| NIC1 | NAT, guest IP 10.0.2.15 |
| NIC2 | Host-only (`VirtualBox Host-Only Ethernet Adapter`) |
| Port forward | `ssh,tcp,127.0.0.1,2222,,22` (shipped with appliance) |
| Guest credentials | remnux / malware |
| VBoxManage | `C:\Program Files\Oracle\VirtualBox\VBoxManage.exe` |

### 3.2 Task assigned by user
"Do the 3.2 step" — in the accepted plan, Phase 3 (ARM64 emulation) step 2 = create/verify the ARM64 VM startup script setup (`~/arm64-vm/start-arm64.sh` + supporting pieces). Complete it by SSH-ing into REMnux per `remnux-ssh-setup.md`.

### 3.3 Work executed — ordered log

**Step 1: SSH connectivity test (Windows → REMnux).**
```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 remnux "echo CONNECTED; uname -m; whoami; qemu-img --version | head -1"
```
Result: `CONNECTED`, `x86_64`, `remnux`, `qemu-img version 8.2.2`.

**Step 2: Inventory existing ARM64 VM state.**
```bash
ssh remnux "ls -la ~/arm64-vm/; ls -la ~/arm64-vm/images/; qemu-system-aarch64 --version | head -1; qemu-aarch64-static --version | head -1"
```
Found: image 619 MB, snapshot qcow2, script, `.swp` swap file, `disks/` dir, `images/` dir.

**Step 3: Inspect existing script + disk validity.**
```bash
ssh remnux "cat ~/arm64-vm/start-arm64.sh; qemu-img info ~/arm64-vm/images/ubuntu-arm64-malware-test.qcow2"
```
Script matched the plan (virt machine, cortex-a72, 2 smp, 2G, hostfwd 2222→22, nographic). Disk valid, backing file correct. **Key gap identified:** no cloud-init seed ISO → Ubuntu cloud image has no default password and no injected SSH key → **impossible to log in.**

**Step 4: Install cloud-init seed tooling + check keys on guest.**
```bash
ssh remnux "sudo apt-get install -y cloud-image-utils >/dev/null 2>&1; which cloud-localds; ls ~/.ssh/"
```
`cloud-localds` installed. Guest `~/.ssh/` contained only `authorized_keys` (host's pubkey was already installed there for REMnux login itself).

**Step 5: Read Windows host SSH public key.**
```bash
cat "$USERPROFILE/.ssh/id_ed25519.pub"
```
`ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICNrYASYRGfr4tH4mF0tMMzfuMyrzniA/EUVjkGpv1DP vju_longbcse2023@MAY2`

**Step 6: Create first cloud-init seed ISO.**
```bash
ssh remnux 'mkdir -p ~/arm64-vm/seed && cd ~/arm64-vm/seed && cat > user-data <<EOF
#cloud-config
hostname: arm64-malware-test
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    ssh_authorized_keys:
      - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICNrYASYRGfr4tH4mF0tMMzfuMyrzniA/EUVjkGpv1DP vju_longbcse2023@MAY2
ssh_pwauth: true
disable_root: false
EOF
printf "instance-id: arm64-malware-test\nlocal-hostname: arm64-malware-test\n" > meta-data
cloud-localds cloud-init-seed.iso user-data meta-data'
```
Result: `cloud-init-seed.iso` 374,784 bytes created. Note: this first seed had **no password field** — only SSH key injection (deliberate; key auth should suffice).

**Step 7: Update `start-arm64.sh` to attach seed drive.**
First attempt used an unquoted heredoc which collapsed the backslash line-continuations into one line (valid but ugly single-line command). Rewritten with a properly quoted heredoc `<<'EOF'` — verified with `cat -A` that `\` continuations are intact.

Final script:
```bash
#!/bin/bash
# start-arm64.sh - Boot Ubuntu ARM64 for malware testing

IMG_DIR="$HOME/arm64-vm/images"
DISK="${IMG_DIR}/ubuntu-arm64-malware-test.qcow2"
SEED="$HOME/arm64-vm/seed/cloud-init-seed.iso"

echo "Starting ARM64 VM for malware testing..."
echo "SSH will be available on port 2222 (user: ubuntu)"
echo "Stop with Ctrl-A X"

qemu-system-aarch64 \
  -M virt \
  -cpu cortex-a72 \
  -smp 2 \
  -m 2G \
  -drive file=${DISK},if=virtio,format=qcow2 \
  -drive file=${SEED},if=virtio,format=raw \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic \
  -serial mon:stdio

echo "VM stopped"
```
Also removed the stale `.start-arm64.sh.swp`.

**Step 8: First boot.**
```bash
ssh remnux "cd ~/arm64-vm && nohup ./start-arm64.sh > ~/arm64-vm/qemu.log 2>&1 & echo LAUNCHED; sleep 5; pgrep -af qemu-system-aarch64"
```
QEMU running PID 3218. Log contained only the 3 echo lines — **no guest console output** (later identified as virtio-console behavior, see issues).

**Step 9: SSH attempts to the ARM64 guest fail with `Permission denied (publickey,password)`.**
Multiple attempts as `ubuntu@127.0.0.1:2222` from Windows kept failing. Serial log empty. QEMU uptake showed 607 s uptime, 0.0% CPU.

**Step 10: Root-cause discovery — port 2222 collision.**
Windows `netstat` showed port 2222 owned by **VirtualBoxVM** (PID 15888), not a QEMU tunnel:
```
TCP  127.0.0.1:2222  0.0.0.0:0  LISTENING  15888
```
**Critical finding:** port 2222 on Windows = the **VirtualBox NAT port-forward to REMnux's own sshd** (from the appliance's shipped rule). Every `ubuntu@127.0.0.1:2222` attempt had been hitting **REMnux's sshd**, which has no `ubuntu` user → reject. The QEMU hostfwd `tcp::2222-:22` binds **inside the REMnux guest** at `127.0.0.1:2222`, reachable only from within REMnux, not from Windows directly.

Also noted: an earlier attempted tunnel `ssh -N -f -L 2222:127.0.0.1:2222 remnux` failed with `bind [127.0.0.1]:2222: Address already in use` — same collision.

**Step 11: Correct connectivity path.**
New tunnel on a free Windows port mapping to REMnux's internal 2222 (QEMU hostfwd):
```bash
ssh -o BatchMode=yes -N -f -L 2232:127.0.0.1:2222 remnux && echo TUNNEL_2232_UP
```
Then log into the ARM64 guest via:
```bash
ssh -p 2232 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes ubuntu@127.0.0.1
```
Result on first try: `Connection timed out during banner exchange` — tunnel up, QEMU hostfwd responding, but **guest sshd not yet listening** (guest still booting / cloud-init still running).

**Step 12: Seed rebuild with password fallback + fresh instance-id.**
Since key-only seed gave no login and we could not see the guest console, rebuilt the seed to be robust:
- Fresh `instance-id: arm64-malware-test-2` in meta-data → **forces cloud-init to treat the boot as a brand-new instance and re-run user-data** (cloud-init caches per instance-id in `/var/lib/cloud/instance`).
- Added an SHA-512 password hash for user `ubuntu` (created on the guest with `openssl passwd -6 "test123"`).
- Added `chpasswd: expire: false` (password does not need changing at first login).
- Added `runcmd: - touch /tmp/cloudinit-done` (diagnostic marker).

Final user-data:
```yaml
#cloud-config
hostname: arm64-malware-test
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    passwd: $6$TinzTKJtuM2s5pQj$5QDyp/...   (truncated here; real hash present on guest)
    ssh_authorized_keys:
      - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICNrYASYRGfr4tH4mF0tMMzfuMyrzniA/EUVjkGpv1DP vju_longbcse2023@MAY2
chpasswd:
  expire: false
ssh_pwauth: true
disable_root: false
runcmd:
  - touch /tmp/cloudinit-done
```
`cloud-localds` rebuilt -> `cloud-init-seed.iso` (374,784 bytes). Verified `user-data` and `meta-data` via `cat`.

**Step 13: Kill old VM, re-boot with new seed.**
- Killed QEMU (pkill; process confirmed stopped).
- Relaunched via `nohup ./start-arm64.sh > qemu.log 2>&1 &`.
- QEMU running PID 4613 (verified via guestcontrol `pgrep`).
- Old tunnel re-created; poll loop for guest login ran in background.

**Step 14: Poll results.**
20 attempts, all `Connection to 127.0.0.1 port 2232 timed out` — guest sshd still not answering after ~10 minutes of guest uptime. QEMU process alive (PID 4613) at 607 s, CPU 0.0% at sampling time. Poll task ended (exit -1, interrupted).

### 3.4 Issues hit and fixes (complete table)
| Issue | Root cause | Fix |
|---|---|---|
| `Permission denied (publickey,password)` on `ssh ubuntu@127.0.0.1:2222` | Port 2222 on Windows = VirtualBox NAT forward to REMnux's own sshd (appliance rule `ssh,tcp,127.0.0.1,2222,,22`). Attempts hit REMnux sshd, never ARM64 guest. | New tunnel on port 2232: `ssh -N -f -L 2232:127.0.0.1:2222 remnux` → REMnux localhost:2222 (QEMU hostfwd) → ARM64 guest:22. |
| Guest console output empty in `qemu.log` | Ubuntu cloud image on `virt` machine uses virtio-console, not serial ttyAMA0; `-serial mon:stdio` has nothing to display. | Not blocking (SSH is the intended path; console not needed). For later debugging: attach serial file capture or `-append "console=ttyAMA0,115200"`. |
| First seed had no password — no fallback if key injection fails | Only `ssh_authorized_keys` specified; `lock_passwd: false` without `passwd` leaves account with empty (non-functional) password. | Rebuilt seed with SHA-512 hash of `test123` (`$6$...`), plus `chpasswd: expire: false`. |
| cloud-init would not re-read updated user-data | cloud-init caches instance-id; same instance-id on reboot → skips user-data. | Changed `instance-id` to `arm64-malware-test-2` → full re-run on next boot. |
| PowerShell interpolates `$()` / `\$` inside `guestcontrol -- -c "..."` | PS double-quoted strings expand `$(...)`; `\$` passes literal `\$` to bash (no command substitution). | Use PS **single-quoted** strings around the whole `-c '...'` bash command. |
| `openssl` not recognized (not a cmdlet) | Command was executed by Windows PowerShell, not the guest bash. | Generate password hash only inside guest bash. |
| Inline `sed 's/.../</hash-present>/'` produced garbage | Unquoted `>` in the replacement string is a bash redirection, writing to a file. | Avoid `>`/`<` in inline bash strings; inspect files with plain `cat`. |
| Heredoc first attempt collapsed `\`-continuations | Unquoted heredoc `<<EOF` lets bash process backslash-newlines during the `cat`. | Use quoted heredoc `<<'EOF'`. |
| `guestcontrol` session sometimes returns no output | VBoxManage guest session close can time out (`VERR_TIMEOUT`) after the command ends; transient. | Re-run with a single simple command; treat trailing `VBoxManage.exe: error: Closing guest session ... VERR_TIMEOUT` as non-fatal. |
| Background tasks occasionally exit with `-1` / timeout 143 | Long-running polls exceed tool timeouts or were stopped by user. | Break into smaller waits; use background BASH tasks and monitor output files. |

### 3.5 Network paths — definitive reference
```
Windows host 127.0.0.1:2222  ──(VirtualBox NAT forward)──▶  REMnux guest :22        (ssh remnux)
Windows host 127.0.0.1:2232  ──(ssh -L tunnel through remnux)──▶ REMnux localhost:2222
                                                                    │
                                                                    ▼ QEMU hostfwd tcp::2222-:22
                                                              ARM64 guest :22 (ubuntu)
```

### 3.6 Current state (at last check)
- `first_run/` folder created; docs reorganized (see §5).
- QEMU ARM64 VM running on REMnux guest (PID 4613).
- Tunnel Windows:2232 → ARM64 guest:22 established.
- **Guest sshd NOT yet answering** — banner exchange timeouts persist.
- **Open diagnosis branches:**
  1. **Guest still booting** — TCG (software) emulation is roughly 10–20x slower than native; first boot + cloud-init can take many minutes. Wait longer, retry.
  2. **Guest booted and idle** (CPU 0.0% supports this) but sshd down — verify from inside REMnux: `timeout 3 bash -c 'echo >/dev/tcp/127.0.0.1/2222' && echo OPEN || echo CLOSED`; also `ss -tln | grep 22`.
  3. **Kernel or cloud-init stuck** — need console visibility: rerun QEMU with `-serial file:/tmp/arm64-console.log` (captures boot output), or add kernel args `-append "console=ttyAMA0,115200"`, or inspect the guest disk offline (qemu-nbd / libguestfs).
  4. **Machine/CPU parameter mismatch** — if `-cpu cortex-a72` proves problematic, try `-cpu max` or add `-machine virt,highmem=off`.

---

## 4. Key Commands Reference

### Windows host → REMnux (baseline)
```powershell
ssh remnux                          # per remnux-ssh-setup.md (VirtualBox NAT forward 2222)
ssh -N -f -L 2232:127.0.0.1:2222 remnux   # tunnel: Windows 2232 -> REMnux localhost:2222 -> QEMU hostfwd -> ARM64 guest:22
ssh -p 2232 -i "$USERPROFILE/.ssh/id_ed25519" ubuntu@127.0.0.1    # login ARM64 guest
```

### Inspect/control REMnux without depending on its sshd
```powershell
$vb = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $vb guestcontrol "remnux-noble-amd64-virtualbox" --username remnux --password malware run --exe /bin/bash --wait-stdout --wait-stderr -- -c 'COMMAND'
```
Important: use single quotes around the whole bash command so PowerShell does not evaluate `$()` / `$var`.

### Inside the REMnux guest (typical operations)
```bash
cd ~/arm64-vm && nohup ./start-arm64.sh > qemu.log 2>&1 &   # boot VM detached
pgrep -af qemu-system-aarch64                                # is QEMU alive
ps -o etimes=,pcpu= -p $(pgrep -f qemu-system-aarch64 | head -1)   # uptime + CPU
cloud-localds ~/arm64-vm/seed/cloud-init-seed.iso user-data meta-data  # rebuild seed
qemu-img info ~/arm64-vm/images/ubuntu-arm64-malware-test.qcow2      # disk health
timeout 3 bash -c 'echo >/dev/tcp/127.0.0.1/2222' && echo OPEN || echo CLOSED  # port probe
```

### ARM64 guest access hygiene
- First SSH to a fresh host key: add `-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null`.
- Credentials: user `ubuntu`, SSH key = Windows `id_ed25519` (injected), fallback password `test123`.

---

## 5. Folder Organization (post-cleanup on Windows host)

```
EM/
├── first_run/                                  ← conversation artifacts (this folder)
│   ├── main_summary.md                         ← this file
│   ├── IoT_Malware_EM_Lab_Setup_Plan.docx      ← full lab plan report (generated)
│   ├── generate_lab_report.py                  ← python-docx generator for the report
│   ├── Content 2.docx                          ← thesis content (moved here)
│   ├── Nội dung 1.docx                         ← thesis content (moved here)
│   ├── Nội dung 2.docx                         ← thesis content (moved here)
│   ├── SENTAN_Malware-IoT-SCA.pdf              ← reference paper (moved here)
│   ├── task_ky_thuat.docx                      ← task doc (moved here)
│   └── remnux-ssh-setup.md                     ← SSH setup doc (moved here)
├── goodware_runner.py                          ← live project script (kept in root)
└── Mal/                                        ← pre-existing structure (kept)
    ├── draft/
    │   └── IoT_Malware_EM_Lab_Setup_Plan.docx  ← plan doc copy (kept)
    └── main/                                   ← empty
```

**Deleted from EM root** (docx-extraction leftovers): `temp_content2/`, `temp_content2.zip`, `temp_noidung1/`, `temp_noidung1.zip`, `temp_noidung2/`, `temp_noidung2.zip`.

---

## 6. Next Steps (recommended order)

1. **Diagnose ARM64 guest boot** — get to a login:
   - From inside REMnux: probe `127.0.0.1:2222` (`OPEN`/`CLOSED`) and check `ss -tln | grep 22`; this distinguishes "QEMU forward dead" from "guest sshd down".
   - If guest sshd down: relaunch QEMU with serial capture (`-serial file:/tmp/arm64-console.log`) to observe boot; or add `-append "console=ttyAMA0,115200"`; or inspect the qcow2 offline.
   - If machine/CPU param suspected: try `-cpu max`, or `-machine virt,highmem=off`.
2. **Verify login** → `ssh -p 2232 ubuntu@127.0.0.1` (key `id_ed25519`) or password `test123`. Confirm with `uname -m` = `aarch64`.
3. **Snapshot a working state** — once login works, consider `qemu-img snapshot` of the qcow2 so the malware test base is reproducible.
4. **Proceed with the plan:**
   - Level 1 static analysis in REMnux (file, strings, readelf, upx -d, Ghidra, YARA).
   - Level 2 smoke test: `qemu-aarch64-static ./malware_binary`.
   - Level 3 full-system behavior test inside the ARM64 VM (network capture via tcpdump, process/fs monitoring).
   - Stage malware samples via the VirtualBox shared folder (`C:\VMShares\MalwareSamples` → `/media/sf_malware_samples/`).
   - Level 4 real hardware: transfer validated samples to Raspberry Pi 5, run with GPIO-triggered oscilloscope capture (extend `goodware_runner.py` or a malware runner analog), collect EM traces, build dataset, train classifier.
5. **REMnux sshd persistence note** — REMnux sshd is disabled at boot by design (malware-box hardening). If frequent reboots expected, `sudo systemctl enable ssh`; otherwise re-run `sudo systemctl start ssh` per boot.

---

## 7. Session chronology (condensed)

| Order | Event |
|---|---|
| 1 | User introduced EM project folder; asked to read files, plan malware scripts + dataset + VirtualBox lab. |
| 2 | Files read (goodware_runner.py, docx extracted via zip rename, research PDF). Project understood: EM SCA on IoT malware; Pi 5 target. |
| 3 | Initial lab plan given (4-layer nested VM, Debian Wheezy ARM). |
| 4 | User requested detail on step 3 (downloads); download guide provided. |
| 5 | User pasted Gemini critique; asked if correct. Evaluated: ~80% correct; plan revised. |
| 6 | User asked why old plan had those steps; rationale explained. |
| 7 | User requested optimized plan; produced final architecture with QEMU ARM64 system emulation added back. |
| 8 | User asked to export latest plan to a Word document; `IoT_Malware_EM_Lab_Setup_Plan.docx` generated via `generate_lab_report.py` (python-docx). |
| 9 | User: use `remnux-ssh-setup.md` to SSH into REMnux and do step 3.2. Remote work began (this session's main execution). |
| 10 | Inventory, seed creation, script update, first boot, port-2222 misroute discovered, tunnel 2232, seed rebuild with password + fresh instance-id, reboot, poll (login pending). |
| 11 | User asked to create `first_run` folder, move related docs, delete leftovers, write `main_summary.md`. |
| 12 | User asked for more detail in `main_summary.md` and English-only output. (This revision.) |

---

## 8. Lessons learned

1. **Check which service owns a port before tunneling.** The 2222 collision cost several retries; the port was a shipped VirtualBox NAT forward, not free.
2. **Ubuntu cloud images are headless by default.** No console login, no password — you must inject credentials via cloud-init seed (NoCloud on `/dev/vdb`) or you cannot get in.
3. **cloud-init is idempotent per instance-id.** To re-apply user-data, change `instance-id` (or wipe `/var/lib/cloud/instance`).
4. **PowerShell + embedded bash = quoting minefield.** Single-quote the whole bash string passed through `guestcontrol`; generate secrets inside the guest, not on Windows.
5. **TCG emulation is slow.** ARM64 guest boots take minutes; budget 5–15 min for cloud-init first boot before declaring the VM broken.
6. **Separate "VM up" from "service up".** QEMU process running ≠ guest sshd listening ≠ login works. Verify each layer independently.