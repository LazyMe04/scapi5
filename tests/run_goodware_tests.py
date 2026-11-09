#!/usr/bin/env python3
"""
Host-runnable checks for the shared goodware runner.

Nothing here needs a Pi, a GPIO pin or a scope. The trigger is a fake that
records calls; `vcgencmd` is stubbed. What is tested is the part that decides
what the manifest says, because that manifest is the only provenance a benign
trace will ever have:

  * the throttle gate refuses a non-zero or unreadable mask
  * a trace record carries the wall-clock bounds the join needs
  * `started_utc` precedes `trigger_on_utc` by at least the pre-trigger
    interval, so a capture that starts before the edge still falls inside
  * resume continues at max(trace_index)+1 and a non-empty manifest is
    refused without it
  * a workload failure is recorded, not swallowed

Run::

    python -I tests/run_goodware_tests.py

Exit code 0 means every check passed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# The join lives in the nested capture repo; reuse its UTC parser rather than
# duplicating the format handling.
JOIN_DIR = os.path.join(ROOT, "pico-em-capture")
if JOIN_DIR not in sys.path:
    sys.path.insert(0, JOIN_DIR)

import goodware_runner as gw  # noqa: E402
from manifest_join import parse_utc  # noqa: E402

FAILURES: list[str] = []
CHECKS = [0]


def check(cond, label):
    CHECKS[0] += 1
    if not cond:
        FAILURES.append(label)
        print(f"  [FAIL] {label}")
    return bool(cond)


def eq(actual, expected, label):
    if actual != expected:
        label = f"{label} (got {actual!r}, wanted {expected!r})"
    return check(actual == expected, label)


def raises(exc_type, fn, label, contains=None):
    try:
        fn()
    except exc_type as exc:
        if contains is not None and contains not in str(exc):
            return check(False, f"{label} (message lacked {contains!r}: {exc})")
        return check(True, label)
    except Exception as exc:  # noqa: BLE001 - wrong type is a failure
        return check(False, f"{label} (raised {type(exc).__name__}: {exc})")
    return check(False, f"{label} (did not raise)")


class FakeTrigger:
    """Stands in for HardwareTrigger: records edges, sleeps for nothing."""

    def __init__(self):
        self.dry_run = True
        self.use_act_led = False
        self.pin = 17
        self.act_led_brightness_path = "/sys/class/leds/ACT/brightness"
        self.events = []

    def on(self):
        self.events.append("on")

    def off(self):
        self.events.append("off")

    def cleanup(self):
        pass


def trace_records(path):
    with open(path, encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    return [r for r in records if r.get("type", "trace") == "trace"]


# --------------------------------------------------------------------------- #
# 1. Throttle gate
# --------------------------------------------------------------------------- #
def test_throttle():
    print("[1] Throttle gate")

    eq(gw.throttle_state("throttled=0x0"), [0], "a clean mask parses")
    eq(gw.throttle_state("throttled=0x5000"), [0x5000], "a fault mask parses")
    eq(gw.throttle_state(""), [], "an empty response has no values")
    eq(gw.throttle_state("nonsense"), [], "unparseable text has no values")

    gw.assert_not_throttled("throttled=0x0", "before the session")

    raises(ValueError, lambda: gw.assert_not_throttled("throttled=0x5000", "now"),
           "under-voltage is refused", contains="throttled")
    raises(ValueError, lambda: gw.assert_not_throttled("throttled=0x0bad", "now"),
           "a non-zero mask is refused", contains="throttled")
    raises(ValueError, lambda: gw.assert_not_throttled("", "now"),
           "an unreadable response is refused, not treated as a pass",
           contains="cannot read")
    # A zero followed by other text still passes; a zero substring inside a
    # non-zero value must not.
    gw.assert_not_throttled("throttled=0x0 (ok)", "now")
    raises(ValueError, lambda: gw.assert_not_throttled("throttled=0x0001", "now"),
           "trailing digits are part of the value")


# --------------------------------------------------------------------------- #
# 2. Trace record shape
# --------------------------------------------------------------------------- #
def test_record_shape():
    print("[2] Trace record shape")

    trigger = FakeTrigger()
    record = gw.run_trace(0, "crypto", 0.01, trigger, lead_in_s=0.0)

    required = [
        "type", "trace_index", "mode", "status",
        "started_utc", "trigger_on_utc", "trigger_off_utc", "finished_utc",
        "wall_s", "result", "dry_run", "notes", "lead_in_s",
    ]
    for key in required:
        check(key in record, f"trace record carries {key}")

    eq(record["type"], "trace", "the record is a trace line")
    eq(record["mode"], "goodware-crypto", "the mode names the workload")
    eq(record["status"], "ok", "a completed workload is ok")
    eq(trigger.events, ["on", "off"], "the trigger brackets the workload")

    # Parsing every stamp is what makes the record usable by the join.
    for key in ("started_utc", "trigger_on_utc", "trigger_off_utc", "finished_utc"):
        check(parse_utc(record[key]) is not None, f"{key} is a parseable UTC stamp")

    start = parse_utc(record["started_utc"])
    on = parse_utc(record["trigger_on_utc"])
    off = parse_utc(record["trigger_off_utc"])
    end = parse_utc(record["finished_utc"])
    check(start <= on <= off <= end,
          f"the bounds are ordered: {record['started_utc']} .. {record['finished_utc']}")

    # The whole reason for the lead-in: the scope's pre-trigger samples put the
    # capture's window before the GPIO edge.
    led = gw.run_trace(1, "idle", 0.001, FakeTrigger(), lead_in_s=0.02)
    gap_s = (parse_utc(led["trigger_on_utc"]) - parse_utc(led["started_utc"])).total_seconds()
    check(gap_s >= 0.02, f"the lead-in precedes the edge by >= 0.02 s: {gap_s:.4f}")


# --------------------------------------------------------------------------- #
# 3. Workload failure
# --------------------------------------------------------------------------- #
def test_failure_is_recorded():
    print("[3] Workload failure is recorded")

    trigger = FakeTrigger()
    saved = gw.WORKLOADS["keyboard"]

    def broken(duration=1.5):
        raise RuntimeError("keysynth not found")

    gw.WORKLOADS["keyboard"] = broken
    try:
        record = gw.run_trace(7, "keyboard", 0.01, trigger, lead_in_s=0.0)
    finally:
        gw.WORKLOADS["keyboard"] = saved

    eq(record["status"], "workload-failed", "a failed workload is labelled")
    check(record["notes"] and "keysynth" in record["notes"][0],
          f"the failure reason is kept: {record['notes']}")
    eq(trigger.events, ["on", "off"],
       "the trigger is still released when the workload fails")
    check(record["finished_utc"] is not None,
          "a failed trace still has an end bound")


# --------------------------------------------------------------------------- #
# 4. Manifest writing and resume
# --------------------------------------------------------------------------- #
def test_manifest_and_resume():
    print("[4] Manifest writing and resume")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "manifest.jsonl")

        saved_run = gw.run_trace
        gw.run_trace = lambda i, task, dur, trig, lead_in_s=0.05: {
            "type": "trace", "trace_index": i, "mode": f"goodware-{task}",
            "status": "ok", "started_utc": "2026-01-01T12:00:00.000Z",
            "trigger_on_utc": "2026-01-01T12:00:00.100Z",
            "trigger_off_utc": "2026-01-01T12:00:02.600Z",
            "finished_utc": "2026-01-01T12:00:02.600Z",
            "wall_s": 2.5, "result": 1, "dry_run": True, "notes": [],
            "lead_in_s": 0.1,
        }
        try:
            ok = gw.run_benchmark("idle", 2, 0.001, FakeTrigger(), cooldown=0,
                                  manifest_path=path, skip_throttle_check=True)
        finally:
            gw.run_trace = saved_run

        check(ok, "a clean run reports success")
        traces = trace_records(path)
        eq(len(traces), 2, "two traces were written")
        eq([t["trace_index"] for t in traces], [0, 1],
           "trace indices start at 0")

        with open(path, encoding="utf-8") as fh:
            types = [json.loads(line)["type"] for line in fh if line.strip()]
        eq(types[0], "header", "the first line is a header")
        eq(types[-1], "footer", "the last line is a footer")

        # Resume: continues after the existing traces.
        saved_run = gw.run_trace
        gw.run_trace = lambda i, task, dur, trig, lead_in_s=0.05: {
            "type": "trace", "trace_index": i, "mode": f"goodware-{task}",
            "status": "ok", "started_utc": "2026-01-01T12:00:10.000Z",
            "trigger_on_utc": "2026-01-01T12:00:10.100Z",
            "trigger_off_utc": "2026-01-01T12:00:12.600Z",
            "finished_utc": "2026-01-01T12:00:12.600Z",
            "wall_s": 2.5, "result": 1, "dry_run": True, "notes": [],
            "lead_in_s": 0.1,
        }
        try:
            gw.run_benchmark("idle", 1, 0.001, FakeTrigger(), cooldown=0,
                             manifest_path=path, resume=True,
                             skip_throttle_check=True)
        finally:
            gw.run_trace = saved_run

        eq([t["trace_index"] for t in trace_records(path)], [0, 1, 2],
           "a resumed run continues at max(trace_index)+1")

    # Without --resume a non-empty manifest is refused, not appended to.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "manifest.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "trace", "trace_index": 0}) + "\n")
        raises(ValueError,
               lambda: gw.run_benchmark("idle", 1, 0.001, FakeTrigger(),
                                        manifest_path=path, resume=False,
                                        skip_throttle_check=True),
               "a non-empty manifest is refused without --resume",
               contains="--resume")


# --------------------------------------------------------------------------- #
# 5. Malformed manifest
# --------------------------------------------------------------------------- #
def test_malformed_manifest():
    print("[5] Malformed manifest is refused")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "manifest.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"type": "trace", "trace_index": 0}\n')
            fh.write("not json\n")
        raises(ValueError, lambda: gw.read_manifest(path),
               "a corrupt manifest line is an error, not a skip",
               contains="not valid JSON")

    eq(gw.read_manifest("/nonexistent/path.jsonl"), [],
       "a missing manifest reads as empty")
    eq(gw.next_trace_index([]), 0, "an empty manifest starts at 0")
    eq(gw.next_trace_index([{"trace_index": 4}, {"trace_index": 9}]), 10,
       "the next index follows the maximum, not the count")


# --------------------------------------------------------------------------- #
# 6. CLI surface
# --------------------------------------------------------------------------- #
def test_cli():
    print("[6] CLI surface")

    proc = subprocess.run([PY, "-I", os.path.join(ROOT, "goodware_runner.py"),
                           "--help"], capture_output=True, text=True,
                          timeout=60, check=False)
    eq(proc.returncode, 0, "--help exits 0")
    for flag in ("--manifest", "--run-dir", "--resume", "--capture-duration",
                 "--pre-trigger", "--skip-throttle-check"):
        check(flag in proc.stdout, f"--help lists {flag}")

    # On a host without vcgencmd, a run must refuse rather than silently skip
    # the throttle invariant.
    proc = subprocess.run([PY, "-I", os.path.join(ROOT, "goodware_runner.py"),
                           "--task", "idle", "--count", "1", "--dry-run"],
                          capture_output=True, text=True, timeout=60,
                          check=False, cwd=tempfile.gettempdir())
    if gw.read_throttled() is None:
        check(proc.returncode != 0,
              "a run without vcgencmd refuses instead of skipping the gate")
        check("--skip-throttle-check" in proc.stderr,
              f"the refusal says how to proceed: {proc.stderr.strip()[-200:]}")
    else:
        check(True, "vcgencmd is available; the refusal path is untested here")

    # --manifest and --run-dir are mutually exclusive.
    proc = subprocess.run([PY, "-I", os.path.join(ROOT, "goodware_runner.py"),
                           "--manifest", "a.jsonl", "--run-dir", "/tmp/x",
                           "--dry-run", "--skip-throttle-check"],
                          capture_output=True, text=True, timeout=60, check=False)
    check(proc.returncode != 0, "conflicting manifest options are refused")

    # --task all is five cells; each must get its own manifest rather than
    # five workloads appended into one file.
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "m.jsonl")
        proc = subprocess.run(
            [PY, "-I", os.path.join(ROOT, "goodware_runner.py"), "--task", "all",
             "--count", "1", "--duration", "0.001", "--cooldown", "0",
             "--dry-run", "--skip-throttle-check", "--manifest", base],
            capture_output=True, text=True, timeout=120, check=False)
        eq(proc.returncode, 0, "--task all runs in dry-run")
        produced = sorted(f for f in os.listdir(tmp) if f.endswith(".jsonl"))
        eq(len(produced), len(gw.ALL_TASKS),
           f"one manifest per cell: {produced}")
        for task in gw.ALL_TASKS:
            cell = os.path.join(tmp, f"m.{task}.jsonl")
            check(os.path.exists(cell), f"{task} has its own manifest")
            if os.path.exists(cell):
                modes = {r["mode"] for r in trace_records(cell)}
                eq(modes, {f"goodware-{task}"},
                   f"{cell} holds only {task} traces")


# --------------------------------------------------------------------------- #
# 7. Lint
# --------------------------------------------------------------------------- #
def test_lint():
    print("[7] Lint")
    proc = subprocess.run([PY, "-m", "pyflakes",
                           os.path.join(ROOT, "goodware_runner.py")],
                          capture_output=True, text=True, check=False)
    eq(proc.returncode, 0, f"pyflakes clean ({proc.stdout.strip() or 'ok'})")


def main():
    test_throttle()
    test_record_shape()
    test_failure_is_recorded()
    test_manifest_and_resume()
    test_malformed_manifest()
    test_cli()
    test_lint()

    print(f"\n{CHECKS[0]} checks run")
    if FAILURES:
        print(f"{len(FAILURES)} FAILED")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
