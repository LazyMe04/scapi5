# Bashlite

Bashlite project area — EM side-channel capture tooling for the Bashlite/Gafgyt
32-bit ARM sample (`349d2476…b777`).

## Subdirectories

| Directory | Contents |
|---|---|
| `docs/` | `BASHLITE_32BIT_PLAN.md` (full plan), `BASHLITE_PI_DIRECT.md` (Pi 5 runbook), `BASHLITE_VM_TEST.md` (VM rehearsal), `PI5_Bashlite_HuongDan.docx` (Vietnamese operator guide) |
| `runner/` | `bashlite_runner.py` — time-bounded executor with trigger, containment gate, privilege drop, leftover sweep, manifest |
| `c2/` | `c2_server.py` — spoofed C2 (observe / serve modes), `c2_script.json` — command timeline |
| `analysis/` | `elfdump.py`, `func_dump.py`, `pool_check.py`, `simparse.py`, `fakebot.py`, plus `main.asm`, `initconn.asm` disassembly |
| `analysis_notes/` | `STATIC_TRIAGE_349d2476.md` — static triage of the staged sample |
| `runs/` | `discover-run.jsonl`, `run01.jsonl` — recorded C2 logs |
| `staging/` | `349d2476…b777.zip` — the staged, encrypted sample payload |
| `docgen/` | `build_pi5_guide.py` — generates `docs/PI5_Bashlite_HuongDan.docx` |

## Entry points

- Straight Pi 5 run: `Bashlite/docs/BASHLITE_PI_DIRECT.md`
- Full end-to-end plan: `Bashlite/docs/BASHLITE_32BIT_PLAN.md`
- VM rehearsal: `Bashlite/docs/BASHLITE_VM_TEST.md`

## Rules

- The sample is never rebuilt and never committed as a plaintext ELF. The identity of
  the sample is its SHA-256; a rebuild replaces the author's toolchain and the sample
  stops being in-the-wild.
- `Bashlite/isolation-on.sh` is Bashlite-specific (hardcodes this sample's C2 address
  and port). `isolation-off.sh` at the repo root is family-agnostic and works for any
  family's run.
- Static-analysis scripts (`analysis/*.py`) are read-only: the zip is decrypted in
  memory, nothing is ever written to disk as an ELF.
