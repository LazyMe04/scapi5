#!/usr/bin/env python3
"""Keysniffer manifest validator and dataset summary.

Reads the JSONL manifests written by `kisni_runner.py` and answers the questions
Phase 10 says must be answered *before* any model is trained:

  1. Is the 2x2 ablation complete? (module present/absent x typing busy/idle)
  2. Are `kisni-typing` and `typing-only` actually comparable — same injected
     keystroke sequence, same rate, same window length? If not, any classifier
     result is measuring the workload rather than the rootkit.
  3. Did every trace start from a fresh module instance?
  4. Did any trace fail, leak the module, or record nothing?
  5. Do the manifests describe one experiment at all — same module bytes,
     kernel, `codes=` mode, trigger, injector and timing? Two individually
     clean manifests can still be two different experiments.

It also refutes the trivially-invalid cases loudly, because a quiet "OK" on a
broken dataset is worse than no tool at all.

Usage::

    python3 -I keysni_analyze.py manifests/*.jsonl
    python3 -I keysni_analyze.py --self-test
    python3 -I keysni_analyze.py --json manifests/*.jsonl
"""

import argparse
import json
import sys
from collections import Counter, defaultdict

# A trace is usable only if the module lifecycle completed cleanly. Anything
# else is reported, not silently dropped: a run with 40 failures out of 50 is a
# finding about the setup, not noise to filter away.
GOOD_STATUS = "ok"
WINDOW_TOLERANCE_MS = 50  # scheduling jitter on a non-RT kernel


def load(paths):
    """Parse JSONL manifests. Returns (records, errors)."""
    records, errors = [], []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        errors.append(f"{path}:{lineno}: {exc}")
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    return records, errors


def split(records):
    headers = [r for r in records if r.get("type") == "header"]
    traces = [r for r in records if r.get("type") == "trace"]
    footers = [r for r in records if r.get("type") == "footer"]
    return headers, traces, footers


# Fields that define *which experiment* a trace belongs to. A manifest per cell
# means one dataset spans several headers; if any of these differ, the cells were
# not measured under the same conditions and combining them is an artefact.
HEADER_IDENTITY_FIELDS = (
    ("expected_hash", "expected module hash"),
    ("kernel_release", "kernel release"),
    ("codes", "codes parameter"),
    ("trigger", "trigger source"),
    ("gpio_pin", "GPIO pin"),
    ("rate", "keystroke rate"),
    ("duration_s", "trace duration"),
    ("injector", "injector"),
    ("schema", "manifest schema"),
    ("runner_version", "runner version"),
)
TRACE_IDENTITY_FIELDS = (
    ("module_sha256", "module hash"),
    ("kernel_release", "kernel release"),
)


