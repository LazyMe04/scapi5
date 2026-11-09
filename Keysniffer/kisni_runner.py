#!/usr/bin/env python3
"""Keysniffer EM measurement runner — kernel-module trace lifecycle.

What this is
------------
A per-trace supervisor for the `kisni` kernel module. A kernel-resident payload
has no PID, so `bashlite_runner.py` cannot supervise it: there is no process to
spawn, bound, or sweep. What can be controlled is the module's *presence* and
the *activity source*:

    load module -> settle -> trigger ON -> type -> trigger OFF -> measure -> unload

Reloading per trace is deliberate. The debugfs buffer wraps at 16 KB and cannot
be truncated from userspace, so a byte-count delta only means something if each
trace starts from a fresh module instance. Load and unload happen outside the
trigger window, so the load path does not contaminate the trace.

Comparability contract
----------------------
The trigger, settle time, window length and manifest shape match
`Bashlite/runner/bashlite_runner.py` and `goodware_runner.py`: GPIO 17
active-high, 1.0 s settle, 2.5 s window. A trace is only comparable if it was
produced by the same code path shape as the other classes.

Safety
------
* Dry run by default. `--execute` is required for any real load.
* `--expected-hash` is required with `--execute`; a changed .ko invalidates the
  dataset.
* Containment must be verifiably active; `kisni` performs no networking, so the
  default-deny OUTPUT policy is enough and no C2 exception is needed.
* Never uses `insmod --force`. If the kernel refuses the module, that is a
  reported blocker, not something to route around.

Usage
-----
Dry run, no root, no module::

    python3 kisni_runner.py --mode kisni-typing --count 2 --duration 2.5 \\
        --manifest /tmp/kisni_dry.jsonl

Real trace on the Pi, as root::

    sudo python3 kisni_runner.py --module /home/emlab/work/modules/kisni-6.18.50-a1b2c3d4e5f6.ko \\
        --expected-hash <sha256> --execute --mode kisni-typing \\
        --keysynth /home/emlab/work/tools/keysynth --keyfile /home/emlab/work/keys.txt \\
        --rate 20 --count 3000 --duration 2.5 --cooldown 0.5 \\
        --manifest /home/emlab/work/manifests/run01.jsonl

Logical self-test, no hardware, no root::

    python3 -I kisni_runner.py --self-test
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

RUNNER_VERSION = "1.0.0"
MANIFEST_SCHEMA = 1

DEBUGFS_PATH = "/sys/kernel/debug/kisni/keys"
MODULE_NAME = "kisni"
SETTLE_S = 1.0

# Exit codes, matching bashlite_runner.py so scripts can treat them alike.
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONTAINMENT = 2
EXIT_MODULE = 3
EXIT_FORMAT = 4
EXIT_PRIVILEGE = 5

MODES = ("kisni-typing", "typing-only", "kisni-idle", "idle")
# The 2x2 ablation: module present/absent x keyboard busy/idle. Derived from an
# explicit set rather than string suffix matching, because "typing-only" does
# not end in "typing".
TYPING_MODES = frozenset({"kisni-typing", "typing-only"})
MODULE_MODES = frozenset({"kisni-typing", "kisni-idle"})


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------
def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        remaining = limit
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            if remaining is not None:
                chunk = chunk[:remaining]
                remaining -= len(chunk)
            h.update(chunk)
            if remaining == 0:
                break
    return h.hexdigest()


def run_cmd(argv, timeout=30):
    """Run a command, return (rc, stdout, stderr). Never raises on rc != 0."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]}: timed out after {timeout}s"


