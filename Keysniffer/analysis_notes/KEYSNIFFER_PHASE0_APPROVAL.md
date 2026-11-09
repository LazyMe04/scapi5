# Keysniffer — Phase 0 approval record and deviation register

**Status:** Phase 0 PASSED on 2026-11-09. This file is the written approval the plan
requires before any Phase 1 action. It is also the deviation-register entry that must
exist **before the first trace**.

---

## 1. Approval record

The four questions in `KEYSNIFFER_PLAN.md` §0.1, answered by the operator on 2026-11-09:

| # | Question | Answer |
|---|---|---|
| 1 | Supervisor approved extending scope to this family? | **Yes — written approval exists.** |
| 2 | Same-source rebuild on aarch64 acceptable, given §0's cost statement? | **Yes.** The resulting class is a same-source re-instantiation, not a replication of the paper's `kisni` traces. |
| 3 | Class reported as "rootkit (keysniffer, rebuilt)" rather than a replication? | **Yes — that exact label is used in manifests, dataset metadata and the thesis.** |
| 4 | Deviation register entry written **before** the first trace? | **Yes — this file, dated before Phase 1 begins.** |

Because all four are affirmative, the plan proceeds. `maK_It` remains excluded regardless.

---

## 2. Deviation register entry (required before the first trace)

Any dataset produced from this family must carry these statements. They are not optional
caveats; omitting any one of them makes the result misrepresent the work.

| # | Paper | This project | Consequence |
|---|---|---|---|
| D1 | Prebuilt `kisni-4.19.57-v7+.ko`, kernel 4.19, ARMv7 | Out-of-tree build of published GPL-2.0 source for the running aarch64 kernel | The trace describes 6.18 input/VT code, not 4.19's. It is a same-source re-instantiation on new hardware, **not** a replication of the paper's `kisni` traces. |
| D2 | PicoScope 6407 | PicoScope 6404E | Different bandwidth and sample-memory envelope. Record the model and the achieved timebase with every manifest. |
| D3 | Two rootkit families (`maK_It` train / `kisni` test) | One rootkit family (`kisni`) | The paper's novelty split cannot be reproduced. Use an ordinary train/test split on `kisni` and state that the class is weaker than the paper's two-family class. |
| D4 | Physical console typing | `uinput` synthetic keyboard | Removes the USB host-controller interrupt workload a physical keyboard adds. The typing workload is reproducible but not hardware-identical. |
| D5 | — | Source identification of the paper's sample as `jarun/spy` is **inferred**, not proven | If the paper's `.ko` is obtained, compare `modinfo` `description`/`author`/`srcversion`. Until then, cite the identification as inferred. |

---

## 3. Supersession of historical documents

`third_run/weekly_report_2026-09-27.md` §5.3 ("Two of the six malware classes are
architecturally excluded") and the "Malware classes: Six → Four" row of its deviation table
record the earlier decision to drop both kernel-module classes. **That report is not edited**,
per the plan. This dated entry supersedes it for the scope question only:

| Former statement (2026-09-27) | Now (2026-11-09) |
|---|---|
| "These two classes are permanently excluded" | `keysniffer` (`kisni`) is in scope, conditional on the rebuild argument in `KEYSNIFFER_PLAN.md` §0 and this approval. `maK_It` is still excluded. |
| Malware classes: six → four | six → **five** (rootkit class represented by `kisni` alone) |
| Reason: cannot load 32-bit kernel modules on 64-bit | Still true for the *prebuilt* module. It does not follow that a module cannot be *built* for this kernel; that is what §0 of the plan establishes. |

`maK_It` exclusion rationale, unchanged: its source is not published by the same route, and it
adds a hidden-module, packet-sniffer and reverse-shell component not covered by the rebuild
argument.

---

## 4. What the approval does not authorise

- Loading the paper's prebuilt `.ko`. It is foreign-arch and foreign-kernel; `insmod`
  will reject it and forcing it is forbidden.
- `maK_It`, in any form.
- Signing with `insmod --force`, or disabling module signature enforcement.
- Any edit inside `spy_cb()`, or any printk/counter/delay added to the measured code path.
- Running any Phase 1+ step before Phase 1's image and recovery path exist.
