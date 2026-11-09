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
| `TODO` | | | | | |