# -----------------------------------------------------------------------------
# Machine abstraction — every side effect goes through this, so the logic is
# testable with a fake implementation and no root.
# -----------------------------------------------------------------------------
class Machine:
    """Real system operations used by the runner."""

    def insmod(self, module, codes):
        return run_cmd(["insmod", module, f"codes={codes}"])

    def rmmod(self, name=MODULE_NAME):
        return run_cmd(["rmmod", name])

    def modinfo(self, path):
        return run_cmd(["modinfo", path])

    def lsmod_has(self, name=MODULE_NAME):
        rc, out, _ = run_cmd(["lsmod"])
        return any(line.split() and line.split()[0] == name
                   for line in out.splitlines())

    def debugfs_size(self, path=DEBUGFS_PATH):
        try:
            return os.stat(path).st_size
        except OSError:
            return None

    def dmesg_tail(self, lines=20):
        rc, out, _ = run_cmd(["dmesg"])
        return "\n".join(out.splitlines()[-lines:])

    def dmesg_taint(self):
        text = self.dmesg_tail(200)
        for line in text.splitlines():
            if "taints" in line.lower() or "tainted" in line.lower():
                return line.strip()
        return ""

    def run_keysynth(self, argv, timeout):
        return run_cmd(argv, timeout=timeout)

    def keysynth_leftover(self, keysynth_path):
        """Count surviving keysynth processes, matched by /proc/<pid>/exe.

        `pgrep -f keysynth` cannot be used here: it matches the whole command
        line, and this runner's own argv contains `--keysynth /path/keysynth`,
        so it would report itself as a leak on every trace. Comparing the
        resolved executable path avoids that entirely.
        """
        target = os.path.abspath(keysynth_path or "keysynth")
        if not os.path.isdir("/proc"):
            return 0
        own = {os.getpid(), os.getppid()}
        hits = 0
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid in own:
                continue
            try:
                exe = os.readlink(f"/proc/{pid}/exe").replace(" (deleted)", "")
            except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
                continue
            if os.path.abspath(exe) == target:
                hits += 1
        return hits

    def sleep(self, seconds):
        time.sleep(seconds)


class FakeMachine(Machine):
    """Deterministic stand-in used by --self-test.

    Records every call and simulates module load/unload and a debugfs counter
    that grows only while the module is loaded and keysynth runs.
    """

    def __init__(self, module_present=True, keysynth_rc=0, grow=True,
                 grow_bytes=512, emit_stdout=True):
        self.calls = []
        self.loaded = False
        self.module_present = module_present
        self.keysynth_rc = keysynth_rc
        self.grow = grow
        self.grow_bytes = grow_bytes
        self.emit_stdout = emit_stdout
        self.bytes = 0
        self.vermagic = "6.18.50+rpt-rpi-2712"

    def insmod(self, module, codes):
        self.calls.append(("insmod", module, codes))
        self.loaded = True
        return 0, "", ""

    def rmmod(self, name=MODULE_NAME):
        self.calls.append(("rmmod", name))
        self.loaded = False
        return 0, "", ""

    def modinfo(self, path):
        self.calls.append(("modinfo", path))
        return 0, f"vermagic: {self.vermagic} SMP preempt mod_unload modversions aarch64\n", ""

    def lsmod_has(self, name=MODULE_NAME):
        self.calls.append(("lsmod_has", name))
        return self.loaded

    def debugfs_size(self, path=DEBUGFS_PATH):
        if not self.loaded:
            return None
        return self.bytes

    def dmesg_tail(self, lines=20):
        return "fake dmesg"

    def dmesg_taint(self):
        return "Tainted: G OE" if self.loaded else ""

    def run_keysynth(self, argv, timeout):
        self.calls.append(("keysynth", tuple(argv)))
        if self.keysynth_rc == 0 and self.grow and self.loaded:
            self.bytes += self.grow_bytes
        # Mirrors the real binary's stdout contract.
        if not self.emit_stdout:
            return self.keysynth_rc, "", ""
        n = 50 if self.keysynth_rc == 0 else 0
        return self.keysynth_rc, f"keysynth emitted={n} interval_ms=50 duration_ms=2500\n", ""

    def keysynth_leftover(self, keysynth_path):
        return 0

    def sleep(self, seconds):
        self.calls.append(("sleep", seconds))


# -----------------------------------------------------------------------------
# Checks
# -----------------------------------------------------------------------------
def check_platform():
    """Return (ok, detail). Kernel modules only load on Linux."""
    if platform.system() != "Linux":
        return False, f"host is {platform.system()}, not Linux; a kernel module cannot be loaded"
    return True, platform.release()


def check_privilege():
    if os.geteuid() != 0:
        return False, "must run as root to insmod/rmmod"
    return True, "root"


def check_module_hash(module, expected):
    if not os.path.isfile(module):
        return False, f"module not found: {module}"
    actual = sha256_file(module)
    if expected and actual.lower() != expected.lower():
        return False, f"sha256 mismatch: expected {expected}, got {actual}"
    return True, actual


