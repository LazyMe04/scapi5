#!/usr/bin/env python3
"""
Goodware Workload Runner & Hardware GPIO Trigger for Side-Channel Analysis
Designed for Raspberry Pi 5 (ARM Cortex-A76) & Raspberry Pi 4 (ARM Cortex-A72).

Features:
- Precise GPIO Trigger synchronization (Compatible with Pi 5 via gpiozero / lgpio).
- Dry-run mode for testing on PCs / non-Pi hardware without crashing.
- 5 Standard Benign Workload Profiles (Idle, Cryptography, Compression, Math, Network).
- Configurable trace count, execution duration, and trigger pins.
- Append-only JSONL manifest with wall-clock bounds, so each trace can be joined
  to the EM capture that recorded it (see pico-em-capture/manifest_join.py).
- vcgencmd get_throttled gate: a throttled CPU invalidates the trace.

The manifest
------------
Every trace is recorded before any judgement is made about it, with the
wall-clock bounds the join needs:

    started_utc      before the per-trace settle
    trigger_on_utc   immediately before GPIO goes high
    trigger_off_utc  immediately after GPIO goes low
    finished_utc     after the trigger is released

`started_utc`..`finished_utc` is the interval a capture must fall inside, and
it deliberately starts before `trigger_on_utc`: the scope records pre-trigger
samples, so its window begins *before* the GPIO edge.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone

RUNNER_VERSION = "2.0.0"
MANIFEST_SCHEMA = 1

# Workload classes. `mode` is what the classifier sees, so it must name the
# workload and nothing else: a trace labelled "crypto" that actually ran idle
# is worse than a missing trace.
MODE_PREFIX = "goodware"

# -----------------------------------------------------------------------------
# GPIO Hardware Trigger Handler (Pi 5 & Pi 4 Compatible)
# -----------------------------------------------------------------------------
class HardwareTrigger:
    def __init__(self, pin=17, use_act_led=False, dry_run=False):
        self.pin = pin
        self.use_act_led = use_act_led
        self.dry_run = dry_run
        self.device = None
        self.original_trigger = None
        self.act_led_brightness_path = "/sys/class/leds/ACT/brightness"
        self.act_led_trigger_path = "/sys/class/leds/ACT/trigger"

        if self.use_act_led:
            if not self.dry_run:
                try:
                    # Check for fallback LED path (e.g., led0 on older kernel/models)
                    if not os.path.exists(self.act_led_trigger_path) and os.path.exists("/sys/class/leds/led0/trigger"):
                        self.act_led_trigger_path = "/sys/class/leds/led0/trigger"
                        self.act_led_brightness_path = "/sys/class/leds/led0/brightness"

                    if os.path.exists(self.act_led_trigger_path):
                        with open(self.act_led_trigger_path, "r") as f:
                            content = f.read()
                        match = re.search(r'\[(.*?)\]', content)
                        if match:
                            self.original_trigger = match.group(1)
                        else:
                            self.original_trigger = "mmc0"

                        with open(self.act_led_trigger_path, "w") as f:
                            f.write("none\n")
                        print(f"[HardwareTrigger] Initialized ACT LED ({self.act_led_brightness_path}). Kernel trigger disabled (was '{self.original_trigger}').")
                    else:
                        print("[HardwareTrigger] Warning: ACT LED path not found. Falling back to DRY-RUN mode.")
                        self.dry_run = True
                except Exception as e:
                    print(f"[HardwareTrigger] Warning: Could not initialize ACT LED ({e}). Falling back to DRY-RUN mode.")
                    self.dry_run = True
            else:
                print("[HardwareTrigger] Initialized ACT LED in DRY-RUN mode.")
        else:
            if not self.dry_run:
                try:
                    # gpiozero is the official standard for Raspberry Pi 5 (uses lgpio backend)
                    from gpiozero import OutputDevice
                    self.device = OutputDevice(self.pin, active_high=True, initial_value=False)
                    print(f"[HardwareTrigger] Initialized GPIO pin {self.pin} via gpiozero.")
                except (ImportError, Exception) as e:
                    print(f"[HardwareTrigger] Warning: Could not initialize GPIO ({e}). Falling back to DRY-RUN mode.")
                    self.dry_run = True

    def on(self):
        """Assert trigger ON (Start oscilloscope acquisition / Turn LED ON)"""
        if self.use_act_led:
            if not self.dry_run:
                try:
                    with open(self.act_led_brightness_path, "w") as f:
                        f.write("0\n")  # Active-Low: 0 = ON
                except Exception as e:
                    print(f"[HardwareTrigger] Error setting LED ON: {e}")
        else:
            if not self.dry_run and self.device:
                self.device.on()

    def off(self):
        """Assert trigger OFF (Stop oscilloscope acquisition / Turn LED OFF)"""
        if self.use_act_led:
            if not self.dry_run:
                try:
                    with open(self.act_led_brightness_path, "w") as f:
                        f.write("1\n")  # Active-Low: 1 = OFF
                except Exception as e:
                    print(f"[HardwareTrigger] Error setting LED OFF: {e}")
        else:
            if not self.dry_run and self.device:
                self.device.off()

    def cleanup(self):
        if self.use_act_led:
            if not self.dry_run:
                try:
                    # Turn off LED
                    with open(self.act_led_brightness_path, "w") as f:
                        f.write("1\n")
                    # Restore original kernel trigger
                    restore_trig = self.original_trigger if self.original_trigger else "mmc0"
                    if os.path.exists(self.act_led_trigger_path):
                        with open(self.act_led_trigger_path, "w") as f:
                            f.write(f"{restore_trig}\n")
                    print(f"[HardwareTrigger] Restored ACT LED trigger to '{restore_trig}'.")
                except Exception as e:
                    print(f"[HardwareTrigger] Error during ACT LED cleanup: {e}")
        else:
            if self.device:
                self.device.close()


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------
def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_throttled():
    """
    Return the raw `vcgencmd get_throttled` response, or None when the command
    cannot be run (not a Pi, no vcgencmd).

    None is distinct from "readable but non-zero": the caller has to decide,
    and on a Pi a missing vcgencmd is a broken environment, not a pass.
    """
    try:
        proc = subprocess.run(["vcgencmd", "get_throttled"],
                              capture_output=True, text=True, timeout=10,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout or "").strip() if proc.returncode == 0 else None


def throttle_state(response):
    """
    Parse the throttle mask. Returns a list of ints, empty if unreadable.

    Mirrors pico-em-capture/session.py: a substring search would accept
    "0x0" inside a longer non-zero value, and an empty response would pass.
    """
    return [int(v, 16) for v in re.findall(r"throttled\s*=\s*0x([0-9a-fA-F]+)",
                                           response or "")]


def assert_not_throttled(response, when):
    """Raise ValueError unless every reported throttle bit is clear."""
    values = throttle_state(response)
    if values and all(v == 0 for v in values):
        return
    if not values:
        raise ValueError(
            f"cannot read the throttle state {when}: got {response!r}. The "
            f"invariant needs 'throttled=0x0'; an unreadable answer is a "
            f"failure, not a pass."
        )
    raise ValueError(
        f"Pi is throttled {when}: {response!r}. The CPU clock is not stable, "
        f"so any trace captured now is invalid. Fix power/cooling and rerun. "
        f"(0x5000 = under-voltage now, 0x40000 = throttled since boot.)"
    )


def write_manifest_line(path, record):
    """Append one JSONL line. Append-only: nothing earlier is rewritten."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def read_manifest(path):
    """Trace records already in a manifest; [] when the file does not exist."""
    if not path or not os.path.exists(path):
        return []
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{lineno}: not valid JSON ({exc}); refusing to "
                    f"resume from a manifest this tool cannot read"
                ) from exc
    return [r for r in records if r.get("type", "trace") == "trace"]


