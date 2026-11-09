#!/usr/bin/env python3
"""
Goodware Workload Runner & Hardware GPIO Trigger for Side-Channel Analysis
Designed for Raspberry Pi 5 (ARM Cortex-A76) & Raspberry Pi 4 (ARM Cortex-A72).

Features:
- Precise GPIO Trigger synchronization (Compatible with Pi 5 via gpiozero / lgpio).
- Dry-run mode for testing on PCs / non-Pi hardware without crashing.
- 5 Standard Benign Workload Profiles (Idle, Cryptography, Compression, Math, Network).
- Configurable trace count, execution duration, and trigger pins.
"""

import argparse
import hashlib
import os
import re
import socket
import subprocess
import sys
import time
import zlib

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
def run_benchmark(task_name, count, duration, trigger, cooldown=0.3):
    workload_fn = WORKLOADS.get(task_name)
    if not workload_fn:
        print(f"Error: Unknown task '{task_name}'. Available: {list(WORKLOADS.keys())}")
        sys.exit(1)

    print("\n=======================================================")
    print(f" Goodware Acquisition Runner: {task_name.upper()}")
    print(f" Target Runs   : {count}")
    print(f" Trace Duration: {duration:.2f} seconds")
    trigger_desc = f"ACT LED ({trigger.act_led_brightness_path})" if trigger.use_act_led else f"Pin {trigger.pin}"
    print(f" GPIO Trigger  : {trigger_desc} (Dry-run: {trigger.dry_run})")
    print(f" Cooldown      : {cooldown:.2f} seconds")
    print("=======================================================\n")

    # Initial settling time to stabilize CPU clock
    time.sleep(1.0)

    for run_idx in range(1, count + 1):
        print(f"[{run_idx:04d}/{count:04d}] Arming Trigger -> Executing '{task_name}'...", end="", flush=True)

        # 1. Start Trigger (GPIO HIGH)
        trigger.on()

        # 2. Execute Workload
        exec_start = time.perf_counter()
        try:
            result = workload_fn(duration=duration)
        except RuntimeError as exc:
            # A workload that cannot run is a failed trace, not a reason to
            # abandon the campaign: stop here and report, so the remaining
            # traces are not silently recorded as idle.
            trigger.off()
            print(f" FAILED\n[Error] {exc}")
            print(f"\n[Aborted] Trace {run_idx} failed; no further traces run.\n")
            return False
        exec_end = time.perf_counter()

        # 3. Stop Trigger (GPIO LOW)
        trigger.off()

        actual_duration = exec_end - exec_start
        print(f" Done in {actual_duration:.3f}s (Stat: {result if result is not None else 'OK'})")

        # 4. Inter-trace Cooldown (allow CPU to return to baseline governor frequency)
        time.sleep(cooldown)

    print(f"\n[Completed] Successfully executed {count} traces of '{task_name}'.\n")
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

    args = parser.parse_args()

    trigger = HardwareTrigger(pin=args.gpio_pin, use_act_led=args.use_act_led, dry_run=args.dry_run)

    ok = True
    try:
        if args.task == "all":
            for task in ALL_TASKS:
                if not run_benchmark(task, args.count, args.duration, trigger, args.cooldown):
                    ok = False
                    break
        else:
            ok = run_benchmark(args.task, args.count, args.duration, trigger, args.cooldown)
    except KeyboardInterrupt:
        print("\n[Interrupted] Execution aborted by user.")
        ok = False
    finally:
        trigger.off()
        trigger.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
