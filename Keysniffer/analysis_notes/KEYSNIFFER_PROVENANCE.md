# Provenance — source, build and artifact identity

Status: **template.** Everything marked `TODO` is filled in on the isolated analysis host
during Phase 2 and on the Pi during Phase 3. This file is the single place that answers
"which bytes produced these traces", so a placeholder must never survive into a dataset.

## 1. Source (Phase 2)

| Field | Value |
|---|---|
| Upstream | `https://github.com/jarun/spy` |
| Licence | GPL-2.0 |
| Commit | `TODO: git rev-parse HEAD` |
| Commit subject | `TODO: git log --oneline -1` |
| `spy.c` sha256 | `TODO` |
| `Makefile` sha256 | `TODO` |
| Cloned on | `TODO: date`, isolated analysis host (never Windows) |
| Copy inside the isolated host | `TODO: path` |

Why the commit is pinned: a source change between trace batches silently changes the
artifact. Two batches with different commits are two different experiments.

## 2. Build (Phase 3)

| Field | Value |
|---|---|
| Kernel release | `TODO: uname -r` |
| `CONFIG_MODVERSIONS` | `TODO: y/n` |
| `CONFIG_MODULE_SIG` / `_FORCE` | `TODO` |
| `CONFIG_DEBUG_FS` | `TODO: must be y` |
| Headers package | `TODO: linux-headers-<release>` |
| Compiler | `TODO: gcc --version` |
| Build command | `make -C /lib/modules/$(uname -r)/build M=$PWD modules` |
| `kisni.ko` sha256 | `TODO` |
| `file kisni.ko` | `TODO: must say ARM aarch64` |
| `modinfo` vermagic | `TODO: must equal uname -r exactly` |
| Frozen path | `TODO: /home/emlab/work/modules/kisni-<release>-<hash12>.ko` |

`--expected-hash` in `kisni_runner.py` must be the `kisni.ko` sha256 above. A mismatch
aborts the run before anything is loaded, which is the point: a rebuilt or replaced
module invalidates every trace that follows.

### Patches

If the 4.19 source no longer compiles against the Pi's kernel, the only permitted edits
are mechanical API adaptations. Each one goes in `PATCHES.md` as a before/after diff with
the compiler error it resolves.

**Nothing inside `spy_cb()` may be edited.** That function is the code path under
measurement; a `printk` or a counter inside it changes the artifact.

If no patch is needed, state "none" here rather than leaving the section empty.

## 3. Deviation register

These are recorded in the thesis appendix and must appear in every report that cites a
trace from this module. The list is D1–D5 in `KEYSNIFFER_PHASE0_APPROVAL.md`; restated
here because this is the file someone reads when checking a dataset:

| ID | Deviation | Consequence |
|---|---|---|
| D1 | Locally rebuilt module, not the paper's prebuilt `.ko` | Traces describe 6.18 code, not 4.19. This is a same-source re-instantiation, **not** a replication of the paper's sample |
| D2 | PicoScope 6404E, not 6407 | Bandwidth and memory depth differ; do not compare raw spectra with the paper's figures |
| D3 | One rootkit family, not two | The class is weaker than the paper's. State it |
| D4 | `uinput` injection, not physical typing | The keystroke workload is synthetic; the USB host-controller interrupt load differs from a real keyboard |
| D5 | Source identification is inferred | The provenance claim is high-confidence, not proof |

## 4. Trigger method (Phase 8 decision)

| Field | Value |
|---|---|
| Trigger source | `TODO: EXT` or `AUX` |
| Scope model | PicoScope 6404E |
| Settle time | 1.0 s (matches `bashlite_runner.py` and `goodware_runner.py`) |
| GPIO pin | 17, active-high |

`ps6000aSetSimpleTrigger` can only take its source from channels A–D, so an external
trigger means driving `AUX`/`EXT`. `pico-em-capture` already resolves this through
`resolve_trigger_source()`; the decision recorded here is which source the physical setup
uses, so the manifest and the scope config agree.

## 5. Dataset inventory

One row per completed run. The module hash must match §2 for every row.

| Run | Date | Mode | Traces | Module sha256 | Manifest |
|---|---|---|---|---|---|
| `smoke03` | 2026-11-15 | `kisni-typing` | 96 | `TODO: copy from smoke03 header` | `TODO: path on Pi` |
| `TODO` | | | | | |

## 6. Measurement-chain smoke test — `smoke03` (2026-11-15)

Purpose: prove the debugfs activity path end to end on the real kernel, after the
`stat`-based size bug was replaced by a read-length measurement. **This is not the EM
dataset**: no scope capture is described here.

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Kernel | `6.18.50+rpt-rpi-2712` |
| Runner | `kisni_runner.py` 1.0.0, manifest schema 1 |
| Mode | `kisni-typing` |
| Traces | 96 consecutive (one module load/unload per trace) |
| Status | 96/96 `ok` |
| `debugfs_bytes_before` | 0 on every trace (fresh module instance) |
| `debugfs_delta` | 160 on every trace |
| `keystroke_count` | 50, taken from keysynth stdout |
| `lsmod_after` | `false` on 96/96 |
| `keysynth_leftover` | 0 on 96/96 |
| Analyzer | no behavioral or manifest problem; non-zero only for `2x2 ablation incomplete` (three control cells not yet collected) |
| Manifest | `TODO: path on Pi` |
| Module sha256 | `TODO: copy from smoke03 header` |

What this establishes:

- the read-based measurement works on the target kernel. The previous
  `os.stat().st_size` path returned 0 before and after the trace, so this same run would
  have reported `debugfs_delta = 0` and `status = "no-activity"` on every trace;
- 96 load/unload cycles completed without a module leak or a surviving injector, which
  exceeds the 50-cycle rehearsal required by Phase 5;
- the injected workload was identical across traces (same key sequence, rate and window),
  so the byte delta is deterministic and the buffer never wrapped.

What this does **not** establish: any EM-side-channel separability, the missing 2x2
control cells (`typing-only`, `kisni-idle`, `idle`), or a completed dataset. The behavioral
figures above are transcribed from the bench session report, not re-derived from the
manifest in this repo; transcribe `expected_hash`, `trigger`/`gpio_pin`, `codes`, `rate`,
`duration_s` and the manifest path from the smoke03 header before citing this run.