def next_trace_index(records):
    indices = [int(r["trace_index"]) for r in records
               if isinstance(r.get("trace_index"), int)]
    return max(indices) + 1 if indices else 0


def _per_task_manifest(manifest_path, task):
    """
    `<name>.<task>.jsonl` next to the requested manifest, for `--task all`.

    Each task is its own cell, so it gets its own file: one file per cell is
    what makes "this trace ran under this workload" checkable at all.
    """
    stem, ext = os.path.splitext(manifest_path)
    return f"{stem}.{task}{ext or '.jsonl'}"


# -----------------------------------------------------------------------------
# Workload Definitions (Stdlib-first, Zero-bloat)
# -----------------------------------------------------------------------------

def workload_idle(duration=1.5):
    """Clean system baseline: minimal CPU activity to capture device noise floor."""
    time.sleep(duration)


def workload_crypto(duration=1.5):
    """
    Intensive ALU & register crypto benchmark.
    Uses hashlib (compiled C OpenSSL binding) executing continuous SHA-256 / PBKDF2 rounds.
    """
    start_time = time.perf_counter()
    data = b"IoT_SIDE_CHANNEL_ANALYSIS_BENCHMARK_GOODWARE_" * 2048  # 90 KB buffer
    iterations = 0
    while time.perf_counter() - start_time < duration:
        _ = hashlib.sha256(data).digest()
        iterations += 1
    return iterations


