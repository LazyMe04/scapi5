#!/usr/bin/env python3
"""
Estimate whether this machine can hold a capture campaign.

The campaign size was decided before any trace existed: the plan asks for
3 000 traces per cell of a 2.5 s window at 2 MHz, which is 5 000 000 samples
per trace. Written as float64 that is 40 MB per trace, and the required cells
alone are ~240 GB. A disk that fills at trace 4 100 of 6 000 does not fail
loudly - the last traces are simply short or absent - so the arithmetic is
checked before the first trace rather than during the campaign.

This tool measures the destination and reports; it does not create files and
does not need the scope.

Usage::

    python -I capacity_plan.py --out D:\\captures\\run01 \\
        --traces 3000 --cells 2 --duration 2.5 --rate 2000000

    python -I capacity_plan.py --self-test
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

BYTES_PER_SAMPLE = 8          # float64, what capture.py saves
MANIFEST_LINE_BYTES = 900     # one JSONL trace record, measured from the code
FILESYSTEM_HEADROOM = 1.10    # metadata, allocation slack, OS noise

EXIT_OK = 0
EXIT_PROBLEM = 1


def trace_bytes(duration_s, sampling_hz, bytes_per_sample=BYTES_PER_SAMPLE):
    """Bytes one .npy trace occupies, including the header and manifest line."""
    samples = int(round(float(duration_s) * float(sampling_hz)))
    raw = samples * bytes_per_sample
    # .npy header is ~128 bytes and rounds up to a 64-byte boundary; 512 is a
    # safe allowance rather than a precise one, which is the right side to err.
    return samples, raw, raw + 512 + MANIFEST_LINE_BYTES


def plan(duration_s, sampling_hz, trace_count, cells=1,
         bytes_per_sample=BYTES_PER_SAMPLE, free_bytes=None,
         headroom=FILESYSTEM_HEADROOM):
    """
    Return the numbers a campaign decision needs.

    `cells` is the number of separately captured cells (e.g. kisni-typing and
    typing-only). Each cell is a full trace_count; that is how the plan is
    written and it is the usual mistake to estimate for one cell.
    """
    if trace_count < 0 or cells < 1:
        raise ValueError("trace_count must be >= 0 and cells >= 1")
    samples, raw, per_trace = trace_bytes(duration_s, sampling_hz,
                                          bytes_per_sample)
    total_traces = int(trace_count) * int(cells)
    total = per_trace * total_traces
    required = int(total * headroom)
    result = {
        "samples_per_trace": samples,
        "bytes_per_trace": per_trace,
        "traces_per_cell": int(trace_count),
        "cells": int(cells),
        "total_traces": total_traces,
        "total_bytes": int(total),
        "required_bytes": required,
        "free_bytes": None if free_bytes is None else int(free_bytes),
    }
    if free_bytes is not None:
        result["fits"] = required <= int(free_bytes)
        result["shortfall_bytes"] = max(0, required - int(free_bytes))
        result["max_traces"] = int(free_bytes // per_trace) if per_trace else 0
    return result


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} TB"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check that a capture campaign fits the destination.")
    parser.add_argument("--out", help="output directory the campaign will use")
    parser.add_argument("--traces", type=int, default=3000,
                        help="traces per cell (default 3000, the paper's count)")
    parser.add_argument("--cells", type=int, default=1,
                        help="number of separately captured cells (default 1)")
    parser.add_argument("--duration", type=float, default=2.5,
                        help="capture window in seconds (default 2.5)")
    parser.add_argument("--rate", type=float, default=2_000_000,
                        help="sampling rate in Hz (default 2000000)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.out:
        parser.error("--out is required (or use --self-test)")

    target = os.path.abspath(args.out)
    probe = target
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if not os.path.exists(probe):
        print(f"[ERROR] no existing parent directory for {target}",
              file=sys.stderr)
        return EXIT_PROBLEM

    usage = shutil.disk_usage(probe)
    result = plan(args.duration, args.rate, args.traces, args.cells,
                  free_bytes=usage.free)
    result["probed_path"] = probe
    result["target_path"] = target

    if args.json:
        import json
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"target     : {target}")
        print(f"probed at  : {probe}")
        print(f"per trace  : {result['samples_per_trace']:,} samples, "
              f"{human(result['bytes_per_trace'])}")
        print(f"campaign   : {result['cells']} cell(s) x "
              f"{result['traces_per_cell']:,} = "
              f"{result['total_traces']:,} traces")
        print(f"needs      : {human(result['total_bytes'])} "
              f"(+{int((FILESYSTEM_HEADROOM - 1) * 100)}% headroom -> "
              f"{human(result['required_bytes'])})")
        print(f"free       : {human(usage.free)}")
        if result["fits"]:
            print(f"\nOK: the campaign fits, with room for "
                  f"{result['max_traces'] - result['total_traces']:,} more traces.")
        else:
            print(f"\nPROBLEM: short by {human(result['shortfall_bytes'])}.")
            print(f"  at {human(result['bytes_per_trace'])}/trace this disk "
                  f"holds {result['max_traces']:,} traces.")
            print("  Options: lower --duration, write each cell to its own "
                  "volume, or move completed cells to archive storage.")

    return EXIT_OK if result["fits"] else EXIT_PROBLEM


def self_test():
    failures, checks = [], [0]

    def expect(cond, label):
        checks[0] += 1
        if not cond:
            failures.append(label)

    samples, raw, per_trace = trace_bytes(2.5, 2_000_000)
    expect(samples == 5_000_000, f"2.5 s at 2 MHz is 5e6 samples: {samples}")
    expect(raw == 40_000_000, f"float64 trace is 40 MB: {raw}")
    expect(per_trace > raw, "the per-trace figure includes overhead")

    r = plan(2.5, 2_000_000, 3000, cells=2, free_bytes=10**12)
    expect(r["total_traces"] == 6000, f"two cells double the count: {r['total_traces']}")
    expect(r["total_bytes"] == 6000 * per_trace, "the total is per-trace x count")
    expect(r["fits"], "1 TB holds a 240 GB campaign")

    tight = plan(2.5, 2_000_000, 3000, cells=2, free_bytes=250 * 10**9)
    expect(not tight["fits"], "250 GB does not hold 240 GB plus headroom")
    expect(tight["shortfall_bytes"] == r["required_bytes"] - 250 * 10**9,
           "the shortfall is exact")

    zero = plan(2.5, 2_000_000, 0, cells=1, free_bytes=0)
    expect(zero["fits"], "an empty campaign fits anywhere")

    # Headroom is applied, not implied: exactly-sized free space is a problem.
    exact = plan(2.5, 2_000_000, 1, cells=1, free_bytes=per_trace)
    expect(not exact["fits"], "exact free space is refused without headroom")

    try:
        plan(2.5, 2_000_000, 10, cells=0)
        expect(False, "cells=0 is rejected")
    except ValueError:
        expect(True, "cells=0 is rejected")

    expect(human(1024) == "1.0 KB", f"human(1024): {human(1024)}")
    expect(human(40_000_000) == "38.1 MB", f"human(40e6): {human(40_000_000)}")

    print(f"self-test: {checks[0]} checks", file=sys.stderr)
    if failures:
        for f in failures:
            print(f"  FAIL: {f}", file=sys.stderr)
        return 1
    print("self-test: all checks passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
