#!/usr/bin/env python3
"""Pre-flight gate for the Keysniffer campaign: Phases 1, 3.1 and 5.

Everything here is read-only. Nothing loads a module, writes outside /tmp, or
changes a kernel setting. The point is to make the expensive, risky phases
unreachable until the cheap checks have passed.

Checks are grouped by the phase that requires them:

  P1  restore point exists, power/clock state is clean, recovery path recorded
  P3  kernel headers, Module.symvers, and the CONFIG_MODULE_SIG* decision
  P5  debugfs mounted, uinput available, load/unload rehearsal prerequisites

Run it on the Pi before Phase 2::

    python3 -I keysni_preflight.py
    python3 -I keysni_preflight.py --json
    python3 -I keysni_preflight.py --image /path/to/pi5-prekeysniffer.img

Exit codes: 0 all required checks pass, 1 a required check failed,
2 usage, 3 not running on Linux (dry-run inspection only).
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys

OK = "ok"
WARN = "warn"
FAIL = "fail"
SKIP = "skip"


def run(argv, timeout=20):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           check=False)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


# -----------------------------------------------------------------------------
# Phase 1 — restore point and environment fingerprint
# -----------------------------------------------------------------------------
def check_image(path):
    """A restore point is mandatory: the Pi has no snapshots."""
    if not path:
        return WARN, ("no --image given; confirm an SD image exists and has "
                      "been hashed before any module is loaded")
    if not os.path.isfile(path):
        return FAIL, f"image not found: {path}"
    sha = path + ".sha256"
    if not os.path.isfile(sha):
        return WARN, f"image found but no {os.path.basename(sha)} alongside it"
    size_gb = os.path.getsize(path) / 1e9
    return OK, f"image {os.path.basename(path)} ({size_gb:.1f} GB) + sha256"


def check_throttled():
    rc, out, err = run(["vcgencmd", "get_throttled"])
    if rc != 0:
        return SKIP, f"vcgencmd unavailable ({err or 'not found'})"
    if out.strip() != "throttled=0x0":
        return FAIL, f"{out} - power or thermal fault; abort the capture"
    return OK, out


def check_overclock():
    path = "/boot/firmware/config.txt"
    text = read(path)
    if text is None:
        return SKIP, f"{path} not readable"
    bad = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or "=" not in s:
            continue
        key = s.split("=", 1)[0].strip()
        if key in ("arm_freq", "overclock", "force_turbo", "arm_freq_min"):
            bad.append(s)
    if bad:
        return FAIL, "overclock/clock settings present: " + "; ".join(bad)
    return OK, "no arm_freq / overclock / force_turbo entries"


def check_recovery():
    """Image alone is not a recovery path if the card cannot be re-flashed."""
    cfg = read("/boot/firmware/config.txt") or ""
    uart = any(line.strip().startswith("enable_uart=1")
               for line in cfg.splitlines())
    note = read("/boot/firmware/cmdline.txt") or ""
    if uart or "console=serial0" in note:
        return OK, "UART console appears enabled"
    return WARN, ("no UART console detected; confirm HDMI + USB keyboard, or "
                  "that the SD card can be pulled and re-flashed")


# -----------------------------------------------------------------------------
# Phase 3.1 — build prerequisites
# -----------------------------------------------------------------------------
def check_kernel_release():
    rel = platform.release()
    # The repo carries two different versions; a module is tied to the exact
    # string, so report what this machine actually is rather than assuming.
    if rel in ("6.18.34+rpt-rpi-2712", "6.18.50+rpt-rpi-2712"):
        return OK, rel
    return WARN, (f"{rel} - plan records 6.18.34 and 6.18.50; re-verify before "
                  f"building, the .ko will not load on a different release")


def check_headers():
    rel = platform.release()
    build = f"/lib/modules/{rel}/build"
    if not os.path.isdir(build):
        return FAIL, f"{build} missing; install linux-headers-{rel}"
    real = os.path.realpath(build)
    if not os.path.isfile(os.path.join(real, "Makefile")):
        return FAIL, f"{build} -> {real} has no Makefile"
    return OK, f"{build} -> {real}"


def check_symvers():
    rel = platform.release()
    path = f"/lib/modules/{rel}/Module.symvers"
    if os.path.isfile(path):
        return OK, path
    # Only fatal when CONFIG_MODVERSIONS=y, which check_module_config decides.
    return WARN, f"{path} missing (fatal only if CONFIG_MODVERSIONS=y)"


def check_module_config():
    rel = platform.release()
    config = read(f"/boot/config-{rel}")
    if config is None:
        rc, out, _ = run(["modprobe", "--showconfig"])
        config = out if rc == 0 else None
    if config is None:
        return WARN, f"/boot/config-{rel} unreadable; check CONFIG_MODULE_SIG* by hand"

    vals = {}
    for line in config.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.startswith("CONFIG_MODULE_SIG") or k in ("CONFIG_MODVERSIONS",
                                                      "CONFIG_DEBUG_FS"):
            vals[k] = v

    if vals.get("CONFIG_MODULE_SIG_FORCE") == "y":
        return FAIL, ("CONFIG_MODULE_SIG_FORCE=y: an unsigned module will be "
                      "refused. Do NOT disable it. Sign with the local MOK key "
                      "or report this as a blocker.")
    if vals.get("CONFIG_DEBUG_FS") != "y":
        return FAIL, "CONFIG_DEBUG_FS is not y; /sys/kernel/debug/kisni/keys will not exist"
    if vals.get("CONFIG_MODVERSIONS") == "y":
        return OK, ("MODVERSIONS=y (must build against the Pi's Module.symvers), "
                    f"MODULE_SIG={vals.get('CONFIG_MODULE_SIG', 'n')}, "
                    "DEBUG_FS=y - load will taint the kernel")
    return OK, ("MODVERSIONS=n, "
                f"MODULE_SIG={vals.get('CONFIG_MODULE_SIG', 'n')}, DEBUG_FS=y")


def check_build_tools():
    missing = [t for t in ("make", "gcc") if not shutil.which(t)]
    if missing:
        return FAIL, "missing: " + ", ".join(missing) + " (apt install build-essential)"
    rc, out, _ = run(["gcc", "--version"])
    return OK, (out.splitlines()[0] if out else "gcc present")


# -----------------------------------------------------------------------------
# Phase 5 — load/unload rehearsal prerequisites
# -----------------------------------------------------------------------------
def check_debugfs():
    base = "/sys/kernel/debug"
    if not os.path.isdir(base):
        return FAIL, f"{base} does not exist"
    rc, out, err = run(["mount"])
    if rc != 0:
        return FAIL, f"cannot list mounts ({err or 'mount failed'})"
    # The exact path must be absent now: a stale entry means a module is
    # already loaded, which would invalidate the first trace's byte delta.
    if not os.path.ismount(base):
        return FAIL, f"{base} is not a mount point (mount -t debugfs none {base})"
    if os.path.exists("/sys/kernel/debug/kisni"):
        return FAIL, "debugfs:/kisni already present - a module is loaded; rmmod first"
    return OK, f"{base} mounted, no stale kisni entry"


def check_taint():
    """A module load taints the kernel; a pre-existing taint is a bad baseline."""
    try:
        with open("/proc/sys/kernel/tainted", encoding="ascii") as fh:
            mask = int(fh.read().strip() or "0")
    except (OSError, ValueError) as exc:
        return FAIL, f"cannot read /proc/sys/kernel/tainted: {exc}"
    if mask == 0:
        return OK, "kernel is not tainted"
    return WARN, (f"kernel already tainted (mask 0x{mask:x}); reboot before "
                  f"capture, or every manifest will attribute a foreign taint to kisni")


def check_uinput():
    if not os.path.exists("/dev/uinput"):
        rc, _, _ = run(["modprobe", "-n", "uinput"])
        if rc == 0:
            return FAIL, "/dev/uinput absent but the uinput module is available; load it"
        return FAIL, "/dev/uinput absent and uinput is not available"
    if not os.access("/dev/uinput", os.W_OK):
        return WARN, "/dev/uinput not writable by this user (root, or a udev rule, required)"
    return OK, "/dev/uinput present and writable"


def check_kisni_absent():
    rc, out, _ = run(["lsmod"])
    if rc != 0:
        return SKIP, "lsmod unavailable"
    loaded = any(line.split() and line.split()[0] == "kisni"
                 for line in out.splitlines())
    if loaded:
        return FAIL, "kisni is already loaded; unload it before a run"
    return OK, "kisni not loaded"


# -----------------------------------------------------------------------------
def gather(image=None):
    results = []

    def add(phase, name, fn, *a):
        if platform.system() != "Linux" and phase != "P1":
            status, detail = SKIP, f"not Linux (host is {platform.system()})"
        else:
            try:
                status, detail = fn(*a)
            except Exception as exc:  # noqa: BLE001 - a check must never crash the run
                status, detail = FAIL, f"check raised: {exc}"
        results.append({"phase": phase, "check": name,
                        "status": status, "detail": detail})

    add("P1", "restore_image", check_image, image)
    add("P1", "throttled", check_throttled)
    add("P1", "no_overclock", check_overclock)
    add("P1", "recovery_path", check_recovery)
    add("P3", "kernel_release", check_kernel_release)
    add("P3", "build_tools", check_build_tools)
    add("P3", "headers", check_headers)
    add("P3", "module_symvers", check_symvers)
    add("P3", "module_config", check_module_config)
    add("P5", "debugfs", check_debugfs)
    add("P5", "taint_baseline", check_taint)
    add("P5", "uinput", check_uinput)
    add("P5", "kisni_absent", check_kisni_absent)
    return results


GLYPH = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL", SKIP: "SKIP"}


def render(results, stream=sys.stdout):
    stream.write(f"{'':4} {'phase':<5} {'check':<18} detail\n")
    for r in results:
        stream.write(f"{GLYPH[r['status']]} {r['phase']:<5} {r['check']:<18} "
                     f"{r['detail']}\n")
    fails = sum(r["status"] == FAIL for r in results)
    warns = sum(r["status"] == WARN for r in results)
    stream.write(f"\n{fails} failed, {warns} warning(s)\n")
    if fails:
        stream.write("\nNot ready. Fix the FAIL lines before Phase 2.\n")
    return 1 if fails else 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Keysniffer Phase 1/3/5 preflight gate.")
    p.add_argument("--image", help="path to the SD-card image (the restore point)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    results = gather(args.image)
    if args.json:
        print(json.dumps(results, indent=2))
        return 1 if any(r["status"] == FAIL for r in results) else 0

    if platform.system() != "Linux":
        print(f"note: host is {platform.system()}; device checks are skipped.\n")
    return render(results)


if __name__ == "__main__":
    sys.exit(main())