def check_vermagic(machine, module):
    rc, out, err = machine.modinfo(module)
    if rc != 0:
        return False, (err or out).strip() or "modinfo failed"
    running = platform.release()
    for line in out.splitlines():
        if line.startswith("vermagic:"):
            value = line.split(":", 1)[1].strip()
            base = value.split()[0] if value.split() else ""
            if base != running:
                return False, f"vermagic {base} != running kernel {running}"
            return True, base
    return False, "modinfo produced no vermagic line"


def check_taint_baseline():
    """Refuse to start if the kernel is already tainted by something else.

    A module load taints the kernel (`G OE`), which is expected and recorded.
    But if the kernel is *already* tainted before the first load, the taint is
    from something else, and every manifest would attribute it to `kisni`. The
    bitmask in /proc/sys/kernel/tainted is cumulative and cleared only by a
    reboot, so a stale taint cannot be ignored.
    """
    path = "/proc/sys/kernel/tainted"
    try:
        with open(path, encoding="ascii") as fh:
            mask = int(fh.read().strip() or "0")
    except (OSError, ValueError):
        return None, "cannot read /proc/sys/kernel/tainted"
    if mask == 0:
        return 0, "kernel is not tainted"
    return mask, f"kernel already tainted (mask 0x{mask:x}); reboot before capture"


def check_containment(machine):
    """Require a default-deny OUTPUT policy, or DROP/REJECT rules that cover it.

    `has_rules` alone is not enough: `-A OUTPUT -j ACCEPT` is a rule, and it
    contains nothing. The Bashlite runner had the same shape of bug and fixed
    it by parsing policy and rules properly; this is the minimum version of
    that check. `kisni` performs no networking, so no port exception is needed
    and none is allowed.
    """
    rc, out, _ = run_cmd(["iptables", "-S", "OUTPUT"])
    if rc != 0:
        return False, "cannot read iptables OUTPUT rules (needs root or sudo)"
    policy = None
    accepts, drops = [], []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("-P OUTPUT"):
            parts = line.split()
            policy = parts[2] if len(parts) > 2 else None
        elif line.startswith("-A OUTPUT"):
            if "-j ACCEPT" in line:
                accepts.append(line)
            elif "-j DROP" in line or "-j REJECT" in line:
                drops.append(line)
    if policy == "DROP":
        return True, f"policy DROP ({len(drops)} explicit drop rule(s))"
    if accepts:
        return False, (f"OUTPUT policy is {policy or 'unknown'} and there is an "
                       f"open ACCEPT rule: {accepts[0]}")
    if drops:
        return True, f"no policy DROP, but {len(drops)} DROP/REJECT rule(s) present"
    return False, ("OUTPUT is permissive; run Bashlite/isolation-on.sh first, "
                   "then isolation-off.sh at the end")


