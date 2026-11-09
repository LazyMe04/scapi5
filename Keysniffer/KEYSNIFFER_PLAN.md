# Keysniffer on the Pi 5 — end-to-end plan

**Scope of this document:** one malware family, one device, one measurement question.
Keysniffer (`kisni`) as a **Linux kernel module built from its published upstream source**
for the Pi 5's own aarch64 kernel, loaded on the bench Pi, exercised by a **synthetic
keyboard**, and measured with the same scope configuration as the other classes.

**Out of scope:** `maK_It`, Mirai, Bashlite re-runs, any change to the goodware set beyond
adding a keyboard-typing profile.

This plan deliberately conflicts with the *historical* text of
`.cursor/rules/em-lab-invariants.mdc` ("Kernel modules `keysniffer` and `maK_it` cannot load;
do not attempt them") and with `pi5_setup/pi5_setup_instructions.md` §4.5 / Appendix B.
**Phase 0 is a gate, not a formality.**

> **Phase 0 status: PASSED 2026-11-09.** The four questions in §0.1 were answered
> affirmatively and the five documents in §0.2 were amended. The record, including the
> deviation register that must precede the first trace, is
> `Keysniffer/analysis_notes/KEYSNIFFER_PHASE0_APPROVAL.md`. Phases 1–10 are still
> unimplemented; Phase 1 has not started.

---

## 0. Why this plan exists, and what changed

The exclusion was justified by one true statement: *a prebuilt `.ko` must match kernel
version, kernel configuration and CPU architecture exactly, so the paper's
`kisni-4.19.57-v7+.ko` (32-bit ARM, kernel 4.19) cannot load on a Pi 5 (aarch64, kernel 6.x).*

That statement is true and remains true. It does **not** imply what the rule text says next
("kernel modules cannot work on this device"). It only rules out *loading a foreign binary*.
The module is open source, GPL-2.0, published by its author, and its source still builds
against current mainline interfaces:

| Interface the module needs | Status on Linux 6.18 mainline | Evidence |
|---|---|---|
| `register_keyboard_notifier()` / `unregister_keyboard_notifier()` | exported, `EXPORT_SYMBOL_GPL` | `drivers/tty/vt/keyboard.c` |
| `struct keyboard_notifier_param` with `.down`, `.shift`, `.value` | unchanged | `include/linux/keyboard.h` |
| Consumer-side notifier fired from `kbd_keycode()` | still fired for `KBD_KEYCODE` | `drivers/tty/vt/keyboard.c` |
| `debugfs_create_dir()` / `debugfs_create_file()` / `simple_read_from_buffer()` | unchanged | module source |

So the real decision is not "can a kernel module work" but **"may the artifact be rebuilt
from source"** — which is exactly the question the project already answered *no* for
Bashlite. The distinction matters and must be written down:

| Artifact | Provenance | Rebuild allowed? |
|---|---|---|
| Bashlite | closed, in-the-wild ELF; SHA-256 is the identity | **No** — a rebuild replaces the author's toolchain and the sample stops being in-the-wild |
| Keysniffer (`kisni`) | open source GPL-2.0; the paper's own sample *is* a build of this source | **Yes, conditionally** — identity is the source revision, not one binary's hash |

What a rebuild costs you scientifically, stated plainly:

- The trace no longer describes the paper's kernel 4.19 input/VT code. It describes 6.18's.
- It is therefore a **same-source re-instantiation on new hardware**, not a replication of
  the paper's `kisni` traces. The thesis must say that.
- The module's *behaviour* (hook console keyboard events, append to a debugfs file) is
  identical, which is the property the EM classifier is supposed to key on.

`maK_It` is **not** covered by this argument. Its source is not published by the same route,
and it adds a hidden-module, packet-sniffer and reverse-shell component. It stays excluded.

---

## 1. What the paper actually did with keysniffer

Facts extracted from `og_research.txt` (ACSAC '21), so the plan matches the methodology:

| Fact | Value |
|---|---|
| Sample name | `kisni-4.19.57-v7+.ko` |
| Traces recorded | 3 000 |
| Type tag | `rootkit` (shared with `maK_It`) |
| Family tag | `kisni` |
| Novelty split | `maK_It` **training only**, `kisni` **test only** |
| Reported behaviour | hooks and records keys pressed from keyboard events to `debugfs` |
| Executable scenario | "nearly no confusion" between `maK_it` and `keysniffer` |
| Capture parameters | 2 MHz, 2.5 s = 5 000 000 points, probe 45° over the CPU |

Consequences for this project:

1. A single-family rootkit class is a weaker class than the paper's two-family one. Record
   it; do not hide it.
2. The paper's novelty split (train on `maK_It`, test on `kisni`) cannot be reproduced with
   one family. Use an ordinary train/test split on `kisni` and say so.
3. The paper's rootkit class is *kernel-resident code with no userland process*. Any
   controlled comparison against userland workloads has a kernel/userland confound. The
   ablation in Phase 6 is how you keep that confound visible instead of letting the
   classifier absorb it silently.

### 1.1 Identifying the source (high confidence, not proof)

The paper gives only the filename. The matching public project is **`jarun/spy`**
(module name `kisni`, description *"Sniff and log keys pressed in the system to debugfs"*,
author Arun Prakash Jana, GPL v2, version 1.8). The project's CHANGELOG records that it was
renamed from `keysniffer`; the README states the module name is deliberately camouflaged.
The paper's binary is named exactly `kisni-4.19.57-v7+`.

Treat this as **high-confidence identification, still unproven**. If the paper's `.ko` can be
obtained from the authors, run `modinfo` on it and compare `description`, `author`,
`srcversion` and source structure before claiming the match in the thesis. If it cannot be
obtained, cite the project and state the identification as inferred.

The plan uses upstream `spy.c` v1.8 as the build input either way, because it is the only
public source that matches the described behaviour.

---

## Phase 0 — Decision gate (do this before anything else)

> **PASSED 2026-11-09.** Answers and the amended-document record are in
> `Keysniffer/analysis_notes/KEYSNIFFER_PHASE0_APPROVAL.md`. The checklist below is retained
> as the record of what was asked.

### 0.1 Questions the operator must answer in writing

- [ ] Has the supervisor approved extending scope to this family?
- [ ] Is a **same-source rebuild** on aarch64 acceptable, given §0's cost statement?
- [ ] Is the resulting class reported as *rootkit (keysniffer, rebuilt)* rather than as a
      replication of the paper's `kisni`?
- [ ] Does the thesis deviation register get an entry **before** the first trace?

If any answer is no, stop here and keep the four-class design. Nothing below is wasted
knowledge, but none of it gets executed.

### 0.2 Documentation changes the approval implies

Do not run Phase 3 until these are consistent, or the repo will contain two contradictory
safety rules:

| File | Change |
|---|---|
| `.cursor/rules/em-lab-invariants.mdc` | replace the blanket ban with: prebuilt foreign-arch `.ko` may not be loaded; an out-of-tree build of published GPL source for the running kernel is permitted in the lab only, per `Keysniffer/KEYSNIFFER_PLAN.md` — **done 2026-11-09** |
| `pi5_setup/pi5_setup_instructions.md` §4.5, Appendix B | same narrowing; keep the `maK_It` ban — **done 2026-11-09** |
| `pi5_setup/pi5_setup_report.md` | append a dated amendment — **done 2026-11-09** |
| `third_run/weekly_report_2026-09-27.md` §5.3 | do not edit the historical report; add a later report entry that supersedes it — **superseded by `KEYSNIFFER_PHASE0_APPROVAL.md` §3, 2026-11-09** |
| `BENCH_OPERATIONS.md` §3 | add the kernel-module rule and the crash-recovery requirement — **done 2026-11-09** |

**Gate:** written approval exists, and the four documents above agree with each other.

---

## Phase 1 — Restore point and environment fingerprint

The Pi has no snapshots and a kernel module can panic the machine. Imaging is not optional
here; it is the only rollback.

```bash
# laptop, SD card mounted
lsblk -o NAME,SIZE,MODEL,MOUNTPOINT
sudo dd if=/dev/sdX of=pi5-prekeysniffer-$(date +%F).img bs=4M status=progress conv=fsync
sha256sum pi5-prekeysniffer-$(date +%F).img > pi5-prekeysniffer-$(date +%F).img.sha256
```

Record on the Pi (goes into the manifest and thesis appendix):

```bash
uname -a
uname -r > /tmp/krel.txt                  # expected 6.18.34+rpt-rpi-2712 or later
cat /etc/os-release
vcgencmd get_throttled                    # must be 0x0
grep -E 'arm_freq|overclock|force_turbo' /boot/firmware/config.txt   # must be empty
sudo bash preflight.sh              # run while internet is still available
```

Note: the repo carries two different kernel versions (`6.18.34` in `pi5_setup_report.md`,
`6.18.50` in `BENCH_OPERATIONS.md`). Re-verify; every module build is tied to the exact
release string, so a stale assumption here produces an unloadable module two phases later.

**Recovery path before you can brick the machine:** confirm you can reach the Pi after a
panic. Either an HDMI display + USB keyboard, or a UART console (`enable_uart=1` in
`/boot/firmware/config.txt`, documented as a debug-only change — it is not a clock setting),
or the SD card can be pulled and re-flashed. Write down which one you have.

**Gate:** image exists and hashes; `get_throttled` is `0x0`; a documented recovery path exists.

---

## Phase 2 — Obtain and pin the source

On the isolated analysis host, never on Windows:

```bash
git clone https://github.com/jarun/spy.git
cd spy
git log --oneline -1
git rev-parse HEAD > /tmp/src-rev.txt
sha256sum spy.c Makefile > /tmp/src.sha256
```

Pin the revision in the plan and in every manifest. Do not track a moving branch: a source
change between trace batches silently changes the artifact.

Upstream facts you will need:

- module name `kisni`, built from `spy.o`
- module parameter `codes` (0 = US keymap text, 1 = hex `keycode shift`, 2 = decimal)
- log file `/sys/kernel/debug/kisni/keys`, mode 0400, 16 KB wrap-around buffer
- `module_init` creates the debugfs entry then registers the notifier; `module_exit` reverses it

`codes=1` is the better default for this experiment: fixed-width records, no UTF-8 or
keymap-layout noise in the byte count used as the activity proxy in Phase 7.

**Gate:** pinned commit, recorded hashes, and a copy of the source inside the isolated host.

---

## Phase 3 — Build for the running Pi 5 kernel

### 3.1 Prerequisites, all verified before building

```bash
sudo apt install -y build-essential linux-headers-$(uname -r)
# if that exact package is unavailable for the rpt kernel, try the meta package:
apt-cache policy linux-headers-rpi-2712
```

```bash
ls -l /lib/modules/$(uname -r)/build          # must exist and point at /usr/src/linux-headers-<ver>
ls /lib/modules/$(uname -r)/Module.symvers    # needed if CONFIG_MODVERSIONS=y
zgrep -E 'CONFIG_MODVERSIONS|CONFIG_MODULE_SIG|CONFIG_MODULE_SIG_FORCE|CONFIG_MODULE_SIG_ALL' \
      /boot/config-$(uname -r)
```

Decision table for the config:

| Setting | Meaning for this plan |
|---|---|
| `CONFIG_MODVERSIONS=y` | build must use the Pi's `Module.symvers`; a mismatch gives "no symbol version for module_layout" at `insmod` |
| `CONFIG_MODULE_SIG=y`, `FORCE` not set | unsigned in-tree-lab module loads; taints the kernel (`Tainted: G OE`) |
| `CONFIG_MODULE_SIG_FORCE=y` | unsigned modules are refused. **Do not disable it.** Sign with the local MOK key if one exists, otherwise report the blocker and stop |
| `CONFIG_DEBUG_FS=y` | `/sys/kernel/debug/kisni/keys` will exist |

Do **not** use `insmod --force`. Forcing past version magic is how you turn a lab exercise
into an undebuggable panic.

### 3.2 Build

```bash
cd spy
make -C /lib/modules/$(uname -r)/build M=$PWD modules
file kisni.ko
modinfo kisni.ko
```

Expected: `ELF 64-bit LSB relocatable, ARM aarch64`, `vermagic: <the Pi's exact release>`.

Compiler warnings are acceptable; **errors are not patched around silently**. If the 4.19
source no longer compiles, the only permitted edits are mechanical API adaptations
(replacing a removed helper, fixing a signature), each one recorded in a `PATCHES.md` with
a before/after diff. Never add a counter, a printk, or any code inside `spy_cb()` — that
function is the code path under measurement, and instrumenting it changes the artifact.

### 3.3 Hash and freeze the artifact

```bash
sha256sum kisni.ko > kisni.ko.sha256
cp kisni.ko /home/emlab/work/modules/kisni-$(uname -r)-$(sha256sum kisni.ko | cut -c1-12).ko
```

**Gate:** `file` says aarch64, `vermagic` matches `uname -r`, the module is hashed, and no
edit touched the notifier callback.

---

## Phase 4 — Static review before loading

> **Status 2026-11-09: blocked on Phase 2.** `analysis_notes/KEYSNIFFER_STATIC_REVIEW.md`
> holds the checklist and procedure, with every verdict blank. Filling them in before the
> pinned source exists would be a fabricated review; this file is also the record that the
> lab loaded a keylogger deliberately.

Loading a kernel module is the highest-privilege action in this project. Read the source
before it runs.

```bash
grep -n "module_param\|debugfs_create\|register_keyboard_notifier\|module_init\|module_exit" spy.c
```

Checklist:

- [ ] `module_init` is error-safe: on failure it removes the debugfs directory and returns an
      error code, leaving no half-registered notifier
- [ ] `module_exit` unregisters the notifier **before** removing the directory
- [ ] the callback returns without dereferencing anything that can be NULL
- [ ] the buffer write cannot exceed `BUF_LEN` (upstream bounds-checks and wraps; confirm in
      the pinned revision)
- [ ] no networking, no file writes outside debugfs, no process interaction
- [ ] `MODULE_LICENSE("GPL v2")` present, required by `EXPORT_SYMBOL_GPL`

Record the review as `Keysniffer/analysis_notes/KEYSNIFFER_STATIC_REVIEW.md`, including the
pinned commit and the fact that this is a keylogger — the review is also the record that
the lab loaded it deliberately.

**Gate:** review written; no unexplained behaviour in the source.

---

## Phase 5 — Load/unload rehearsal and crash recovery

Do this on a throwaway image state, with nothing valuable on the card.

```bash
sudo dmesg -C
sudo insmod /home/emlab/work/modules/kisni-<ver>-<hash>.ko codes=1
echo "insmod=$?"
dmesg | tail -20
ls -l /sys/kernel/debug/kisni/keys
lsmod | grep kisni
```

Then type on the console (see Phase 6 for the injector) and confirm the log grows:

```bash
stat -c %s /sys/kernel/debug/kisni/keys
```

Unload and confirm a clean exit:

```bash
sudo rmmod kisni
echo "rmmod=$?"
lsmod | grep kisni || echo "unloaded"
dmesg | tail -20
sudo dmesg | grep -i 'taint'
```

Repeat the load/unload cycle **50 times** unattended. A module that leaks a notifier or a
dentry per cycle panics on the 60th load, not the first. If any cycle fails, stop: no
capture from an unstable module.

Failure handling:

| Symptom | Meaning | Action |
|---|---|---|
| `insmod: Invalid module format` | vermagic mismatch | rebuild against the running kernel; never force |
| `insmod: Unknown symbol module_layout` | `Module.symvers` / modversions mismatch | install matching headers, rebuild |
| `Operation not permitted` | signature enforcement | see §3.1 table; do not disable enforcement |
| dmesg Oops on load | failed `module_init` path | capture the trace, fix source, re-review |
| machine hangs | panic | power cycle, check `/var/log` or serial console, record it |

**Gate:** 50 clean cycles, log file present and growing, no leftover `kisni` entry in `lsmod`.

---

## Phase 6 — Synthetic keyboard: the activity source

> **Status 2026-11-09.** `tools/keysynth.c` is written. It has **not been compiled or
> run**: no C compiler exists on the authoring host, so it is reviewed statically and
> built in Phase 3 on the Pi. The `keyboard` profile in `goodware_runner.py` is written
> and tested against a stub injector. The Phase 6 gate below still requires the Pi.

This is the methodological core. `kisni` logs **console (`VT`) keyboard events**, produced
when an input device is bound to `kbd_handler` in `drivers/tty/vt/keyboard.c`. Consequences:

- SSH keystrokes do **not** pass through that path. Typing over SSH produces no notifier
  callbacks and therefore an idle trace. This is the single most likely way to waste a
  whole capture campaign.
- A headless Pi has no keyboard, so the workload must be synthesised.

### 6.1 Primary injector: `uinput`

A `uinput` device that declares `EV_KEY` with ordinary keycodes is matched by
`kbd_match()` (`find_next_bit(dev->keybit, BTN_MISC, KEY_RESERVED) < BTN_MISC`) and bound to
the console keyboard handler, so injected events do reach `kbd_keycode()`.

Write a small C tool `Keysniffer/tools/keysynth.c` rather than a Python one:

- `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` for a fixed inter-key interval — jitter
  in the keystroke rate becomes visible jitter in the spectrogram
- deterministic keystroke sequence from a file, hashed into the manifest
- `EV_KEY` press + `SYN_REPORT`, release + `SYN_REPORT`; optional hold/repeat
- prints the exact number of events emitted and the first/last monotonic timestamps
- exits non-zero if `/dev/uinput` cannot be opened

Bootstrap once:

```bash
sudo modprobe uinput
ls -l /dev/uinput
sudo chvt 1                      # make sure a VT is active and allocated
```

Parameters that must be **constant across every trace** (they are part of the workload
definition, not tunables):

| Parameter | Value | Why |
|---|---|---|
| keys per window | ~50 at 20 keys/s | keeps the callback rate well inside 2.5 s without saturating |
| inter-key interval | 50 ms | reproducible; ten-plus callbacks per 500 ms |
| key set | letters + digits only | US keymap covers them; avoids unmapped-key early return |
| sequence | one pinned text file, hashed | comparability across runs |

### 6.2 Secondary source, only if `uinput` is unavailable

A microcontroller (e.g. a Pi Pico) acting as a USB HID keyboard, typing a stored script.
This is reliable and hardware-real, but adds a USB host-controller interrupt workload that
`uinput` does not have. Do not mix the two within one dataset; pick one and record which.

### 6.3 The ablation set — 2×2

Without this, the classifier can learn "the keyboard was busy" instead of "a rootkit is
resident", and every accuracy number becomes meaningless.

| Cell | Module | Typing | Purpose |
|---|---|---|---|
| `kisni-typing` | loaded | yes | the malware class |
| `typing-only` | not loaded | yes | equal-workload benign control |
| `kisni-idle` | loaded | no | isolates the module's baseline footprint |
| `idle` | not loaded | no | the existing idle reference |

Minimum campaign: `kisni-typing` and `typing-only`. The other two are cheap and make the
analysis defensible; capture them if the schedule allows.

`typing-only` must go into the benign class of the dataset, not into a separate experiment,
so that the classifier is forced to separate the module from the workload rather than from
the absence of input.

### 6.4 Extend the existing goodware runner instead of creating a parallel one

Add a `keyboard` profile to `goodware_runner.py`, reusing the exact same
`HardwareTrigger` semantics (GPIO 17 active-high, 1.0 s settle), the same duration, cooldown
and manifest shape. The trace is only comparable if the trigger and window are produced by
the same code path that produced the Bashlite and Gonnacry traces.

**Gate:** with `kisni` loaded, `keysynth` increments `/sys/kernel/debug/kisni/keys` by
exactly the expected number of records; with `kisni` unloaded, it does not. With SSH-only
typing, it does not increment at all. Confirm all three.

---

## Phase 7 — Runner

> **Status 2026-11-09.** `Keysniffer/kisni_runner.py` is written and tested: 43 logic
> checks run through a fake machine, so the lifecycle is proven without root, without a
> module, and without the Pi. The Phase 7 gate below (one real trace with a non-zero byte
> delta and a clean `lsmod`) still requires the hardware.

Kernel-resident code has no PID, so `bashlite_runner.py` cannot supervise it. Add
`Keysniffer/kisni_runner.py` rather than bending the sample runner; keep the sample runner's
containment gate, trigger and manifest conventions.

### 7.1 Per-trace lifecycle (a trace is a lifecycle, not a sleep)

```
1  verify  .ko sha256 matches --expected-hash
2  verify  modinfo vermagic == uname -r
3  rmmod kisni (ignore "not loaded")
4  insmod kisni codes=1                     ← outside the measurement window
5  settle  1.0 s
6  stat    byte count of /sys/kernel/debug/kisni/keys  → before
7  trigger ON  (GPIO 17 active-high)
8  spawn   keysynth for --duration (default 2.5 s)
9  trigger OFF
10 stat    byte count → after      (must be > before)
11 rmmod kisni
12 verify  no `kisni` in lsmod; no leftover keysynth; record dmesg tail
13 append  one JSONL manifest record
```

Reloading per trace is deliberate: the debugfs buffer wraps at 16 KB and cannot be
truncated from userspace, so a byte-count delta is only meaningful if each trace starts
from a fresh module instance. Reload is outside the trigger window, so the module-load code
path does not contaminate the trace.

### 7.2 CLI

```
Keysniffer/kisni_runner.py
  --module PATH               .ko to load
  --expected-hash SHA256      required with --execute
  --mode {kisni-typing,typing-only,kisni-idle,idle}
  --count N  --duration 2.5  --cooldown 0.5
  --trigger {gpio17,software} [--gpio-pin 17]
  --keysynth PATH --keyfile PATH --rate 20
  --manifest PATH --run-dir PATH
  --execute                   required for any real load
  --allow-taint               acknowledge the kernel will be tainted (recorded, not fatal)
```

Semantics copied from `bashlite_runner.py` so the traces stay comparable: dry run by
default, hash required for real execution, per-trace manifest, trigger fallback recorded
rather than silently downgraded, exit codes `2` containment, `3` sample, `4` format, `5` run-as.

### 7.3 Containment

`kisni` performs no networking. The default-deny OUTPUT policy from `isolation-on.sh` still
applies and the runner's containment gate will classify it `full`; no C2 exception is needed.
Do **not** run `isolation-on.sh` with a C2 port exception for this family — fewer open paths
is one less thing to explain later. `REQUIRED_PORTS` in the sample runner is Bashlite-specific
and is not a template for this one.

### 7.4 Manifest fields specific to this family

`module_sha256`, `module_vermagic`, `kernel_release`, `module_load_monotonic_ns`,
`module_unload_monotonic_ns`, `debugfs_bytes_before`, `debugfs_bytes_after`,
`keystroke_file_sha256`, `keystroke_count`, `keystroke_interval_ms`, `injector`
(`uinput`|`hid`), `dmesg_taint`, `lsmod_after`, `trigger_edge_ns_on`, `trigger_edge_ns_off`.

**Gate:** one dry run and one real trace produce complete manifests, the byte delta is
non-zero, and `lsmod` is clean afterwards.

---

## Phase 8 — Scope trigger — a real gap in `pico-em-capture`

> **Status 2026-11-09: no work needed.** The gap this phase described is closed upstream
> in `pico-em-capture`: `EXTERNAL = 1000` and `TRIGGER_AUX = 1001` at
> `picoscope6404e.py:63-64`, `setup_external_trigger()` at `picoscope6404e.py:467`, and
> `resolve_trigger_source()` at `capture.py:54` routing `EXT`/`AUX` through it from
> `configure_scope()`. Verified by reading the code, not assumed. Record which source the
> physical setup uses in `analysis_notes/KEYSNIFFER_PROVENANCE.md` §4.

`pico-em-capture/picoscope6404e.py` implements only `ps6000SetSimpleTrigger`, which sources
the trigger from channels A–D. Channel A is the EM probe. GPIO 17 has nowhere to land. The
current capture code therefore **cannot start a trace on the Pi's trigger edge** — this is
true for Bashlite too, and is worth fixing before either campaign.

Two fixes, in preference order:

1. **External trigger (EXT/AUX input).** Add `setup_external_trigger()` wrapping
   `ps6000SetTriggerChannelConditions` with `PS6000_TRIGGER_AUX` and
   `ps6000SetTriggerChannelDirections` for a rising edge. Wire GPIO 17 → scope EXT BNC,
   common ground to the Pi's ground pin, verify 3.3 V high at the Pi header with a
   multimeter before connecting. Confirm the 6404E's EXT input accepts the Pi's 3.3 V logic
   level in its manual.
2. **Trigger on channel B.** Feed GPIO 17 into channel B, set that channel's range so 3.3 V
   is inside it (e.g. ±5 V), trigger above ~2 V on B, probe stays on A.

Either way: do a single short capture, confirm the trace starts at the trigger edge and not
in an idle pre-roll, and record the chosen method. A misaligned trigger cannot be fixed
after the campaign.

Also note the paper used a 6407; ours is a 6404E. Record the substitution as a deviation.

**Gate:** one trace shows the workload starting inside the window, verified against the
trigger timestamp in the manifest.

---

## Phase 9 — Capture campaign

Per-cell volume, following the paper's 3 000 traces per binary:

| Cell | Traces | Wall clock at ~3.2 s/trace | Disk at ~40 MB/trace (float64 .npy) |
|---|---|---|---|
| `kisni-typing` | 3 000 | ~2.7 h | ~120 GB |
| `typing-only` | 3 000 | ~2.7 h | ~120 GB |
| `kisni-idle` | 1 000 (optional) | ~0.9 h | ~40 GB |
| `idle` | 1 000 (optional) | ~0.9 h | ~40 GB |

Run rules, identical to the Bashlite campaign:

- `vcgencmd get_throttled` = `0x0` before and after every session
- `wlan0` down, radios soft-blocked
- do not move the Pi, probe, or amplifier within a dataset
- one manifest per trace, append-only, resumable by `--count`/run-dir
- re-verify the module hash at session start; a changed `.ko` invalidates the dataset
- after every 100 traces: confirm `lsmod` is clean and `dmesg` has no Oops
- if the machine panics mid-campaign, the session ends; reimage, then resume from the last
  manifest line

Ordering: capture `typing-only` and `kisni-typing` in interleaved blocks rather than one
long block of each. Drift in temperature or ambient conditions then affects both cells
equally, instead of masquerading as class separation.

**Gate:** both required cells reach 3 000 traces, manifests complete, byte-delta non-zero on
every trace, no trace from an unloaded or unverified module.

---

## Phase 10 — Analysis and record keeping

> **Status 2026-11-09.** `Keysniffer/keysni_analyze.py` is written and tested (15 checks).
> It automates the "minimum analysis to show the class is real" below: per-cell byte
> distribution, ablation completeness, and the comparability checks that make the
> `typing-only` control meaningful. The STFT/NICV/classifier work still needs captured
> traces.

Minimum analysis to show the class is real before any ML claim:

```bash
# per-cell distribution of debugfs bytes / trace
jq -r 'select(.mode=="kisni-typing") | .debugfs_bytes_after - .debugfs_bytes_before' \
   manifests/*.jsonl | sort -n | uniq -c
```

- `kisni-typing` and `typing-only` must have the same keystroke count and the same window
  length, or the comparison is invalid
- spectrograms at STFT 8192/4096, NICV-selected bands, per the paper
- run the type/family classifiers with and without the `typing-only` ablation and report both
  numbers — the gap between them is the honest measure of how much of the signal was the
  keyboard rather than the rootkit

Deliverables:

| Item | Where |
|---|---|
| This plan | `Keysniffer/KEYSNIFFER_PLAN.md` |
| Static review | `Keysniffer/analysis_notes/KEYSNIFFER_STATIC_REVIEW.md` |
| Source revision, hashes, patch set | `Keysniffer/analysis_notes/KEYSNIFFER_PROVENANCE.md` |
| Trigger method decision | same file, `trigger` section |
| Deviation register entry | thesis appendix: rebuild instead of the paper's prebuilt `.ko`; 6404E instead of 6407; single-family rootkit class; `uinput` instead of physical typing |
| Dataset manifests + module `.ko` hash | archived per run |

Cleanup at the end of the campaign:

```bash
sudo rmmod kisni
lsmod | grep kisni || echo "clean"
rm -f /home/emlab/work/modules/*.ko        # keep the source and the hash, not the binary
sudo bash isolation-off.sh
```

---

## Known gaps and risks

| Gap | Effect | Mitigation |
|---|---|---|
| Source identification is inferred | provenance claim could be wrong | get the paper's `.ko` if possible; otherwise state it as inferred |
| Rebuild ≠ paper's sample | traces describe 6.18 code, not 4.19 | document as a deviation; do not claim replication |
| Single rootkit family | weaker class than the paper's two | state it; consider `maK_It` only if its source can be obtained the same way |
| Kernel module can panic the Pi | lost session, possible SD corruption | image first, recovery path, 50-cycle rehearsal, per-trace resume |
| Kernel signature enforcement | module refused | do not force; report the blocker |
| `uinput` unavailable | no reproducible keystrokes | fall back to a USB HID microcontroller and record the switch |
| SSH typing produces nothing | idle traces that look valid | Phase 6.3 gate check catches this before capture |
| No typing-only ablation | classifier learns the workload, not the malware | mandatory `typing-only` cell |
| Scope trigger gap | traces do not start at the edge | Phase 8 fix before either campaign |
| Kernel/userland confound | rootkit class differs from userland classes structurally | keep in limitations; the 2×2 ablation keeps it measurable |

---

## What is still missing (honest list)

- Supervisor approval and the §0.2 documentation amendments
- Confirmation that headers for the Pi's exact kernel release can be installed offline
- Confirmation of module signature enforcement on the current image
- A decision on the external-trigger wiring (EXT BNC vs channel B)
- The paper's actual `.ko`, to turn "high confidence" into proof
- No oscilloscope-dependent step can start before Phase 8 is resolved
