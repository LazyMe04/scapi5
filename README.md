# bench — EM IoT malware lab tooling

This repository holds the tooling for the electromagnetic side-channel lab:
capture hardware drivers, Pi-side runners, C2 rehearsal servers, isolation
scripts, and static-analysis utilities for malware samples.

## Layout

| Area | Contents | Kind |
|---|---|---|
| `Bashlite/` | Bashlite project: runner, C2, runbooks, static-analysis tools, staged sample | project |
| `Keysniffer/` | Keysniffer project: plan, runner, analyzer, preflight, `uinput` injector, tests | project |
| `goodware_runner.py` | Benign workload runner (GPIO 17 trigger, GPIO/ACT LED) shared by all families; writes a resumable JSONL manifest | shared |
| `em_analysis.py` | STFT (8192/4096) + NICV feature selection over joined traces | shared |
| `capacity_plan.py` | Disk check for a campaign before the first trace | shared |
| `tests/run_goodware_tests.py` | Host-runnable checks for the goodware runner | shared |
| `preflight.sh` | Pi 5 readiness check before every capture session | shared |
| `isolation-off.sh` | Network-rollback script, family-agnostic | shared |
| `regen_honeypot.sh` | Gonnacry honeypot regeneration | shared |
| `BENCH_OPERATIONS.md` | Gonnacry campaign operations guide | shared |
| `pico-em-capture/` | PicoScope 6404E Python driver (separate git repo, untracked here) | shared |
| `.pylib/` | Vendored `capstone`, `pyzipper`, `pycryptodomex` | shared |
| `pi5_setup/` | Pi 5 device-level compatibility gate | shared |
| `OG research.pdf`, `og_research.txt` | Reference paper (ACSAC '21) | shared |
| `first_run/`, `second_run/`, `third_run/`, `Mal/`, `GonnaCry/` | Historical run records (untouched) | legacy |

## Status

`Bashlite/` has captured traces. `Keysniffer/` is **code-complete but not yet run on
hardware**: Phases 6, 7, 10 are written and tested on the host, Phase 8 needed no work,
and Phases 1–5 plus 9 remain blocked on the Pi 5, the SD card, the scope and an isolated
analysis host.

Host-runnable checks for everything written so far:

```bash
python3 -I Keysniffer/tests/run_tests.py
python3 -I tests/run_goodware_tests.py
python3 -I em_analysis.py --self-test
python3 -I capacity_plan.py --self-test
(cd pico-em-capture && python3 -I tests/run_tests.py && python3 -I manifest_join.py --self-test)
```

## Benign traces and the join

`goodware_runner.py` writes one JSONL manifest per cell (append-only, resumable
with `--resume`). Each trace records `started_utc` … `finished_utc`, plus the
trigger edges. `started_utc` is taken after a lead-in of at least twice the
scope's pre-trigger interval, because the capture's window begins *before* the
GPIO edge; without the lead-in the capture would fall outside the trace's own
span and could not be joined. `--pre-trigger` and `--capture-duration` tell the
runner what the scope is doing.

```bash
python3 goodware_runner.py --task crypto --count 3000 --duration 2.5 \
    --capture-duration 2.5 --run-dir runs/crypto-01
```

`--task all` writes `<name>.<task>.jsonl` per task: one manifest per cell, so a
trace's workload is a property of the file it is in.

## Preprocessing

`em_analysis.py` implements the paper's §6 preprocessing: STFT with a 8192-sample
window and 4096-sample overlap, NICV per time-frequency bin, then the `epsilon`
frequency bands with the highest mean NICV over time. It streams one trace at a
time, so a 6 000-trace set does not need 240 GB of RAM.

```bash
python3 -I manifest_join.py --captures captures/run01/manifest.jsonl \
    --runs runs/crypto-01/manifest.jsonl --out runs/crypto-01/joined.jsonl
python3 -I em_analysis.py --joined runs/crypto-01/joined.jsonl --epsilon 20 \
    --out runs/crypto-01/features.npz
```

It refuses traces whose capture record says they are not measurements
(`trigger_real: false`, or the gate bypassed). Synthetic signals are used only
inside the self-test; they never reach a dataset directory.

## Campaign capacity

```bash
python3 -I capacity_plan.py --out D:/captures --traces 3000 --cells 2
```

2.5 s at 2 MHz is 5 000 000 float64 samples ≈ 38 MB per trace; the two required
Keysniffer cells alone are ~224 GB, ~246 GB with headroom. Check the destination
before the first trace: a disk that fills mid-campaign does not fail loudly.

## Hard invariants

- **Traces come only from physical silicon.** QEMU, VirtualBox, and REMnux never produce EM data; they are analysis and rehearsal only.
- **Windows is never a malware host.** Never run malware on the Windows host; never point samples at the public internet or real C2.
- **Isolation before malware.** Network isolation (VLAN or verified iptables) must exist before the first malware run on the Pi.
- **No clock tuning.** Do not overclock, underclock, or set `arm_freq` / `force_turbo`. Abort capture if `vcgencmd get_throttled` is not `0x0`.

Project files are in English; chat is in Vietnamese.