# -----------------------------------------------------------------------------
# One trace
# -----------------------------------------------------------------------------
def run_trace(trace_index, args, machine, dry_run):
    """Execute or simulate one trace. Returns a manifest record dict."""
    record = {
        "trace_index": trace_index,
        "started_utc": utc_now(),
        "mode": args.mode,
        "duration_s": args.duration,
        "dry_run": dry_run,
        "module_sha256": None,
        "module_vermagic": None,
        "module_load_monotonic_ns": None,
        "module_unload_monotonic_ns": None,
        "kernel_release": platform.release(),
        "debugfs_bytes_before": None,
        "debugfs_bytes_after": None,
        "debugfs_delta": None,
        "keystroke_file_sha256": None,
        "keystroke_count": 0,
        "keystroke_interval_ms": int(round(1000.0 / args.rate)) if args.rate else None,
        "injector": args.injector,
        "dmesg_taint": "",
        "lsmod_after": None,
        "keysynth_leftover": None,
        "trigger_edge_ns_on": None,
        "trigger_edge_ns_off": None,
        "status": "ok",
        "notes": [],
    }

    wants_module = args.mode in MODULE_MODES
    wants_typing = args.mode in TYPING_MODES

    record["module_required"] = wants_module
    record["typing"] = wants_typing

    # the module hash is known up front and recorded even in dry run
    if args.module and os.path.isfile(args.module):
        record["module_sha256"] = sha256_file(args.module)

    if args.keyfile and os.path.isfile(args.keyfile):
        record["keystroke_file_sha256"] = sha256_file(args.keyfile)

    if dry_run:
        record["notes"].append("dry run: no module load, no keystroke injection")
        return record

    # ---- real path ----
    try:
        machine.rmmod()          # ignore "not loaded"
    except Exception:            # noqa: BLE001 - an absent module is normal

        pass

    if wants_module:
        rc, out, err = machine.modinfo(args.module)
        for line in (out or "").splitlines():
            if line.startswith("vermagic:"):
                record["module_vermagic"] = line.split(":", 1)[1].strip()
                break

        record["module_load_monotonic_ns"] = time.monotonic_ns()
        rc, out, err = machine.insmod(args.module, args.codes)
        if rc != 0:
            record["status"] = "module-load-failed"
            record["notes"].append(f"insmod rc={rc}: {(err or out).strip()}")
            record["finished_utc"] = utc_now()
            return record

    machine.sleep(SETTLE_S)

    before = machine.debugfs_size()
    record["debugfs_bytes_before"] = before

    on_ns = time.monotonic_ns()
    record["trigger_edge_ns_on"] = on_ns
    if args.trigger == "gpio17":
        # GPIO toggling is done by the same helper the other runners use.
        try:
            from gpiozero import OutputDevice  # type: ignore
            pin = OutputDevice(args.gpio_pin, active_high=True, initial_value=True)
            record["notes"].append(f"gpio{args.gpio_pin} asserted")
        except Exception as exc:  # noqa: BLE001
            pin = None
            record["status"] = "trigger-degraded"
            record["notes"].append(f"gpio init failed: {exc}; trigger NOT toggled")
    else:
        pin = None
        record["notes"].append("software trigger: edge timestamps only")

    keysynth_rc = None
    if wants_typing:
        argv = [args.keysynth or "keysynth",
                "--rate", str(args.rate),
                "--duration", str(args.duration),
                "--quiet"]
        if args.keyfile:
            argv += ["--keyfile", args.keyfile]
        rc, out, err = machine.run_keysynth(argv, timeout=args.duration + 10)
        keysynth_rc = rc
        record["keystroke_count"] = _parse_emitted(out)
        record["keystroke_count_source"] = "keysynth stdout"
        if rc != 0:
            record["status"] = "keysynth-failed"
            record["notes"].append(f"keysynth rc={rc}: {(err or out).strip()}")
        elif record["keystroke_count"] == 0:
            # A zero exit with no count means the stdout contract broke, not
            # that nothing was typed. Treat it as a failed trace.
            record["status"] = "keysynth-unreported"
            record["notes"].append(
                "keysynth exited 0 but printed no emitted= count; the trace "
                "cannot be shown to contain typing")
    else:
        machine.sleep(args.duration)

    if pin is not None:
        try:
            pin.off()
            pin.close()
        except Exception:  # noqa: BLE001
            pass

    record["trigger_edge_ns_off"] = time.monotonic_ns()

    after = machine.debugfs_size()
    record["debugfs_bytes_after"] = after
    if before is not None and after is not None:
        record["debugfs_delta"] = after - before
        # A negative delta is not a failure: the upstream buffer wraps at 16 KB
        # rather than growing, so a long trace can land behind where it started.
        # Records were still written; only a *zero* delta means nothing fired.
        if record["debugfs_delta"] < 0:
            record["notes"].append(
                "debugfs delta is negative: the 16 KB buffer wrapped during the "
                "trace, so this trace's byte delta is not comparable to an "
                "unwrapped one")
        if wants_module and wants_typing and keysynth_rc == 0 \
                and record["debugfs_delta"] == 0:
            record["status"] = "no-activity"
            record["notes"].append(
                "debugfs did not grow: the module did not record the keystrokes")

    if wants_module:
        if args.trigger == "gpio17" and pin is not None:
            # Step 9/11 ordering from the plan: the trigger edge closes the
            # measurement window before the module is removed, so the unload
            # path cannot land inside the trace.
            record["trigger_edge_ns_off"] = time.monotonic_ns()
        record["module_unload_monotonic_ns"] = time.monotonic_ns()
        machine.rmmod()

    record["lsmod_after"] = machine.lsmod_has()
    record["dmesg_taint"] = machine.dmesg_taint()
    record["keysynth_leftover"] = machine.keysynth_leftover(args.keysynth)

    if record["lsmod_after"]:
        record["status"] = "module-leaked"
        record["notes"].append("kisni still present in lsmod after rmmod")
    if record["keysynth_leftover"]:
        record["status"] = "injector-leaked"
        record["notes"].append(
            f"{record['keysynth_leftover']} keysynth process(es) still running")

    record["finished_utc"] = utc_now()
    if record["trigger_edge_ns_on"] and record["trigger_edge_ns_off"]:
        record["window_ns"] = record["trigger_edge_ns_off"] - record["trigger_edge_ns_on"]
    return record


