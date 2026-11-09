# bench — EM IoT malware lab tooling

This repository holds the tooling for the electromagnetic side-channel lab:
capture hardware drivers, Pi-side runners, C2 rehearsal servers, isolation
scripts, and static-analysis utilities for malware samples.

## Layout

| Area | Contents | Kind |
|---|---|---|
| `Bashlite/` | Bashlite project: runner, C2, runbooks, static-analysis tools, staged sample | project |
| `Keysniffer/` | Keysniffer project: plan document only (Phase 0 gate not yet passed) | project |
| `goodware_runner.py` | Benign workload runner (GPIO 17 trigger, GPIO/ACT LED) shared by all families | shared |
| `preflight.sh` | Pi 5 readiness check before every capture session | shared |
| `isolation-off.sh` | Network-rollback script, family-agnostic | shared |
| `regen_honeypot.sh` | Gonnacry honeypot regeneration | shared |
| `BENCH_OPERATIONS.md` | Gonnacry campaign operations guide | shared |
| `pico-em-capture/` | PicoScope 6404E Python driver (separate git repo, untracked here) | shared |
| `.pylib/` | Vendored `capstone`, `pyzipper`, `pycryptodomex` | shared |
| `pi5_setup/` | Pi 5 device-level compatibility gate | shared |
| `OG research.pdf`, `og_research.txt` | Reference paper (ACSAC '21) | shared |
| `first_run/`, `second_run/`, `third_run/`, `Mal/`, `GonnaCry/` | Historical run records (untouched) | legacy |

## Hard invariants

- **Traces come only from physical silicon.** QEMU, VirtualBox, and REMnux never produce EM data; they are analysis and rehearsal only.
- **Windows is never a malware host.** Never run malware on the Windows host; never point samples at the public internet or real C2.
- **Isolation before malware.** Network isolation (VLAN or verified iptables) must exist before the first malware run on the Pi.
- **No clock tuning.** Do not overclock, underclock, or set `arm_freq` / `force_turbo`. Abort capture if `vcgencmd get_throttled` is not `0x0`.

Project files are in English; chat is in Vietnamese.