def workload_compress(duration=1.5):
    """
    Memory bus & string compression workload.
    Compresses pseudo-random textual data using zlib/deflate.
    """
    start_time = time.perf_counter()
    raw_chunk = (os.urandom(1024) + b"AAAABBBBCCCCDDDD" * 64) * 16  # ~80 KB
    iterations = 0
    while time.perf_counter() - start_time < duration:
        compressed = zlib.compress(raw_chunk, level=6)
        _ = zlib.decompress(compressed)
        iterations += 1
    return iterations


def workload_math(duration=1.5):
    """
    Floating-point ALU stress.
    Evaluates trigonometric and matrix math operations.
    """
    start_time = time.perf_counter()
    try:
        import numpy as np
        a = np.random.rand(256, 256).astype(np.float32)
        b = np.random.rand(256, 256).astype(np.float32)
        iterations = 0
        while time.perf_counter() - start_time < duration:
            _ = np.dot(a, b)
            iterations += 1
        return iterations
    except ImportError:
        # Fallback to pure python math if numpy is not installed
        import math
        iterations = 0
        while time.perf_counter() - start_time < duration:
            for x in range(10000):
                _ = math.sin(x) * math.cos(x)
            iterations += 1
        return iterations


def workload_network(duration=1.5):
    """
    Local loopback network socket I/O.
    Transfers UDP packets over 127.0.0.1 to profile network stack EM emissions safely.
    """
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_sock.bind(("127.0.0.1", 0))
    server_port = server_sock.getsockname()[1]
    server_sock.setblocking(False)

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    packet_payload = b"SAFE_GOODWARE_NETWORK_TELEMETRY_" * 32

    start_time = time.perf_counter()
    packets_sent = 0
    while time.perf_counter() - start_time < duration:
        client_sock.sendto(packet_payload, ("127.0.0.1", server_port))
        try:
            _, _ = server_sock.recvfrom(2048)
        except BlockingIOError:
            pass
        packets_sent += 1

    server_sock.close()
    client_sock.close()
    return packets_sent


def workload_keyboard(duration=1.5):
    """
    Synthetic keystroke workload for the console (VT) keyboard path.

    Needed because `kisni` hooks `register_keyboard_notifier()`: only events that
    reach `kbd_keycode()` in drivers/tty/vt/keyboard.c are logged, and SSH typing
    never enters that path. An SSH session therefore produces an idle trace that
    looks perfectly valid. This profile drives `keysynth` (uinput) so the workload
    is identical whether or not the module is loaded — which is what makes the
    `typing-only` cell a usable control.

    Configuration by environment, so the CLI stays compatible with the other
    profiles:
        EMLAB_KEYSYNTH          path to the keysynth binary (default: keysynth in PATH)
        EMLAB_KEYSYNTH_RATE     keys per second (default: 20, fixed across the campaign)
        EMLAB_KEYSYNTH_KEYFILE  keystroke sequence file, hashed into the manifest

    Fails loudly if the injector is missing. A silent fallback to `sleep()` would
    turn every "keyboard" trace into an idle trace without saying so.
    """
    keysynth = os.environ.get("EMLAB_KEYSYNTH", "keysynth")
    rate = os.environ.get("EMLAB_KEYSYNTH_RATE", "20")
    keyfile = os.environ.get("EMLAB_KEYSYNTH_KEYFILE")

    argv = [keysynth, "--rate", str(rate), "--duration", f"{duration:.3f}", "--quiet"]
    if keyfile:
        argv += ["--keyfile", keyfile]

    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=duration + 10, check=False)
    except FileNotFoundError:
        raise RuntimeError(
            f"keysynth not found ({keysynth!r}). Set EMLAB_KEYSYNTH to the built "
            f"binary, or build Keysniffer/tools/keysynth.c first. Refusing to run "
            f"an idle trace in place of a keyboard trace."
        ) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"keysynth did not finish within {duration + 10:.0f}s") from None
    except OSError as exc:
        # Covers "not executable", "wrong architecture", and the WinError 193
        # class of failure: the injector exists but cannot be run.
        raise RuntimeError(f"keysynth could not be executed ({keysynth!r}): {exc}") from None

    if proc.returncode != 0:
        raise RuntimeError(
            f"keysynth exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()}"
        )

    match = re.search(r"emitted=(\d+)", proc.stdout or "")
    if not match:
        raise RuntimeError(f"keysynth produced no emitted count: {proc.stdout!r}")
    return f"{match.group(1)} keystrokes"