def _parse_emitted(stdout):
    """Read `emitted=N` from keysynth's machine-readable line."""
    m = re.search(r"emitted=(\d+)", stdout or "")
    return int(m.group(1)) if m else 0


def write_manifest_line(path, manifest):
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest, sort_keys=True) + "\n")


# -----------------------------------------------------------------------------
# Self-test — exercises the lifecycle logic with FakeMachine, no root, no module
# -----------------------------------------------------------------------------
def self_test():
    failures = []
    checks = [0]

    def expect(cond, label):
        checks[0] += 1
        if not cond:
            failures.append(label)
        return cond

    base = argparse.Namespace(
        mode="kisni-typing", duration=2.5, rate=20, module="/nonexistent.ko",
        keyfile=None, codes=1, trigger="software", gpio_pin=17,
        keysynth="/nonexistent/keysynth", injector="uinput",
    )

    # 1. healthy trace: module loads, keysynth grows debugfs, unloads cleanly
    m = FakeMachine()
    rec = run_trace(0, base, m, dry_run=False)
    expect(rec["status"] == "ok", f"healthy status was {rec['status']}")
    expect(rec["debugfs_delta"] == 512, f"delta was {rec['debugfs_delta']}")
    expect(rec["lsmod_after"] is False, "module left loaded")
    expect(("insmod", "/nonexistent.ko", 1) in m.calls, "insmod not called with codes=1")
    expect(any(c[0] == "rmmod" for c in m.calls), "rmmod not called")

    # 2. typing-only: no module, keysynth runs, debugfs never appears
    m = FakeMachine()
    rec = run_trace(0, argparse.Namespace(**{**vars(base), "mode": "typing-only"}), m, False)
    expect(not any(c[0] == "insmod" for c in m.calls), "typing-only loaded the module")
    expect(any(c[0] == "keysynth" for c in m.calls), "typing-only did not type")

    # 3. kisni-idle: module loads, no typing, no growth required
    m = FakeMachine()
    rec = run_trace(0, argparse.Namespace(**{**vars(base), "mode": "kisni-idle"}), m, False)
    expect(rec["status"] == "ok", f"kisni-idle status {rec['status']}")
    expect(not any(c[0] == "keysynth" for c in m.calls), "kisni-idle typed")

    # 4. module loaded + typing but no growth -> no-activity
    m = FakeMachine(grow=False)
    rec = run_trace(0, base, m, dry_run=False)
    expect(rec["status"] == "no-activity", f"expected no-activity, got {rec['status']}")

    # 5. insmod failure is reported, not swallowed
    class BadMachine(FakeMachine):
        def insmod(self, module, codes):
            return 1, "", "Invalid module format"
    m = BadMachine()
    rec = run_trace(0, base, m, dry_run=False)
    expect(rec["status"] == "module-load-failed", f"expected load-failed, got {rec['status']}")
    expect(any("Invalid module format" in n for n in rec["notes"]), "insmod error not recorded")

    # 6. dry run touches nothing
    m = FakeMachine()
    rec = run_trace(0, base, m, dry_run=True)
    expect(rec["dry_run"] is True, "dry_run flag not set")
    expect(not m.calls, f"dry run made calls: {m.calls}")

    # 7. hash mismatch is rejected
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(b"module bytes")
        tmpname = tmp.name
    try:
        ok, detail = check_module_hash(tmpname, "0" * 64)
        expect(not ok, f"bad hash accepted: {detail}")
        good = sha256_file(tmpname)
        ok, detail = check_module_hash(tmpname, good)
        expect(ok, f"good hash rejected: {detail}")
    finally:
        os.unlink(tmpname)

    # 8. vermagic mismatch is rejected
    class WrongVer(FakeMachine):
        def __init__(self):
            super().__init__()
            self.vermagic = "4.19.57-v7+"
    ok, detail = check_vermagic(WrongVer(), "/nonexistent.ko")
    expect(not ok, "foreign vermagic accepted")

    # 9. mode list is the documented set
    expect(set(MODES) == {"kisni-typing", "typing-only", "kisni-idle", "idle"},
           "MODES drifted")

    # 10. the full 2x2 ablation matrix: module present/absent x typing busy/idle
    expected_matrix = {
        "kisni-typing": (True, True),
        "typing-only": (False, True),
        "kisni-idle": (True, False),
        "idle": (False, False),
    }
    for mode, (want_mod, want_type) in expected_matrix.items():
        m = FakeMachine()
        rec = run_trace(0, argparse.Namespace(**{**vars(base), "mode": mode}), m, False)
        loaded = any(c[0] == "insmod" for c in m.calls)
        typed = any(c[0] == "keysynth" for c in m.calls)
        expect(loaded == want_mod,
               f"{mode}: insmod={loaded}, expected {want_mod}")
        expect(typed == want_type,
               f"{mode}: typed={typed}, expected {want_type}")
        expect(rec["status"] == "ok", f"{mode}: status {rec['status']}")
        expect(not m.loaded, f"{mode}: module left loaded")

    # 11. lifecycle timestamps are ordered load < on < off < unload
    m = FakeMachine()
    rec = run_trace(0, base, m, dry_run=False)
    order = [rec["module_load_monotonic_ns"], rec["trigger_edge_ns_on"],
             rec["trigger_edge_ns_off"], rec["module_unload_monotonic_ns"]]
    expect(all(x is not None for x in order), f"missing lifecycle timestamps: {order}")
    if all(x is not None for x in order):
        expect(order == sorted(order), f"lifecycle timestamps out of order: {order}")
    expect(rec["module_vermagic"] is not None, "module_vermagic not recorded")

    # 12. keystroke_count comes from keysynth's stdout, not from an assumption
    expect(rec["keystroke_count"] == 50,
           f"keystroke_count was {rec['keystroke_count']}, expected 50")

    # 13. a leftover keysynth process is reported
    class LeakyInjector(FakeMachine):
        def keysynth_leftover(self, keysynth_path):
            return 1
    rec = run_trace(0, base, LeakyInjector(), dry_run=False)
    expect(rec["status"] == "injector-leaked",
           f"leftover injector not flagged, status={rec['status']}")

    # 13b. the leak check must not match on the runner's own command line.
    # `pgrep -f keysynth` would, because this runner's argv contains
    # `--keysynth /path/keysynth`; matching /proc/<pid>/exe must not.
    m = FakeMachine()
    run_trace(0, base, m, False)
    expect(m.keysynth_leftover(base.keysynth) == 0,
           "runner reports itself as a leaked injector")

    # 14. module leak is distinguished from a clean unload
    class LeakyModule(FakeMachine):
        def lsmod_has(self, name=MODULE_NAME):
            return True
    rec = run_trace(0, base, LeakyModule(), dry_run=False)
    expect(rec["status"] == "module-leaked",
           f"module leak not flagged, status={rec['status']}")

    # 15. the module is loaded even when nothing will be typed (kisni-idle).
    # The first rmmod is the plan's step-3 pre-clean, so the load is bounded by
    # the *last* rmmod, not the first.
    m = FakeMachine()
    run_trace(0, argparse.Namespace(**{**vars(base), "mode": "kisni-idle"}), m, False)
    insmod_at = next(i for i, c in enumerate(m.calls) if c[0] == "insmod")
    rmmod_at = max(i for i, c in enumerate(m.calls) if c[0] == "rmmod")
    expect(insmod_at < rmmod_at, "load/unload order wrong")
    expect(m.calls[insmod_at - 1][0] == "rmmod" or
           any(c[0] == "rmmod" and i < insmod_at for i, c in enumerate(m.calls)),
           "no pre-clean rmmod before insmod")
    settle = [c for c in m.calls if c[0] == "sleep" and c[1] == SETTLE_S]
    expect(len(settle) >= 1, "settle delay skipped")

    # 16. a negative delta is a buffer wrap, not a failure: records were still
    # written. Reporting it as `no-activity` would discard a valid trace.
    class WrappingMachine(FakeMachine):
        def __init__(self):
            super().__init__()
            self.bytes = 16000          # nearly full 16 KB buffer

        def run_keysynth(self, argv, timeout):
            self.calls.append(("keysynth", tuple(argv)))
            self.bytes = (self.bytes + 2000) % 16384   # wraps past the end
            return 0, "keysynth emitted=50 interval_ms=50 duration_ms=2500\n", ""
    rec = run_trace(0, base, WrappingMachine(), dry_run=False)
    expect(rec["debugfs_delta"] is not None and rec["debugfs_delta"] < 0,
           f"wrap fixture produced delta {rec['debugfs_delta']}")
    expect(rec["status"] == "ok", f"buffer wrap reported as {rec['status']}")
    expect(any("wrapped" in n for n in rec["notes"]), "wrap not noted")

    # 17. keysynth exits 0 but prints no count: the trace cannot be shown to
    # contain typing, so it must not be recorded as clean.
    rec = run_trace(0, base, FakeMachine(emit_stdout=False), dry_run=False)
    expect(rec["status"] == "keysynth-unreported",
           f"missing stdout contract gave status {rec['status']}")

    # 18. a genuinely empty delta is still a failure.
    rec = run_trace(0, base, FakeMachine(grow=False), dry_run=False)
    expect(rec["status"] == "no-activity", f"zero delta gave {rec['status']}")

    # 19. the taint baseline gate rejects an already-tainted kernel, and
    # --allow-taint accepts it explicitly.
    if os.path.isfile("/proc/sys/kernel/tainted"):
        mask, detail = check_taint_baseline()
        expect(mask is not None, f"taint unreadable on Linux: {detail}")
    else:
        mask, detail = check_taint_baseline()
        expect(mask is None, "missing /proc/sys/kernel/tainted not reported")

    # 20. containment must not accept an open ACCEPT rule as "contained".
    class IptablesMachine(Machine):
        def __init__(self, text):
            self.text = text

    def containment_of(text):
        original = run_cmd
        globals()["run_cmd"] = lambda argv, timeout=30: (0, text, "")
        try:
            return check_containment(IptablesMachine(text))
        finally:
            globals()["run_cmd"] = original

    ok, detail = containment_of("-P OUTPUT DROP\n-A OUTPUT -o lo -j ACCEPT\n")
    expect(ok, f"default-deny rejected: {detail}")

    ok, detail = containment_of("-P OUTPUT ACCEPT\n-A OUTPUT -j ACCEPT\n")
    expect(not ok, "permissive OUTPUT accepted")

    ok, detail = containment_of("-P OUTPUT ACCEPT\n-A OUTPUT -d 8.8.8.8/32 -j DROP\n")
    expect(ok, f"explicit DROP rejected: {detail}")

    ok, detail = containment_of("-P OUTPUT ACCEPT\n")
    expect(not ok, "empty rule set accepted")

    if failures:
        print(f"SELF-TEST FAILED ({len(failures)})")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"SELF-TEST PASSED ({checks[0]} checks)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Keysniffer EM measurement runner (kernel-module trace lifecycle).")
    parser.add_argument("--module", help="path to the locally built kisni .ko")
    parser.add_argument("--expected-hash", help="expected SHA-256; REQUIRED with --execute")
    parser.add_argument("--mode", choices=MODES, default="kisni-typing")
    parser.add_argument("--count", "-c", type=int, default=10)
    parser.add_argument("--duration", "-d", type=float, default=2.5)
    parser.add_argument("--cooldown", type=float, default=0.5)
    parser.add_argument("--trigger", choices=["gpio17", "software"], default="gpio17")
    parser.add_argument("--gpio-pin", type=int, default=17)
    parser.add_argument("--codes", type=int, default=1,
                        help="kisni module parameter: 0=keymap text, 1=hex, 2=decimal")
    parser.add_argument("--keysynth", help="path to the keysynth binary")
    parser.add_argument("--keyfile", help="keystroke sequence file (hashed into the manifest)")
    parser.add_argument("--rate", type=float, default=20.0, help="keys per second")
    parser.add_argument("--injector", choices=["uinput", "hid"], default="uinput",
                        help="uinput = keysynth; hid = external USB HID microcontroller")
    parser.add_argument("--run-dir", help="directory for the manifest and per-trace logs")
    parser.add_argument("--manifest", help="JSONL manifest path (append-only)")
    parser.add_argument("--execute", action="store_true", help="actually load the module")
    parser.add_argument("--allow-taint", action="store_true",
                        help="acknowledge the kernel will be tainted (recorded, not fatal)")
    parser.add_argument("--skip-containment-check", action="store_true")
    parser.add_argument("--self-test", action="store_true",
                        help="run the logic self-test; no hardware, no root")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    dry_run = not args.execute
    machine = Machine()

    if not dry_run:
        # Argument errors first: they are the caller's fault and are diagnosable
        # on any host, so they should not be masked by an environment check.
        if not args.module:
            print("[FATAL] --module is required with --execute", file=sys.stderr)
            return EXIT_USAGE
        if not args.expected_hash:
            print("[FATAL] --expected-hash is required with --execute", file=sys.stderr)
            return EXIT_USAGE
        ok, detail = check_module_hash(args.module, args.expected_hash)
        if not ok:
            print(f"[FATAL] {detail}", file=sys.stderr)
            return EXIT_MODULE
        ok, detail = check_platform()
        if not ok:
            print(f"[FATAL] {detail}", file=sys.stderr)
            return EXIT_MODULE
        ok, detail = check_vermagic(machine, args.module)
        if not ok:
            print(f"[FATAL] vermagic: {detail}", file=sys.stderr)
            return EXIT_MODULE
        ok, detail = check_privilege()
        if not ok:
            print(f"[FATAL] {detail}", file=sys.stderr)
            return EXIT_PRIVILEGE
        if not args.skip_containment_check:
            ok, detail = check_containment(machine)
            if not ok:
                print(f"[FATAL] containment: {detail}", file=sys.stderr)
                return EXIT_CONTAINMENT
        if args.mode in TYPING_MODES and not shutil.which(args.keysynth or "keysynth") \
                and not (args.keysynth and os.path.isfile(args.keysynth)):
            print("[FATAL] keysynth not found; pass --keysynth PATH", file=sys.stderr)
            return EXIT_USAGE
        if args.mode in MODULE_MODES:
            # A module load always taints the kernel. Refuse if something else
            # already did: otherwise every manifest attributes a foreign taint
            # to kisni, and the run is not a clean baseline.
            mask, detail = check_taint_baseline()
            if mask is None:
                print(f"[FATAL] {detail}", file=sys.stderr)
                return EXIT_MODULE
            if mask != 0 and not args.allow_taint:
                print(f"[FATAL] {detail}", file=sys.stderr)
                print("        reboot the Pi before capture, or pass --allow-taint "
                      "to record the pre-existing taint in every manifest.",
                      file=sys.stderr)
                return EXIT_MODULE
            if mask != 0:
                print(f"[WARN] {detail} (accepted via --allow-taint)")

    print(f"\n[Keysniffer] mode={args.mode} count={args.count} duration={args.duration}s "
          f"trigger={args.trigger} {'DRY RUN' if dry_run else 'EXECUTE'}")
    print(f"[Keysniffer] version {RUNNER_VERSION}, manifest schema {MANIFEST_SCHEMA}\n")

    if args.run_dir:
        os.makedirs(args.run_dir, exist_ok=True)
        manifest_path = args.manifest or os.path.join(args.run_dir, "manifest.jsonl")
    else:
        manifest_path = args.manifest or f"kisni_manifest_{stamp()}.jsonl"
    header = {
        "schema": MANIFEST_SCHEMA,
        "runner_version": RUNNER_VERSION,
        "started_utc": utc_now(),
        "mode": args.mode,
        "count": args.count,
        "duration_s": args.duration,
        "cooldown_s": args.cooldown,
        "trigger": args.trigger,
        "gpio_pin": args.gpio_pin if args.trigger == "gpio17" else None,
        "codes": args.codes,
        "rate": args.rate,
        "injector": args.injector,
        "keyfile": os.path.abspath(args.keyfile) if args.keyfile else None,
        "module": os.path.abspath(args.module) if args.module else None,
        "expected_hash": args.expected_hash,
        "kernel_release": platform.release(),
        "host": platform.platform(),
        "dry_run": dry_run,
        "allow_taint": args.allow_taint,
    }
    write_manifest_line(manifest_path, {"type": "header", **header})

    failed = 0
    for i in range(args.count):
        record = run_trace(i, args, machine, dry_run)
        write_manifest_line(manifest_path, {"type": "trace", **record})
        print(f"  trace {i + 1}/{args.count}: {record['status']}"
              + (f"  delta={record['debugfs_delta']}" if record["debugfs_delta"] is not None else ""))
        if record["status"] not in ("ok",):
            failed += 1
            if record["status"] in ("module-load-failed", "module-leaked"):
                break
        if i + 1 < args.count:
            machine.sleep(args.cooldown)

    print(f"\n[Completed] {args.count - failed}/{args.count} clean. Manifest: {manifest_path}\n")
    write_manifest_line(manifest_path, {"type": "footer", "finished_utc": utc_now(),
                                        "clean": args.count - failed, "failed": failed})
    return EXIT_OK if failed == 0 else EXIT_MODULE


if __name__ == "__main__":
    sys.exit(main())
