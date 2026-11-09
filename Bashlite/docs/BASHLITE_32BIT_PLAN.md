# Bashlite 32-bit on the Pi 5 — end-to-end plan

**Scope of this document:** one malware family, one architecture, one device.
Bashlite (a.k.a. Qbot / Gafgyt / Lizkebash) as a **32-bit ARM static ELF**, executed
natively on the Raspberry Pi 5, driven by a **lab C2 on the bench link**. No
rebuilt binary, no 64-bit port, no change to the goodware side.
**Out of scope:** EM capture (no oscilloscope yet), Mirai, Gonnacry re-runs.

Why 32-bit and not 64-bit is settled in section 1; do not reopen it without new
evidence.

---

## 0. Why this plan exists

A Bashlite sample with no reachable C2 spends its window retrying a dead address and
sleeping. The resulting trace is indistinguishable from an idle process, and an idle
trace teaches a classifier nothing. The paper (ACSAC '21, section 6.1.2) solved this
with a spoofed command server that hands the bot real commands. This plan builds that
server and the isolation around it, so the trace reflects the bot's actual code paths.

---

## 1. Architecture decision — 32-bit stays

| Statement | Status |
|---|---|
| The Pi 5 userland is aarch64 (Debian 13, kernel 6.18) | verified, `BENCH_OPERATIONS.md` §2 |
| The Pi 5 executes 32-bit ARM ELFs **natively** via `CONFIG_COMPAT` | verified twice, exit code 42 test, `pi5_setup` |
| A 64-bit OS does not mean a 32-bit binary is emulated | it is AArch32 mode on the same silicon, no QEMU |
| "Moving to 64-bit" would mean rebuilding the sample | then it is no longer in-the-wild malware |

Rebuilding would replace the author's toolchain, optimisation level, and hardcoded
constants with yours. The EM signature would then describe your build, not the threat.
If a 64-bit dataset is ever required, the correct move is to select **naturally
aarch64** samples, never to recompile this one.

---

## 2. Sample acquisition

The lab does not download malware automatically. Obtain the file through the route
approved for this project (supervisor corpus, MalwareBazaar, theZoo, or the paper
authors), on the isolated analysis machine.

### Candidate sources

| Source | Notes |
|---|---|
| Supervisor / institutional corpus | best provenance and legal clarity; ask first |
| MalwareBazaar (`bazaar.abuse.ch`) | free account, search `bashlite` / `gafgyt`, filter ELF; provides SHA-256 and first-seen |
| theZoo (`github.com/ytisf/theZoo`) | public repo, documented layout, password `infected` |
| VirusTotal (academic licence) | also the source of AV labels for family attribution |
| Paper authors (ACSAC '21) | reasonable request for the published corpus |

### Acceptance criteria

```bash
file bashlite.bin
# ELF 32-bit LSB executable, ARM, EABI5 version 1 (SYSV), statically linked, stripped
sha256sum bashlite.bin
```

- [ ] machine is **ARM**, 32-bit, EABI5 — not MIPS, x86, or aarch64
- [ ] **statically linked** (a dynamic 32-bit binary fails with `No such file or directory`
      because `ld-linux-armhf.so.3` is missing)
- [ ] family label is bashlite / gafgyt / qbot (AVClass or VirusTotal)
- [ ] source URL, download date, SHA-256, first-seen, packer status recorded
- [ ] stored inside REMnux or the isolated analyser, never on Windows

Prefer an **unpacked** sample for the first dataset. A UPX stub executes first and
contributes its own signature; packed variants are a separate study.

---

## 3. Files in this repo and what each one does

| File | Role |
|---|---|
| `Bashlite/runner/bashlite_runner.py` | time-bounded executor with trigger, containment gate, privilege drop, leftover sweep, manifest |
| `Bashlite/isolation-on.sh` | default-deny egress, single C2 exception, per-port DROP counters, optional redirect |
| `isolation-off.sh` | rollback to permissive networking |
| `Bashlite/c2/c2_server.py` | spoofed C2: observe mode, scripted serve mode, flood sinks, JSONL evidence log |
| `Bashlite/c2/c2_script.json` | editable command timeline; offsets from `accept()` |
| `Bashlite/docs/BASHLITE_VM_TEST.md` | rehearsal runbook for the ARM64 guest |
| `Bashlite/docs/BASHLITE_PI_DIRECT.md` | runbook for running straight on the Pi 5 — no REMnux, no VM rehearsal |

---

## Phase 0 — Restore point and environment fingerprint

The Pi has no snapshots. This phase is what makes a bad run recoverable.

```bash
# on the laptop, with the SD card mounted (or over SSH for a file-level backup)
sudo dd if=/dev/sdX of=pi5-clean-$(date +%F).img bs=4M status=progress
```

Minimum alternative if imaging is not possible:

```bash
rsync -a pi5:/home/victim/ ./backup/victim-$(date +%F)/
```

Record the fingerprint (goes into the thesis appendix and the manifest):

```bash
uname -a; cat /etc/os-release
vcgencmd get_throttled                  # must be 0x0
grep -E 'arm_freq|overclock|force_turbo' /boot/firmware/config.txt   # must be empty
dpkg -l > pkg.txt
systemctl list-units --type=service --state=running > svc.txt
id victim
```

**Done when:** an image or backup exists and can be listed, throttle is `0x0`, and
no clock tuning is configured.

---

## Phase 1 — Bench link and isolation

### 1.1 Physical and radio

```bash
sudo nmcli con up bench-static        # Pi 192.168.7.2/24, laptop 192.168.7.1/24
ip -4 addr show eth0
ip route                              # no default route to the internet
sudo rfkill block wifi
sudo rfkill block bluetooth
ip link show wlan0                    # DOWN
```

### 1.2 Kernel enforcement

```bash
sudo bash Bashlite/isolation-on.sh --admin 192.168.7.1 --c2 192.168.7.1 --c2-port 999 \
                               --owner-user victim --dry-run   # inspect first
sudo bash Bashlite/isolation-on.sh --admin 192.168.7.1 --c2 192.168.7.1 --c2-port 999 \
                               --owner-user victim
```

The script sets INPUT/FORWARD/OUTPUT policies to DROP, allows loopback, replies, and
SSH from the admin host, allows exactly one destination (the C2 host), installs
per-port DROP rules so counter evidence exists, disables IPv6, and verifies that
`curl` and `nc` to public addresses fail. It aborts and restores permissive defaults
if any step fails.

`--owner-user victim` scopes the NAT redirect to the sample's account, so the
operator's own SSH and package tooling are not redirected.

### 1.3 Verification before any sample exists on the device

```bash
curl -m 5 -s http://1.1.1.1 >/dev/null; echo "curl=$?"   # non-zero
nc -z -w 3 1.1.1.1 80;                echo "nc=$?"       # non-zero
nc -z -w 3 192.168.7.1 999;           echo "c2=$?"       # reaches the C2 only when it runs
sudo iptables -L OUTPUT -n -v                           # policy DROP, counters present
```

**Done when:** the two public checks fail, the C2 check reaches the server, and the
runner's own gate classifies the ruleset as `full`.

---

## Phase 2 — Static triage (REMnux, nothing executes)

REMnux is the default host for this phase, not a requirement; the phase only needs
a Linux host that is not the operator's daily machine. `Bashlite/docs/BASHLITE_PI_DIRECT.md`
does the same checks on the Pi itself, where the sample has to end up anyway.

```bash
sha256sum bashlite.bin
file bashlite.bin
readelf -h bashlite.bin
strings -a -n 6 bashlite.bin | sort -u > strings.txt
```

Look for: the C2 address (4-byte form or domain), the port, and the command
vocabulary. **Do not assume the IRC-style vocabulary** (`NICK`, `USER`, `PING`,
`PONG`, `PRIVMSG`) or the classic `.tcp` / `.udp` / `.telnet` tokens: the accepted
sample uses neither. Its parser wants `! COMMAND arg arg arg` on a single line,
with the bang followed by exactly one space (see
`Bashlite/analysis_notes/STATIC_TRIAGE_349d2476.md`). Reading the strings is not enough
to get this right — `Bashlite/analysis/simparse.py` executes the sample's own parser and
prints the `argc`/`argv` it would receive.

Write `static_notes.md` with: C2 endpoint, port, protocol, candidate command set,
packer status. This file decides the C2 script in Phase 4.

**Do not patch the binary.** Redirect with DNAT instead (Phase 1.2). Patching changes
the SHA-256 and the memory layout, and weakens the "ran the real sample" claim.

---

## Phase 3 — Build the C2 (three steps)

### 3.1 Observe

```bash
python3 Bashlite/c2/c2_server.py --mode observe --bind 192.168.7.1 --port 999 \
        --log Bashlite/runs/discover-$(date +%H%M).jsonl
```

Run the sample once (Phase 5, with `--count 1`). Read the log: what does the bot send
first, does it wait for a reply, what does it retry. Do not invent a handshake before
seeing this.

### 3.2 Serve a fixed timeline

Edit `Bashlite/c2/c2_script.json` so each command is something the sample actually accepts
(per Phase 3.1). Keep offsets measured from `accept()`:

| Offset | Intent |
|---|---|
| ~~20 ms~~ | ~~handshake reply~~ — not applicable: this sample speaks first and then blocks, so `handshake_at_ms` is 0 |
| 60 ms | first command, so work is already in flight when the window opens |
| ~1200 ms | second command, keeps activity across the middle of the window |
| ~2200 ms | third command / stop |
| 2450 ms | server closes; the runner's window is 2500 ms |

```bash
python3 Bashlite/c2/c2_server.py --mode serve --bind 192.168.7.1 --port 999 \
        --script Bashlite/c2/c2_script.json --sink-port 9999 --flood-seconds 3 \
        --log Bashlite/runs/c2-$(date +%H%M).jsonl --summary Bashlite/runs/c2-summary.json
```

`--flood-seconds` is the duration handed to the bot, not the capture window. Keep it
just above 2.5 s: `SendSTDHEX` loops for that many seconds *before* it reaches
`_exit(0)`, so a long value leaves a flood child running well past the trace.

### 3.3 Prove it works without malware

Two independent checks:

```bash
python3 Bashlite/c2/c2_server.py --print-script              # timeline is what you think
python3 Bashlite/c2/c2_server.py --self-test --bind 192.168.7.1 --port 999
```

The self-test connects like a dumb bot and reports what the server sends. Sink
counters (`--summary`) must move when a flood command is issued.

**Done when:** offsets land within a few milliseconds of the script, the log shows
`send` events with the expected labels, and sink counters increment.

---

## Phase 4 — Rehearsal in the VM (no scope needed)

Optional if you take the direct route: `Bashlite/docs/BASHLITE_PI_DIRECT.md` replaces this
phase with an on-Pi ladder that runs the sample natively instead of through
`qemu-arm-static`.

Follow `Bashlite/docs/BASHLITE_VM_TEST.md`, with the C2 running.

1. Revert the guest to `cloudinit-done`, boot, tunnel SSH.
2. Inside the guest apply default-deny plus an exception to the C2 reachable at
   `10.0.2.2` (QEMU NAT host address).
3. Ladder: E1 dry-run, E2 mimic with `--execute --software-trigger`, E3 real sample.
4. Confirm: bounded traces, no survivors, manifest complete, C2 log matching.

If the 32-bit sample returns `Exec format error` (126), the guest lacks 32-bit
support. Use `qemu-arm-static` for workflow checking only and record that the
behaviour is not representative.

---

## Phase 5 — Pi 5 rehearsal (still no scope)

### 5.1 Stage the sample

```bash
scp bashlite.bin pi5:/tmp/
ssh pi5 'sudo install -o victim -g victim -m 0755 /tmp/bashlite.bin \
              /home/victim/work/samples/bashlite.bin && \
         sudo -u victim sha256sum /home/victim/work/samples/bashlite.bin'
```

### 5.2 Honeypot

`regen_honeypot.sh` was written for Gonnacry (fixed total bytes to be encrypted).
Bashlite does not encrypt; it reads, writes to `/tmp`, and scans. A fixed byte total
is therefore not required, but a non-empty home is: an empty home makes every run
identical in the wrong way. Record whichever choice you make.

### 5.3 Run

```bash
# laptop
python3 Bashlite/c2/c2_server.py --mode serve --bind 192.168.7.1 --port 999 \
        --script Bashlite/c2/c2_script.json --log Bashlite/runs/run01.jsonl --summary Bashlite/runs/run01.json

# Pi, as root so the trigger works, with the sample dropped to victim
sudo python3 /tmp/bashlite_runner.py \
    --sample /home/victim/work/samples/bashlite.bin \
    --expected-hash <sha256> --execute --run-as victim \
    --gpio-pin 17 --count 3 --duration 2.5 --cooldown 0.5 \
    --manifest /home/victim/work/manifest_run01.json
```

`--run-as victim` performs `setgroups/setgid/setuid` in the child, sets `HOME`,
`USER`, and `LOGNAME`, and starts the sample in `/home/victim`. The runner itself
keeps the GPIO. Environment markers survive the privilege drop, so the leftover
sweep still finds daemonized children.

### 5.4 Prove the window is not idle — this replaces the oscilloscope for now

```bash
sudo -u victim bash -c 'timeout 2.5 /home/victim/work/samples/bashlite.bin & sleep 0.4; \
                        ps -o pid,pcpu,cmd -C bashlite.bin'
sudo -u victim strace -f -c -o /tmp/syscalls.txt -w timeout 2.5 \
     /home/victim/work/samples/bashlite.bin
```

Pass criteria:

- CPU above roughly 5 % during the window
- thousands of syscalls, with `sendto`, `socket`, `connect` present
- C2 log shows `accept` and command delivery inside the same window
- sink counters increase
- `pgrep -a bashlite` returns nothing after the trace

If the CPU figure is near zero, the C2 script is wrong or the sample is sleeping.
Fix that before collecting a single trace; an idle dataset cannot be repaired later.

---

## Phase 6 — Capture (deferred until the scope exists)

Only flags change, not logic:

- `--duration 2.5` with 2 MHz sampling; that is 5 000 000 points per trace, not 500 000
  (500 000 points at 2 MHz is only 0.25 s)
- align the trigger on one short capture first; a misaligned trigger cannot be fixed
- `vcgencmd get_throttled` = `0x0` before and after every session
- do not move the Pi or the probe between traces of one dataset

---

## Phase 7 — Cleanup and provenance

```bash
rm -f /home/victim/work/samples/bashlite.bin
sudo bash isolation-off.sh
# restore the SD image if this device holds anything you care about
```

Archive together: sample SHA-256 and source URL, `static_notes.md`, `c2_script.json`
and its version, the C2 JSONL log and summary, every manifest, the environment
fingerprint, and any deviation notes (packer, sampling rate, trace count).

---

## Known gaps and risks

| Gap | Effect | Mitigation |
|---|---|---|
| No oscilloscope | no EM data yet | Phases 0–5 are all valid preparation; nothing is wasted |
| C2 command vocabulary unknown until observed | wrong commands produce no activity | Phase 3.1 before Phase 3.2 |
| Sample may daemonize | bot survives the window | env-marker sweep every trace; verify with `pgrep` |
| Sample may require a specific port | redirect list may miss it | `--redirect-ports` in isolation-on.sh is configurable |
| DNS-dependent sample | connection never reaches the C2 | `--allow-dns` plus a local resolver, or DNAT on port 53 |
| Goodware/malware architecture mismatch | classifier may learn 32-bit vs 64-bit, not malware | out of scope here; must be resolved before training, documented as a limitation |
| Rebuilding on demand | would invalidate "in-the-wild" | never rebuild; select naturally aarch64 samples if 64-bit is required |

---

## What is still missing (honest list)

- A real sample with its SHA-256 (blocked on acquisition)
- The C2 command vocabulary for that specific sample (needs Phase 3.1)
- An oscilloscope model and probe (deferred by the operator)
- A 32-bit benign group, or an explicit acknowledgement that the current goodware
  set is 64-bit Python (see the risk table above)