# Registry of available tasks
WORKLOADS = {
    "idle": workload_idle,
    "crypto": workload_crypto,
    "compress": workload_compress,
    "math": workload_math,
    "network": workload_network,
    "keyboard": workload_keyboard,
}

# `--task all` deliberately excludes `keyboard`. The Bashlite and Gonnacry
# campaigns were captured with the five profiles above; adding a sixth would
# change the workload set and break comparability with those datasets. The
# keyboard profile also needs an external binary, so it would turn an unattended
# `--task all` into an abort on any host without keysynth. It is requested
# explicitly, per Keysniffer trace.
ALL_TASKS = ["idle", "crypto", "compress", "math", "network"]


# -----------------------------------------------------------------------------
# Main Runner Loop
# -----------------------------------------------------------------------------
def _trigger_label(trigger):
    if trigger.use_act_led:
        return f"ACT LED ({trigger.act_led_brightness_path})"
    return f"Pin {trigger.pin}"


def run_trace(index, task_name, duration, trigger, lead_in_s=0.05):
    """
    Execute one trace. Never raises for a workload failure: the record is the
    evidence that the trace happened at all, so it is written either way.

    The wall-clock bounds bracket the trigger, not merely the workload call.

    `started_utc` is taken before the lead-in and before `trigger.on()`, and
    both are deliberate. The scope records pre-trigger samples, so the EM
    capture starts *before* the GPIO edge. If this record claimed to start at
    the edge, the capture's window would begin before the runner's span and
    containment would fail - the trace would exist but not be joinable. The
    lead-in covers that pre-trigger interval.
    """
    record = {
        "type": "trace",
        "trace_index": index,
        "mode": f"{MODE_PREFIX}-{task_name}",
        "status": "ok",
        "started_utc": utc_now(),
        "lead_in_s": round(float(lead_in_s), 6),
        "trigger_on_utc": None,
        "trigger_off_utc": None,
        "finished_utc": None,
        "wall_s": None,
        "result": None,
        "dry_run": bool(trigger.dry_run),
        "notes": [],
    }

    # Let the scope arm and fill its pre-trigger buffer before the edge.
    if lead_in_s:
        time.sleep(lead_in_s)

    trigger.on()
    record["trigger_on_utc"] = utc_now()
    exec_start = time.perf_counter()
    try:
        result = WORKLOADS[task_name](duration=duration)
    except RuntimeError as exc:
        # A workload that cannot run is a failed trace, not a reason to
        # abandon the campaign silently. The record says why.
        record["status"] = "workload-failed"
        record["notes"].append(str(exc))
        result = None
    finally:
        trigger.off()
        record["trigger_off_utc"] = utc_now()
        record["wall_s"] = round(time.perf_counter() - exec_start, 6)
    record["result"] = result
    record["finished_utc"] = utc_now()
    return record


