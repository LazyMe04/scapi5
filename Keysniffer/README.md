# Keysniffer

Keysniffer project area — end-to-end plan for measuring the `kisni` kernel module on
the Pi 5, as a **same-source re-instantiation** of the paper's sample.

## Status

**Measurement path validated on hardware; EM capture not started.**

| Phase | State |
|---|---|
| 0 — decision gate | **PASSED** (2026-11-09), recorded in `analysis_notes/KEYSNIFFER_PHASE0_APPROVAL.md` |
| 1 — image, fingerprint, recovery path | **not recorded** — the Pi is in use; store the image path and preflight output |
| 2 — obtain and pin the source | **source built, pinning open** — record the commit and source hashes in provenance |
| 3 — build for the running kernel | **built and loaded** on `6.18.50+rpt-rpi-2712`; record commit and hashes in provenance |
| 4 — static review | **blocked** on the Phase 2 source; checklist ready |
| 5 — load/unload rehearsal | **PASSED** (2026-11-15) — 96 fresh load/unload cycles in `smoke03`; the gate is 50 |
| 6 — synthetic keyboard | **compiled and run** on the Pi; 50 keys per trace |
| 7 — runner | **PASSED on hardware** (`kisni_runner.py`, 55 logic checks; 96/96 `ok` in `smoke03`) |
| 8 — scope trigger | **already complete** in `pico-em-capture` (see below) |
| 9 — capture campaign | **not started** — no EM captures; 1 of the 4 cells measured behaviourally |
| 10 — analysis | **written and tested** (`keysni_analyze.py`, 26 logic checks) |

Host tests run against a fake machine or the host filesystem; the lifecycle and the
measurement path have also been exercised on the Pi (`smoke03`, see
`analysis_notes/KEYSNIFFER_PROVENANCE.md` §6). No EM trace has been captured yet.

## Files

| File | Contents |
|---|---|
| `KEYSNIFFER_PLAN.md` | End-to-end plan: scope, rebuild argument, runner design, injector, manifest fields |
| `analysis_notes/KEYSNIFFER_PHASE0_APPROVAL.md` | Phase 0 approval record + deviation register (D1–D5) |
| `kisni_runner.py` | Per-trace runner: module load → settle → trigger → type → measure → unload → manifest |
| `keysni_analyze.py` | Manifest validator: ablation completeness, cell comparability, dataset identity, per-cell byte distribution |
| `keysni_preflight.py` | Read-only Phase 1/3.1/5 gate: image, throttling, headers, `CONFIG_MODULE_SIG*`, debugfs, uinput |
| `tools/keysynth.c` | `uinput` keyboard injector, absolute-clock scheduled |
| `tests/run_tests.py` | All host-runnable checks in one command |
| `docs/PI5_Keysniffer_HuongDan.md` | Detailed Vietnamese runbook: prerequisites, gates, exact commands, troubleshooting |
| `docs/PI5_Keysniffer_HuongDan.docx` | Vietnamese operator guide (generated; not the source of truth) |
| `docgen/build_keysni_guide.py` | Generates the guide from this repo's facts; rerun after any procedural change |

## Vietnamese operator guide

`docs/PI5_Keysniffer_HuongDan.docx` is the counterpart of
`Bashlite/docs/PI5_Bashlite_HuongDan.docx`: same chapter structure, different
content, because this family is measured differently. It is **generated**, and
the Markdown files here remain the source of truth — when they disagree, the
Markdown wins and the generator needs fixing.

`docs/PI5_Keysniffer_HuongDan.md` is the detailed runbook version (Vietnamese) with the
exact commands, pass/fail gates, and the failure modes found while reviewing the code.
Use it at the bench; the `.docx` is the polished companion.

```bash
uv run --no-project --with python-docx python -I Keysniffer/docgen/build_keysni_guide.py
```

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
recorded nothing. It also refuses a dataset whose manifests disagree on the artifact or
the measurement conditions — expected module hash, kernel release, `codes=`, trigger/GPIO
pin, rate, duration, injector, schema or runner version, including per-trace
`module_sha256`/`kernel_release` drift. A dry-run-only dataset is rejected explicitly: it
has the correct shape and no measurement, which is the one failure mode a shape check
cannot catch.

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
- `analysis_notes/KEYSNIFFER_PROVENANCE.md` — Phase 2/3 fields (commit, source hashes) and
  the `smoke03` identity fields still need transcribing from the bench host.
- `PATCHES.md` — only if the 4.19 source needs mechanical API adaptations.