def _identity_value(field, value):
    """Normalise a value so equivalent spellings compare equal (not artifact drift)."""
    if value is None:
        return None
    if field == "expected_hash":
        return str(value).strip().lower()
    if field in ("rate", "duration_s"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if isinstance(value, str):
        return value.strip()
    return value


def dataset_identity(headers, traces):
    """Return problems where the manifests describe more than one experiment.

    Every check above can pass on a dataset assembled from two builds, two
    kernels, or two trigger setups: each half is internally clean. These fields
    are not per-trace comparisons, so they have to be checked explicitly.
    """
    problems = []

    def check(fields, rows):
        for field, label in fields:
            seen = {_identity_value(field, r.get(field)) for r in rows
                    if r.get(field) is not None}
            if len(seen) > 1:
                shown = ", ".join(sorted(repr(v) for v in seen))
                problems.append(f"dataset mixes values for {label}: {shown}")

    check(HEADER_IDENTITY_FIELDS, headers)
    check(TRACE_IDENTITY_FIELDS, traces)

    # A run's expected hash is the pin; a trace that does not match any pin was
    # produced by a module this dataset does not describe.
    pinned = {_identity_value("expected_hash", h.get("expected_hash"))
              for h in headers if h.get("expected_hash") is not None}
    observed = {_identity_value("expected_hash", t.get("module_sha256"))
                for t in traces if t.get("module_sha256") is not None}
    unmatched = observed - pinned
    if pinned and unmatched:
        shown = ", ".join(sorted(unmatched))
        problems.append(
            f"trace module hash not pinned by any manifest header: {shown}")

    return problems


def analyse(traces, headers=None):
    """Return a dict of findings. Pure function, so it is testable."""
    out = {
        "total": len(traces),
        "by_mode": Counter(t["mode"] for t in traces if "mode" in t),
        "by_status": Counter(t.get("status", "missing") for t in traces),
        "problems": [],
        "warnings": [],
    }

    # ---- 0. is there a measurement here at all? ----
    # A dry-run manifest has the right shape and no data. Reporting it as clean
    # would be the worst outcome this tool can produce, because the shape checks
    # all pass.
    real = [t for t in traces if not t.get("dry_run")]
    out["measured"] = len(real)
    if traces and not real:
        out["problems"].append(
            "every trace is a dry run: no module was loaded and no keystrokes "
            "were injected. This dataset contains no measurement.")
        return out

    # ---- 1. ablation completeness ----
    expected = {"kisni-typing", "typing-only", "kisni-idle", "idle"}
    present = set(out["by_mode"])
    missing = expected - present
    if missing:
        out["problems"].append(
            "2x2 ablation incomplete: missing cell(s) " + ", ".join(sorted(missing)))

    # ---- 1b. is this one experiment? ----
    for problem in dataset_identity(headers or [], traces):
        out["problems"].append(problem)

    # ---- 2. comparability of the two typing cells ----
    # If the injected workload differs between the cell with the module and the
    # cell without, the classifier can separate the cells by workload alone.
    typing = [t for t in traces
              if t.get("mode") in ("kisni-typing", "typing-only")
              and t.get("status") == GOOD_STATUS]
    if typing:
        by_cell = defaultdict(list)
        for t in typing:
            by_cell[t["mode"]].append(t)

        if len(by_cell) == 2:
            hashes = {m: {t.get("keystroke_file_sha256") for t in v}
                      for m, v in by_cell.items()}
            all_hashes = set().union(*hashes.values())
            if None in all_hashes or len(all_hashes) > 1:
                out["problems"].append(
                    "typing cells used different keyfiles: " + repr(hashes))

            rates = {m: {t.get("keystroke_interval_ms") for t in v}
                     for m, v in by_cell.items()}
            if len(set().union(*rates.values())) > 1:
                out["problems"].append(
                    "typing cells used different key rates: " + repr(rates))

        windows = defaultdict(list)
        for t in typing:
            if t.get("window_ns"):
                windows[t["mode"]].append(t["window_ns"] / 1e6)
        if len(windows) == 2:
            spread = {m: (min(v), max(v)) for m, v in windows.items()}
            overall = [x for v in windows.values() for x in v]
            if overall and (max(overall) - min(overall)) > WINDOW_TOLERANCE_MS:
                out["warnings"].append(
                    f"window length spread {max(overall) - min(overall):.1f} ms "
                    f"exceeds {WINDOW_TOLERANCE_MS} ms: {spread}")

    # ---- 3. fresh module instance per trace ----
    # The debugfs buffer wraps at 16 KB and cannot be truncated, so a trace that
    # started with a non-empty buffer inherited another trace's state.
    for t in traces:
        if t.get("module_required") and not t.get("dry_run"):
            before = t.get("debugfs_bytes_before")
            if before not in (0, None):
                out["problems"].append(
                    f"trace {t.get('trace_index')}: debugfs not empty before load "
                    f"({before} bytes) - module was not reloaded fresh")

    # ---- 4. failures ----
    failed = [t for t in traces if t.get("status") != GOOD_STATUS]
    for t in failed:
        out["problems"].append(
            f"trace {t.get('trace_index')} ({t.get('mode')}): {t.get('status')}"
            + (" - " + "; ".join(t["notes"]) if t.get("notes") else ""))

    # ---- 4b. wrapped traces ----
    # A negative delta means the 16 KB debugfs buffer wrapped mid-trace. The
    # trace is valid, but its byte delta is smaller than the number of records
    # written, so it cannot go into a byte-delta distribution without a note.
    wrapped = [t for t in traces
               if isinstance(t.get("debugfs_delta"), int) and t["debugfs_delta"] < 0]
    out["wrapped"] = len(wrapped)
    if wrapped:
        out["warnings"].append(
            f"{len(wrapped)} trace(s) wrapped the 16 KB buffer; their byte deltas "
            f"are lower bounds, not measurements. Use the keystroke count for "
            f"those, or shorten the trace")

    # ---- 5. the signal itself ----
    # debugfs delta is what the rootkit recorded. A cell with the module loaded
    # and busy but a zero delta means the hook never fired.
    deltas = defaultdict(list)
    for t in traces:
        if t.get("debugfs_delta") is not None:
            deltas[t["mode"]].append(t["debugfs_delta"])
    out["debugfs_delta"] = {m: sorted(v) for m, v in deltas.items()}

    idle_delta = deltas.get("kisni-idle", [])
    # A negative delta is a wrap, not activity; it is reported separately in 4b.
    if idle_delta and any(d > 0 for d in idle_delta):
        out["warnings"].append(
            "kisni-idle recorded keystrokes; something other than the injector "
            "is typing, or a previous trace's buffer was not cleared")

    typing_delta = deltas.get("kisni-typing", [])
    if typing_delta and all(d == 0 for d in typing_delta):
        out["problems"].append(
            "kisni-typing recorded nothing: the module is not seeing the injected "
            "keys - check the VT is active (chvt 1) and the uinput device bound")

    return out


def render(result, stream=sys.stdout):
    w = stream.write
    w(f"traces: {result['total']}  (measured: {result.get('measured', '?')}, "
      f"dry run: {result['total'] - result.get('measured', 0)})\n")
    if result["by_mode"]:
        w("  by mode:   " + ", ".join(f"{k}={v}"
                                      for k, v in sorted(result["by_mode"].items())) + "\n")
    if result["by_status"]:
        w("  by status: " + ", ".join(f"{k}={v}"
                                      for k, v in sorted(result["by_status"].items())) + "\n")

    if result.get("debugfs_delta"):
        w("\ndebugfs bytes recorded per trace (Phase 10 per-cell distribution):\n")
        for mode, values in sorted(result["debugfs_delta"].items()):
            uniq = Counter(values)
            w(f"  {mode:<14} n={len(values):<3} "
              + " ".join(f"{d}x{c}" for d, c in sorted(uniq.items())) + "\n")

    if result["problems"]:
        w(f"\nPROBLEMS ({len(result['problems'])}) - do not train on this dataset:\n")
        for p in result["problems"]:
            w(f"  ! {p}\n")
    if result["warnings"]:
        w(f"\nwarnings ({len(result['warnings'])}):\n")
        for x in result["warnings"]:
            w(f"  ? {x}\n")
    if not result["problems"] and not result["warnings"]:
        w("\nOK: ablation complete, cells comparable, every trace clean.\n")
    return 1 if result["problems"] else 0


# -----------------------------------------------------------------------------
def self_test():
    failures, checks = [], [0]

    def expect(cond, label):
        checks[0] += 1
        if not cond:
            failures.append(label)

    def trace(mode, status="ok", delta=None, before=0, idx=0, hash_="aaa",
              interval=50, window_ms=2500.0, dry=False,
              module_hash="a" * 64, kernel="6.18.50+rpt-rpi-2712"):
        # Default delta models reality: only a loaded module that also sees
        # keystrokes records anything. `idle` has no module at all (None),
        # `kisni-idle` has the module but nothing is typed (0).
        if delta is None:
            delta = 512 if mode == "kisni-typing" else 0
            if mode == "idle":
                delta = None
        return {
            "type": "trace", "trace_index": idx, "mode": mode, "status": status,
            "debugfs_delta": delta, "debugfs_bytes_before": before,
            "keystroke_file_sha256": hash_, "keystroke_interval_ms": interval,
            "window_ns": int(window_ms * 1e6), "dry_run": dry,
            "module_required": mode.startswith("kisni"),
            "module_sha256": module_hash, "kernel_release": kernel,
            "notes": [],
        }

    def complete(**kw):
        return [trace("kisni-typing", idx=0, **kw), trace("typing-only", idx=1, **kw),
                trace("kisni-idle", idx=2, **kw), trace("idle", idx=3, **kw)]

    def header(**kw):
        h = {"type": "header", "schema": 1, "runner_version": "1.0.0",
             "expected_hash": "a" * 64,
             "kernel_release": "6.18.50+rpt-rpi-2712",
             "codes": 1, "trigger": "gpio17", "gpio_pin": 17,
             "rate": 20.0, "duration_s": 2.5, "injector": "uinput"}
        h.update(kw)
        return h

    # 1. a clean, complete dataset produces no problems
    r = analyse(complete(), headers=[header()])
    expect(not r["problems"], f"clean dataset flagged: {r['problems']}")
    expect(not r["warnings"], f"clean dataset warned: {r['warnings']}")

    # 2. a missing cell is a problem, not a silent pass
    r = analyse([trace("kisni-typing")])
    expect(any("ablation incomplete" in p for p in r["problems"]),
           "missing cells not flagged")

    # 3. different keyfiles between the two typing cells is fatal
    r = analyse([trace("kisni-typing", hash_="aaa", idx=0),
                 trace("typing-only", hash_="bbb", idx=1)])
    expect(any("different keyfiles" in p for p in r["problems"]),
           "keyfile drift not flagged")

    # 4. different rates between the typing cells is fatal
    r = analyse([trace("kisni-typing", interval=50, idx=0),
                 trace("typing-only", interval=25, idx=1)])
    expect(any("different key rates" in p for p in r["problems"]),
           "rate drift not flagged")

    # 5. window length drift is a warning, not a hard failure
    r = analyse([trace("kisni-typing", window_ms=2500, idx=0),
                 trace("typing-only", window_ms=3000, idx=1)])
    expect(any("window length spread" in x for x in r["warnings"]),
           "window drift not warned")

    # 6. a non-empty debugfs buffer before load invalidates the trace
    r = analyse([trace("kisni-typing", before=4096)])
    expect(any("not reloaded fresh" in p for p in r["problems"]),
           "reused module buffer not flagged")

    # 7. failed traces are reported with their notes
    t = trace("kisni-typing", status="module-load-failed")
    t["notes"] = ["insmod rc=1: Invalid module format"]
    r = analyse([t])
    expect(any("module-load-failed" in p and "Invalid module format" in p
               for p in r["problems"]), "failure notes not surfaced")

    # 8. a module loaded and busy but recording nothing is the loudest failure
    r = analyse([trace("kisni-typing", delta=0, idx=0),
                 trace("typing-only", delta=0, idx=1)])
    expect(any("recorded nothing" in p for p in r["problems"]),
           "silent module not flagged")

    # 9. activity during the idle cell contradicts the controlled workload
    r = analyse([trace("kisni-idle", delta=100)])
    expect(any("kisni-idle recorded keystrokes" in x for x in r["warnings"]),
           "unexpected idle activity not warned")

    # 10. dry-run traces do not trigger the fresh-module check
    r = analyse([trace("kisni-typing", dry=True, before=None, delta=None)])
    expect(not any("not reloaded fresh" in p for p in r["problems"]),
           "dry run flagged for buffer state")

    # 11. an all-dry-run dataset is rejected outright, not called clean
    r = analyse([trace("kisni-typing", dry=True, idx=0),
                 trace("typing-only", dry=True, idx=1),
                 trace("kisni-idle", dry=True, idx=2),
                 trace("idle", dry=True, idx=3)])
    expect(any("no measurement" in p for p in r["problems"]),
           "dry-run-only dataset reported clean")
    expect(r["measured"] == 0, "measured count wrong for dry run")

    # 12. a mixed dataset is accepted, with only the real traces measured
    r = analyse([trace("kisni-typing", idx=0), trace("typing-only", dry=True, idx=1),
                 trace("kisni-idle", idx=2), trace("idle", idx=3)])
    expect(r["measured"] == 3, f"measured was {r['measured']}, expected 3")
    expect(not any("no measurement" in p for p in r["problems"]),
           "mixed dataset rejected")

    # 13. a wrapped trace is valid, warned about, and not counted as activity
    r = analyse([trace("kisni-typing", delta=-800, idx=0),
                 trace("typing-only", delta=512, idx=1)])
    expect(r["wrapped"] == 1, f"wrapped count was {r.get('wrapped')}")
    expect(not any("recorded nothing" in p for p in r["problems"]),
           "a wrap was treated as no activity")
    expect(any("wrapped the 16 KB buffer" in x for x in r["warnings"]),
           "wrap not warned about")

    # 14. a negative delta in the idle cell is a wrap, not failed containment
    r = analyse([trace("kisni-idle", delta=-800)])
    expect(not any("idle recorded keystrokes" in x for x in r["warnings"]),
           "idle wrap misreported as keystrokes")

    # 15. two headers pinning different module hashes: each run was clean, the
    # dataset is still two experiments.
    r = analyse(complete(), headers=[header(), header(expected_hash="b" * 64)])
    expect(any("expected module hash" in p for p in r["problems"]),
           "module hash drift across manifests not flagged")

    # 16. a different `codes=` mode changes the record width, so byte deltas are
    # not comparable even when both runs recorded correctly.
    r = analyse(complete(), headers=[header(), header(codes=2)])
    expect(any("codes parameter" in p for p in r["problems"]),
           "codes drift not flagged")

    # 17. a software-triggered cell cannot join a GPIO-triggered dataset: the
    # scope has no edge to align it to.
    r = analyse(complete(), headers=[header(),
                                     header(trigger="software", gpio_pin=None)])
    expect(any("trigger source" in p for p in r["problems"]),
           "trigger drift not flagged")

    # 18. equivalent spellings and per-run flags are not dataset drift
    r = analyse(complete(), headers=[header(),
                                     header(expected_hash="A" * 64,
                                            allow_taint=True)])
    expect(not any("dataset mixes" in p for p in r["problems"]),
           f"equivalent headers flagged: {r['problems']}")
    expect(not any("not pinned" in p for p in r["problems"]),
           f"uppercase hash treated as a different module: {r['problems']}")

    # 19. per-trace module hash drift is caught even with a single header
    r = analyse([trace("kisni-typing", idx=0),
                 trace("typing-only", idx=1, module_hash="b" * 64)],
                headers=[header()])
    expect(any("values for module hash" in p for p in r["problems"]),
           "per-trace module hash drift not flagged")

    # 20. traces from two kernels cannot share a dataset
    r = analyse([trace("kisni-typing", idx=0),
                 trace("typing-only", idx=1, kernel="6.1.0-v8+")],
                headers=[header()])
    expect(any("values for kernel release" in p for p in r["problems"]),
           "kernel drift across traces not flagged")

    if failures:
        print(f"SELF-TEST FAILED ({len(failures)} of {checks[0]})")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"SELF-TEST PASSED ({checks[0]} checks)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Validate and summarise kisni manifests.")
    p.add_argument("manifests", nargs="*", help="JSONL manifest files")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.manifests:
        p.error("no manifests given (or use --self-test)")

    records, errors = load(args.manifests)
    if errors:
        for e in errors:
            print(f"[parse] {e}", file=sys.stderr)
    headers, traces, _ = split(records)
    if not traces:
        print("no trace records found", file=sys.stderr)
        return 2

    result = analyse(traces, headers=headers)
    result["parse_errors"] = errors
    result["headers"] = len(headers)

    if args.json:
        payload = {k: (dict(v) if isinstance(v, Counter)
                       or isinstance(v, defaultdict) else v)
                   for k, v in result.items()}
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 1 if result["problems"] else 0

    print(f"manifests: {', '.join(args.manifests)}  (headers: {len(headers)})\n")
    return render(result)


if __name__ == "__main__":
    sys.exit(main())