def run_benchmark(task_name, count, duration, trigger, cooldown=0.3,
                  manifest_path=None, resume=False, skip_throttle_check=False,
                  capture_duration=None, pre_trigger_s=0.005):
    workload_fn = WORKLOADS.get(task_name)
    if not workload_fn:
        print(f"Error: Unknown task '{task_name}'. Available: {list(WORKLOADS.keys())}")
        sys.exit(1)

    # The capture window comes from the scope, which this runner does not
    # control. Warn when the workload is shorter than it, because the capture
    # will then extend past the runner's recorded span and the join cannot
    # place it inside any trace.
    if capture_duration is not None and duration < float(capture_duration):
        print(
            f"[WARN] workload duration {duration:.2f}s is shorter than the "
            f"capture window {float(capture_duration):.2f}s. The EM capture "
            f"will start before and end after this trace's recorded span, so "
            f"it will not be joinable. Pass --duration >= the scope's "
            f"--duration."
        )

    existing = read_manifest(manifest_path) if manifest_path else []
    if existing and not resume:
        raise ValueError(
            f"{manifest_path} already holds {len(existing)} trace(s). Pass "
            f"--resume to continue that session, or choose a new --manifest "
            f"(or run directory) to start a separate one."
        )
    start_index = next_trace_index(existing) if existing else 0

    print("\n=======================================================")
    print(f" Goodware Acquisition Runner: {task_name.upper()}")
    print(f" Target Runs   : {count}")
    print(f" Trace Duration: {duration:.2f} seconds")
    print(f" GPIO Trigger  : {_trigger_label(trigger)} (Dry-run: {trigger.dry_run})")
    print(f" Cooldown      : {cooldown:.2f} seconds")
    if manifest_path:
        print(f" Manifest      : {manifest_path}"
              + (f" (resuming at {start_index})" if start_index else ""))
    print("=======================================================\n")

    throttle_before = read_throttled()
    if not skip_throttle_check:
        assert_not_throttled(throttle_before, "before the session")
    else:
        print("[WARN] --skip-throttle-check: the throttle invariant is NOT "
              "enforced. Do not label these traces as dataset.")

    # The lead-in must exceed the scope's pre-trigger interval, otherwise the
    # capture's window still starts before `started_utc`.
    lead_in_s = max(0.05, 2.0 * float(pre_trigger_s))

    if manifest_path:
        write_manifest_line(manifest_path, {
            "type": "header",
            "schema": MANIFEST_SCHEMA,
            "runner_version": RUNNER_VERSION,
            "started_utc": utc_now(),
            "resumed": bool(start_index),
            "start_index": start_index,
            "task": task_name,
            "mode_prefix": MODE_PREFIX,
            "count": count,
            "duration_s": duration,
            "cooldown_s": cooldown,
            "capture_duration_s": capture_duration,
            "pre_trigger_s": float(pre_trigger_s),
            "lead_in_s": lead_in_s,
            "trigger": {
                "kind": "act_led" if trigger.use_act_led else "gpio",
                "pin": None if trigger.use_act_led else trigger.pin,
                "dry_run": bool(trigger.dry_run),
            },
            "throttle_before": throttle_before,
            "throttle_checked": not skip_throttle_check,
            "host": {
                "node": socket.gethostname(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
        })

    # Initial settling time to stabilize CPU clock
    time.sleep(1.0)

    clean = failed = 0
    try:
        for offset in range(count):
            # trace_index is 0-based and continues across resumes, matching the
            # capture app and kisni_runner; the console shows 1-based progress.
            trace_index = start_index + offset
            print(f"[{offset + 1:04d}/{count:04d}] Arming Trigger -> "
                  f"Executing '{task_name}'...", end="", flush=True)

            record = run_trace(trace_index, task_name, duration, trigger,
                               lead_in_s=lead_in_s)
            if manifest_path:
                write_manifest_line(manifest_path, record)

            stat = record["result"] if record["result"] is not None else "OK"
            print(f" Done in {record['wall_s']:.3f}s (Stat: {stat})")

            if record["status"] == "ok":
                clean += 1
            else:
                failed += 1
                print(f"\n[Aborted] Trace {trace_index} failed: "
                      f"{record['notes'][0] if record['notes'] else 'unknown'}")
                print("No further traces run; the failed trace is in the manifest.\n")
                break

            # Inter-trace cooldown (allow CPU to return to baseline governor
            # frequency).
            time.sleep(cooldown)
    finally:
        throttle_after = None if skip_throttle_check else read_throttled()
        if manifest_path:
            write_manifest_line(manifest_path, {
                "type": "footer",
                "finished_utc": utc_now(),
                "clean": clean,
                "failed": failed,
                "throttle_after": throttle_after,
                "throttle_checked": not skip_throttle_check,
            })
        if not skip_throttle_check:
            assert_not_throttled(throttle_after, "after the session")

    if failed:
        print(f"\n[Completed] {clean}/{clean + failed} traces of '{task_name}'.\n")
        return False
    print(f"\n[Completed] Successfully executed {clean} traces of '{task_name}'.\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Side-Channel Goodware Benchmark & GPIO Trigger Runner")
    parser.add_argument(
        "--task", "-t",
        choices=["all"] + list(WORKLOADS.keys()),
        default="crypto",
        help="Specific goodware task to run (default: crypto, or 'all' to cycle through each)"
    )
    parser.add_argument(
        "--count", "-c",
        type=int,
        default=10,
        help="Number of traces/repetitions to capture (default: 10)"
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=1.5,
        help="Execution duration in seconds per trace (default: 1.5s)"
    )
    parser.add_argument(
        "--gpio-pin", "-p",
        type=int,
        default=17,
        help="Raspberry Pi GPIO BCM pin number for hardware trigger (default: GPIO 17 / Pin 11)"
    )
    parser.add_argument(
        "--use-act-led",
        action="store_true",
        help="Use Raspberry Pi 5 On-board ACT LED as physical trigger (Active-Low: 0=ON, 1=OFF)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force dry-run mode (skips physical GPIO toggling for testing on PC)"
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=0.3,
        help="Cooldown pause between traces in seconds (default: 0.3s)"
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Append-only JSONL manifest for this session. Default: "
             "goodware_manifest_<utc>.jsonl in the current directory. The "
             "manifest is what lets a capture be joined to the trace that "
             "produced it, so a campaign without one cannot be analysed."
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Write the manifest to <run-dir>/manifest.jsonl (overrides "
             "--manifest)."
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue an existing manifest at max(trace_index)+1 instead of "
             "refusing a non-empty one."
    )
    parser.add_argument(
        "--capture-duration",
        type=float,
        default=None,
        help="The scope's capture window in seconds, recorded in the manifest "
             "header. When it is longer than --duration the capture extends "
             "past this trace's span and cannot be joined; a warning is printed."
    )
    parser.add_argument(
        "--pre-trigger",
        type=float,
        default=0.005,
        help="The scope's pre-trigger interval in seconds (default: 0.005 = "
             "the capture app's 10,000 samples at 2 MHz). The runner waits at "
             "least twice this before the GPIO edge so the capture's window "
             "starts inside the trace's recorded span. Recorded in the header."
    )
    parser.add_argument(
        "--skip-throttle-check",
        action="store_true",
        help="Do not run vcgencmd get_throttled. ONLY valid on a host without "
             "vcgencmd (a dry run on a PC); never for dataset capture."
    )

    args = parser.parse_args()

    if args.manifest and args.run_dir:
        parser.error("--manifest and --run-dir are mutually exclusive")
    manifest_path = args.manifest
    if args.run_dir:
        os.makedirs(args.run_dir, exist_ok=True)
        manifest_path = os.path.join(args.run_dir, "manifest.jsonl")
    if not manifest_path:
        manifest_path = f"goodware_manifest_{stamp()}.jsonl"

    # dry_run=True in the trigger OR no vcgencmd means the throttle gate cannot
    # be enforced. Refuse to pretend otherwise unless the operator asked.
    if not args.skip_throttle_check and read_throttled() is None:
        parser.error(
            "vcgencmd get_throttled is unavailable, so the throttle invariant "
            "cannot be checked. This is expected on a PC; pass "
            "--skip-throttle-check for a rehearsal, and leave it off on the Pi."
        )

    trigger = HardwareTrigger(pin=args.gpio_pin, use_act_led=args.use_act_led, dry_run=args.dry_run)

    ok = True
    try:
        if args.task == "all":
            for task in ALL_TASKS:
                # One manifest per cell. Sharing one file across five tasks
                # would make the first task's traces look like a manifest that
                # the second task is about to append to, which is exactly the
                # mixed-configuration case the refusal exists for.
                cell_manifest = _per_task_manifest(manifest_path, task)
                if not run_benchmark(task, args.count, args.duration, trigger,
                                     args.cooldown, manifest_path=cell_manifest,
                                     resume=args.resume,
                                     skip_throttle_check=args.skip_throttle_check,
                                     capture_duration=args.capture_duration,
                                     pre_trigger_s=args.pre_trigger):
                    ok = False
                    break
        else:
            ok = run_benchmark(args.task, args.count, args.duration, trigger,
                               args.cooldown, manifest_path=manifest_path,
                               resume=args.resume,
                               skip_throttle_check=args.skip_throttle_check,
                               capture_duration=args.capture_duration,
                               pre_trigger_s=args.pre_trigger)
    except KeyboardInterrupt:
        print("\n[Interrupted] Execution aborted by user.")
        ok = False
    except ValueError as exc:
        print(f"\n[REFUSED] {exc}")
        ok = False
    finally:
        trigger.off()
        trigger.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
