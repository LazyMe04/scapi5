# Phase 4 — static review checklist (not yet executed)

Status: **blocked.** This file is the checklist and the review procedure, ready to be
completed in one pass on the isolated analysis host once Phase 2 has pinned the source.
It is deliberately empty of conclusions: writing them before reading the pinned revision
would be a fabricated review, and this file is also the lab's record that a keylogger was
loaded on purpose.

## Blocker

The review needs the exact source that will be compiled in Phase 3. That means:

- the commit hash from `git rev-parse HEAD` in `jarun/spy`
- `sha256sum spy.c Makefile`

Both go in `KEYSNIFFER_PROVENANCE.md`. Reviewing a floating branch is worthless: a source
change between review and build silently changes the artifact under measurement.

## Procedure

```bash
grep -n "module_param\|debugfs_create\|register_keyboard_notifier\|module_init\|module_exit" spy.c
```

Record the line numbers, then walk the checklist below against those specific lines.

## Checklist

| # | Check | Why it matters | Verdict | Line(s) |
|---|---|---|---|---|
| 1 | `module_init` is error-safe: on failure it removes the debugfs dir and returns an error, leaving no half-registered notifier | A partially initialised module that returns 0 leaves a registered callback with no log target | | |
| 2 | `module_exit` unregisters the notifier **before** removing the directory | The reverse order gives the callback a dangling dentry on unload | | |
| 3 | The callback returns without dereferencing anything that can be NULL | The callback runs in interrupt context; a fault there panics the machine, not a process | | |
| 4 | The buffer write cannot exceed `BUF_LEN` (upstream bounds-checks and wraps) | An overflow is memory corruption in kernel space | | |
| 5 | No networking, no file writes outside debugfs, no process interaction | Anything beyond a debugfs log changes what the trace measures | | |
| 6 | `MODULE_LICENSE("GPL v2")` present | `EXPORT_SYMBOL_GPL` symbols are unavailable otherwise | | |
| 7 | Nothing was added inside `spy_cb()` | Instrumenting the measured code path changes the artifact. Mechanical API adaptations only, each in `PATCHES.md` | | |
| 8 | The `codes` parameter is read once at load, not per event | Per-event parsing would put variable work inside the measured window | | |

## What to record

For each row: the verdict, the line numbers it was checked against, and — for anything
that is not a clean pass — what the code actually does and what the consequence is for
the measurement. "Looks fine" is not a finding.

The finished file must also state, in its own words:

- the pinned commit and source hashes
- that `kisni` is a keylogger, loaded deliberately, on a lab device with no user data
- which of the six checklist items are *not* satisfied by the pinned revision, and whether
  that is acceptable

## Gate

**Phase 4 passes when this file has a verdict for all eight rows and no unexplained
behaviour remains.** Loading before that is not permitted.
