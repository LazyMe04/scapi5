#!/usr/bin/env python3
"""Test suite for the Keysniffer lab tools.

Three of the four deliverables are testable without hardware or root:

  kisni_runner.py      lifecycle logic, exercised through FakeMachine
  keysni_analyze.py    dataset validation, pure functions
  keysni_preflight.py  device checks, exercised against the real filesystem

`tools/keysynth.c` is not covered here: it needs a C compiler and a Pi to mean
anything, and a test that only proves it parses would be misleading. It is
reviewed in `analysis_notes/KEYSNIFFER_STATIC_REVIEW.md` and built in Phase 3.

Run::

    python3 -I tests/run_tests.py

Exit code 0 means every check passed.
"""

import os
import platform
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

SUITES = [
    ("kisni_runner --self-test", [os.path.join(ROOT, "kisni_runner.py"), "--self-test"]),
    ("keysni_analyze --self-test", [os.path.join(ROOT, "keysni_analyze.py"), "--self-test"]),
    ("keysni_preflight --json", [os.path.join(ROOT, "keysni_preflight.py"), "--json"]),
    ("kisni_runner --help", [os.path.join(ROOT, "kisni_runner.py"), "--help"]),
    ("keysni_analyze --help", [os.path.join(ROOT, "keysni_analyze.py"), "--help"]),
    ("keysni_preflight --help", [os.path.join(ROOT, "keysni_preflight.py"), "--help"]),
    ("keysynth.c static check", [os.path.join(HERE, "check_c_source.py"),
                                 os.path.join(ROOT, "tools", "keysynth.c")]),
]

# Commands that must be *refused*. Each tuple is (label, argv, expected exit).
MUST_REFUSE = [
    ("execute without --module", ["kisni_runner.py", "--execute"], 2),
    ("execute without --expected-hash", ["kisni_runner.py", "--execute",
                                         "--module", "x.ko"], 2),
    ("invalid --mode", ["kisni_runner.py", "--mode", "bogus"], 2),
    ("analyze with no manifests", ["keysni_analyze.py"], 2),
]


def run(argv):
    return subprocess.run([PY, "-I"] + argv, capture_output=True, text=True,
                          check=False, timeout=120)


def main():
    failures = []

    for label, argv in SUITES:
        proc = run(argv)
        # preflight is allowed to exit 0 or 1 depending on the host; the other
        # help/self-test runs must be clean.
        ok = proc.returncode == 0 or (label.startswith("keysni_preflight")
                                      and proc.returncode == 1)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label} (exit {proc.returncode})")
        if not ok:
            failures.append(label)
            for line in (proc.stdout + proc.stderr).strip().splitlines()[-6:]:
                print(f"        {line}")

    for label, argv, expected in MUST_REFUSE:
        proc = run(argv)
        ok = proc.returncode == expected
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] refuse: {label} (exit {proc.returncode}, wanted {expected})")
        if not ok:
            failures.append(label)
            print(f"        {(proc.stdout + proc.stderr).strip().splitlines()[-1:]}")

    # A dry-run end-to-end pass: runner writes a manifest, analyzer reads it.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        key = os.path.join(tmp, "keys.txt")
        with open(key, "w", encoding="utf-8") as fh:
            fh.write("abcdefghij test keys\n")
        man = os.path.join(tmp, "m.jsonl")
        proc = run([os.path.join(ROOT, "kisni_runner.py"), "--mode", "typing-only",
                    "--count", "2", "--keyfile", key, "--manifest", man])
        ok = proc.returncode == 0 and os.path.isfile(man)
        print(f"[{'PASS' if ok else 'FAIL'}] end-to-end: runner wrote a manifest")
        if ok:
            proc = run([os.path.join(ROOT, "keysni_analyze.py"), man])
            # A dry-run-only dataset must be rejected: the analyzer exits 1.
            ok = proc.returncode == 1 and "no measurement" in proc.stdout
            print(f"[{'PASS' if ok else 'FAIL'}] end-to-end: analyzer rejected the dry run")
        if not ok:
            failures.append("end-to-end")
            print((proc.stdout + proc.stderr).strip())

    failures += check_goodware_runner()
    failures += check_lint()

    print()
    if failures:
        print(f"FAILED: {len(failures)} suite(s) - " + ", ".join(failures))
        return 1
    print(f"All suites passed on {platform.platform()}")
    return 0


def check_lint():
    """pyflakes if available; an indentation slip is invisible until runtime."""
    import importlib.util
    if importlib.util.find_spec("pyflakes") is None:
        print("[SKIP] pyflakes not installed; lint skipped")
        return []
    targets = [os.path.join(os.path.dirname(ROOT), "goodware_runner.py")]
    for name in ("kisni_runner.py", "keysni_analyze.py", "keysni_preflight.py"):
        targets.append(os.path.join(ROOT, name))
    for name in ("run_tests.py", "check_c_source.py"):
        targets.append(os.path.join(HERE, name))
    proc = subprocess.run([PY, "-m", "pyflakes"] + targets,
                          capture_output=True, text=True, check=False, timeout=120)
    ok = proc.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] lint: pyflakes clean")
    if not ok:
        print(proc.stdout.strip())
        return ["lint"]
    return []


def check_goodware_runner():
    """The `keyboard` profile must never degrade into an idle trace."""
    runner = os.path.join(os.path.dirname(ROOT), "goodware_runner.py")
    if not os.path.isfile(runner):
        print("[SKIP] goodware_runner.py not found next to Keysniffer/")
        return []

    failures = []
    base = [PY, "-I", runner, "--task", "keyboard", "--count", "1",
            "--duration", "0.1", "--dry-run", "--cooldown", "0"]

    def go(env=None, argv=None):
        e = dict(os.environ)
        if env:
            e.update(env)
        return subprocess.run(argv or base, capture_output=True, text=True,
                              env=e, check=False, timeout=120)

    proc = go(env={"EMLAB_KEYSYNTH": "/nonexistent/keysynth"})
    ok = proc.returncode != 0 and "Aborted" in proc.stdout
    print(f"[{'PASS' if ok else 'FAIL'}] goodware: missing injector aborts the trace")
    if not ok:
        failures.append("goodware missing injector")

    # A stub that mirrors keysynth's real stdout contract. `.bat` because the
    # test host is Windows; on the Pi the real binary is used.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        stub = os.path.join(tmp, "keysynth_stub.bat")
        with open(stub, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write("@echo off\necho keysynth emitted=50 interval_ms=50 "
                     "duration_ms=100\n")
        proc = go(env={"EMLAB_KEYSYNTH": stub})
        ok = proc.returncode == 0 and "50 keystrokes" in proc.stdout
        print(f"[{'PASS' if ok else 'FAIL'}] goodware: injector count reaches the log")
        if not ok:
            failures.append("goodware injector count")
            print((proc.stdout + proc.stderr).strip()[-400:])

    proc = subprocess.run([PY, "-I", runner, "--task", "all", "--count", "1",
                           "--duration", "0.05", "--dry-run", "--cooldown", "0"],
                          capture_output=True, text=True, check=False, timeout=180)
    ok = proc.returncode == 0 and "KEYBOARD" not in proc.stdout
    print(f"[{'PASS' if ok else 'FAIL'}] goodware: --task all excludes keyboard "
          f"(keeps old campaigns comparable)")
    if not ok:
        failures.append("goodware --task all")
        print((proc.stdout + proc.stderr).strip()[-400:])
    return failures


if __name__ == "__main__":
    sys.exit(main())
