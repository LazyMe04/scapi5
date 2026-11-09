# Keysniffer

Keysniffer project area — end-to-end plan for measuring the `kisni` kernel module on
the Pi 5, as a **same-source re-instantiation** of the paper's sample.

## Status

**Code is written and tested; no trace has been captured yet.**

| Phase | State |
|---|---|
| 0 — decision gate | **PASSED** (2026-11-09), recorded in `analysis_notes/KEYSNIFFER_PHASE0_APPROVAL.md` |
| 1 — image, fingerprint, recovery path | **blocked on hardware** — run `keysni_preflight.py` on the Pi |
| 2 — obtain and pin the source | **blocked on the isolated analysis host** |
| 3 — build for the running kernel | **blocked** on Phases 1–2; `keysynth.c` also needs a C compiler |
| 4 — static review | **blocked** on the Phase 2 source; checklist ready |
| 5 — load/unload rehearsal | **blocked on hardware** — `keysni_preflight.py` covers the prerequisites |
| 6 — synthetic keyboard | **written** (`tools/keysynth.c`), **not compiled or run** |
| 7 — runner | **written and tested** (`kisni_runner.py`, 43 logic checks) |
| 8 — scope trigger | **already complete** in `pico-em-capture` (see below) |
| 9 — capture campaign | **blocked on hardware** |
| 10 — analysis | **written and tested** (`keysni_analyze.py`, 15 logic checks) |

Nothing in this directory has been executed against a kernel module. Every test below
runs against a fake machine or on the host filesystem, which is the point: the logic
that decides whether to load a module should be proven before a module is involved.

## Files

| File | Contents |
|---|---|
| `KEYSNIFFER_PLAN.md` | End-to-end plan: scope, rebuild argument, runner design, injector, manifest fields |
| `analysis_notes/KEYSNIFFER_PHASE0_APPROVAL.md` | Phase 0 approval record + deviation register (D1–D5) |
| `kisni_runner.py` | Per-trace runner: module load → settle → trigger → type → measure → unload → manifest |
| `keysni_analyze.py` | Manifest validator: ablation completeness, cell comparability, per-cell byte distribution |
| `keysni_preflight.py` | Read-only Phase 1/3.1/5 gate: image, throttling, headers, `CONFIG_MODULE_SIG*`, debugfs, uinput |
| `tools/keysynth.c` | `uinput` keyboard injector, absolute-clock scheduled |
| `tests/run_tests.py` | All host-runnable checks in one command |

## Running the tests

```bash
python3 -I Keysniffer/tests/run_tests.py
```

This covers the runner lifecycle (through a fake machine, so no root and no module),
the analyzer's dataset validation, the preflight checks, every guard rail that must
refuse a bad invocation, and the `keyboard` profile added to `goodware_runner.py`.

**Not covered:** `tools/keysynth.c`. It needs a C compiler and `/dev/uinput`, neither of
which exists on the authoring host, so a test that only proved it parses would be
misleading. It is built and exercised in Phase 3/Phase 6 on the Pi.

## Using the tools

On the Pi, before Phase 2:

```bash
python3 -I Keysniffer/keysni_preflight.py --image ~/pi5-prekeysniffer-2026-11-09.img
```

Dry run of the runner, no module, no root (safe on any host):

```bash
python3 -I Keysniffer/kisni_runner.py --mode kisni-typing --count 2 --run-dir /tmp/dry
```

A real trace, after Phases 1–5 have passed:

```bash
sudo python3 -I Keysniffer/kisni_runner.py \
    --module /home/emlab/work/modules/kisni-6.18.50-<hash>.ko \
    --expected-hash <sha256> --execute \
    --mode kisni-typing --keysynth /home/emlab/work/tools/keysynth \
    --keyfile /home/emlab/work/keys.txt --rate 20 --count 20 --duration 2.5 \
    --run-dir /home/emlab/work/runs/run01
```

Then check the dataset before training anything on it:

```bash
python3 -I Keysniffer/keysni_analyze.py /home/emlab/work/runs/run01/manifest.jsonl
```

The analyzer exits non-zero on an incomplete ablation, mismatched keyfiles or key rates
between the two typing cells, a reused module buffer, a failed trace, or a module that
recorded nothing. A dry-run-only dataset is rejected explicitly: it has the correct
shape and no measurement, which is the one failure mode a shape check cannot catch.

## Phase 8 is already done

The plan predicted a scope-trigger gap. `pico-em-capture` has since grown the support:
`EXTERNAL = 1000` and `TRIGGER_AUX = 1001` in `picoscope6404e.py`, `setup_external_trigger()`
on the scope class, and `resolve_trigger_source()` routing `EXT`/`AUX` through it in
`capture.py`. No change was needed here.

## Known limitation in the keyboard profile

`goodware_runner.py` asserts the trigger *before* it starts the workload. For the
`keyboard` profile that means the process-spawn and `uinput` device-creation cost
(`UI_DEV_SETUP` + `UI_DEV_CREATE` + a 200 ms settle inside `keysynth`) lands inside the
trigger window, while the other profiles start their work immediately. The first
keystroke therefore arrives ~200 ms after the edge, not at it.

That is acceptable for the `typing-only` control cell as long as `kisni-typing` has the
same offset — both go through `keysynth`, so both carry it. It is **not** acceptable to
compare the keyboard cells' first 200 ms against a crypto or idle trace. Trim the leading
window in analysis, or start `keysynth` before asserting the trigger if a later revision
needs an edge-aligned workload.

## Invariants

Permitted, in this order only:

1. Phase 1 — image the SD card, confirm a recovery path, fingerprint the environment.
2. Phase 2 — obtain and pin the published GPL-2.0 source on the isolated analysis host.

Never:

- Build or load the module before Phase 1's image and recovery path exist.
- `insmod --force`, or disable module signature enforcement. A refused module is a
  reported blocker, not something to route around.
- Load the paper's prebuilt `kisni-4.19.57-v7+.ko` — it is foreign-arch and will be rejected.
- Edit anything inside `spy_cb()`. That function is the code path under measurement.
- `maK_It`, in any form.
- Type over SSH and expect a trace. `kisni` hooks the VT keyboard notifier; SSH keystrokes
  never reach it. The result is a valid-looking idle trace and a wasted campaign.

## Deliverables still to be written on the Pi

- `analysis_notes/KEYSNIFFER_STATIC_REVIEW.md` — Phase 4, needs the pinned source.
- `analysis_notes/KEYSNIFFER_PROVENANCE.md` — Phase 2/3, needs the pinned commit and build hashes.
- `PATCHES.md` — only if the 4.19 source needs mechanical API adaptations.
