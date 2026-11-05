#!/usr/bin/env python3
"""
Bashlite Level C — Real In-the-Wild Sample Runner for Side-Channel Analysis
Designed for Raspberry Pi 5 (ARM Cortex-A76) & Raspberry Pi 4 (ARM Cortex-A72).

Purpose
-------
Execute a genuine Bashlite (a.k.a. Qbot / Lizkebash / BASHLITE) IoT botnet sample
under controlled conditions while capturing its electromagnetic signature via a
GPIO-synchronized oscilloscope trigger. The intent is defensive / academic: to
build a labeled EM trace dataset (goodware vs malware) for a classifier that
distinguishes benign from malicious IoT software.

Design alignment with goodware_runner.py
-----------------------------------------
This runner mirrors goodware_runner.py exactly where it matters for trace
comparability:
  * Same HardwareTrigger class (GPIO 17 or ACT LED).
  * Same trace loop: arm trigger -> execute workload -> drop trigger -> cooldown.
  * Same --count / --duration / --gpio-pin / --use-act-led / --dry-run / --cooldown CLI.
  * Same 1.5 s default measurement window and 0.3 s cooldown.
  * Same dry-run fallback for non-Pi hardware.

Safety controls (read before running)
-------------------------------------
1.  Bashlite is real malware. Its purpose is Telnet brute-force propagation and
    DDoS flooding. NEVER run it on a network you do not own, or with outbound
    connectivity to the internet.
2.  Run only as the dedicated unprivileged `victim` account (see Gonnacry run 3,
    Section 5.1). This account must have no SSH access and no data of value.
3.  Network containment must be ACTIVE and verified before any real sample run:
        sudo iptables -L OUTPUT -n -v   # confirm non-zero drop counters on
                                        # tcp 23, tcp 2323, tcp 80, udp 53
    The Pi 5 provisioning already installs these rules (pi5_setup_report.md §5).
4.  Use --dry-run for all development and trigger-timing validation on non-Pi
    hardware. Dry-run skips GPIO toggling and does not execute the sample.
5.  Verify the sample SHA-256 before execution. Record the exact hash in your
    thesis — results are not reproducible without it.
6.  Bashlite attempts C2 connection and scanning. Because outbound ports 23/2323/
    80/53 are dropped by iptables, the sample will fail to reach real targets,
    but its own CPU/network-stack activity still produces an EM signature. That
    is what this runner captures.
7.  Keep execution time-bounded. This runner kills the sample after `--duration`
    seconds per trace and never lets it run unattended.

Forced observable activity
--------------------------
The weekly report (run 3) warns: an idle bot produces a trace indistinguishable
from benign activity. Bashlite's natural behavior is: connect to C2, attempt
Telnet scans, flood targets. With containment in place those network actions
fail quickly, but the binary still spins its main loop, retries connections,
and performs socket/syscall work — that is observable activity and is exactly
what we capture. No synthetic payload is injected; we run the real sample.

Expected file layout on the Pi 5::

    ~/work/bashlite/
        bashlite_runner.py        <- this file
        samples/
            bashlite.bin          <- real in-the-wild Bashlite ELF (static aarch64)
            sha256.txt            <- `sha256sum bashlite.bin`
    ~/work/victim_home/           <- $HOME of the `victim` account, regenerated
                                      deterministically between runs (see honeypot
                                      regeneration script, outstanding work)

Run (from the Pi 5, as the operator, then drop to victim)::

    python3 bashlite_runner.py \
        --task bashlite \
        --sample ~/work/bashlite/samples/bashlite.bin \
        --count 30 \
        --duration 2.5 \
        --gpio-pin 17 \
        --cooldown 0.5

Verify containment first::

    sudo iptables -L OUTPUT -n -v   # non-zero counters on DROP rules
"""

import argparse
import hashlib
import os
import signal
import subprocess
import sys
import time

# -----------------------------------------------------------------------------
# GPIO Hardware Trigger Handler (identical interface to goodware_runner.py)
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
                    if not os.path.exists(self.act_led_trigger_path) and os.path.exists("/sys/class/leds/led0/trigger"):
                        self.act_led_trigger_path = "/sys/class/leds/led0/trigger"
                        self.act_led_brightness_path = "/sys/class/leds/led0/brightness"

                    if os.path.exists(self.act_led_trigger_path):
                        with open(self.act_led_trigger_path, "r") as f:
                            import re
                            content = f.read()
                            match = re.search(r"\[(.*?)\]", content)
                            if match:
                                self.original_trigger = match.group(1)
                            else:
                                self.original_trigger = "mmc0"

                        with open(self.act_led_trigger_path, "w") as f:
                            f.write("none\n")
                        print(f"[HardwareTrigger] Initialized ACT LED ({self.act_led_brightness_path}). "
                              f"Kernel trigger disabled (was '{self.original_trigger}').")
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
                    with open(self.act_led_brightness_path, "w") as f:
                        f.write("1\n")
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
# Bashlite workload
# -----------------------------------------------------------------------------
def verify_sample(sample_path, expected_hash=None):
    """Return (ok, sha256_hex). Abort with clear message on missing/tampered sample."""
    if not os.path.isfile(sample_path):
        print(f"[Bashlite] ERROR: sample not found: {sample_path}")
        return False, None
    sha = hashlib.sha256()
    with open(sample_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    digest = sha.hexdigest()
    print(f"[Bashlite] Sample SHA-256: {digest}")
    if expected_hash and digest.lower() != expected_hash.lower():
        print(f"[Bashlite] ERROR: hash mismatch! Expected {expected_hash}, got {digest}")
        return False, digest
    return True, digest


def workload_bashlite(sample_path, duration, dry_run=False):
    """
    Execute the real Bashlite sample for `duration` seconds, then terminate it.

    The sample is launched as-is (no arguments, no C2 credentials). Because
    outbound containment blocks ports 23/2323/80/53, the bot cannot reach real
    targets or C2; its own retry/scan/beacon loop produces the observable
    EM activity we capture.

    Returns a dict with run statistics (pid, exit_code, killed, duration).
    """
    result = {
        "pid": None,
        "exit_code": None,
        "killed": False,
        "duration": 0.0,
        "stdout": "",
        "stderr": "",
    }

    if dry_run:
        print("[Bashlite] DRY-RUN: would execute sample, skipping.")
        time.sleep(duration)
        result["duration"] = duration
        return result

    exec_start = time.perf_counter()
    proc = None
    try:
        proc = subprocess.Popen(
            [sample_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach so we can kill the whole process group
        )
        result["pid"] = proc.pid

        # Let it run for the measurement window, then terminate.
        try:
            stdout, stderr = proc.communicate(timeout=duration)
            result["stdout"] = stdout.decode("utf-8", errors="replace")
            result["stderr"] = stderr.decode("utf-8", errors="replace")
            result["exit_code"] = proc.returncode
        except subprocess.TimeoutExpired:
            # Bashlite is expected to run until we stop it; kill the process group.
            result["killed"] = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    proc.wait(timeout=5)
                except Exception:
                    pass
            result["exit_code"] = proc.returncode
            try:
                stdout, stderr = proc.communicate(timeout=2)
                result["stdout"] = stdout.decode("utf-8", errors="replace")
                result["stderr"] = stderr.decode("utf-8", errors="replace")
            except Exception:
                pass

    except Exception as e:
        print(f"[Bashlite] ERROR executing sample: {e}")
        result["stderr"] = str(e)

    result["duration"] = time.perf_counter() - exec_start
    return result


# -----------------------------------------------------------------------------
# Containment pre-flight check
# -----------------------------------------------------------------------------
def check_containment():
    """Best-effort check that key outbound DROP rules exist and are active."""
    try:
        out = subprocess.check_output(["sudo", "iptables", "-L", "OUTPUT", "-n", "-v"],
                                      stderr=subprocess.DEVNULL, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError, PermissionError):
        print("[Bashlite] WARNING: could not read iptables rules (sudo/iptables unavailable). "
              "Proceed at your own risk — ensure containment is active manually.")
        return False

    required = {23, 2323, 80, 53}
    found = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 9 and parts[1] == "DROP":
            # "tcp dpt:23" / "udp dpt:53"
            for i, p in enumerate(parts):
                if p == "dpt:" and i + 1 < len(parts):
                    try:
                        found.add(int(parts[i + 1]))
                    except ValueError:
                        pass

    missing = required - found
    if missing:
        print(f"[Bashlite] WARNING: no active DROP rule for ports {sorted(missing)}. "
              "Containment may be incomplete — do NOT run the real sample on a shared network.")
        return False
    print("[Bashlite] Containment pre-flight OK: DROP rules present for tcp 23, 2323, 80 and udp 53.")
    return True


# -----------------------------------------------------------------------------
# Main runner loop (mirrors goodware_runner.run_benchmark)
# -----------------------------------------------------------------------------
def run_bashlite(sample_path, count, duration, trigger, cooldown=0.3,
                 expected_hash=None, dry_run=False):
    print(f"\n=======================================================")
    print(f" Bashlite Level C — Real In-the-Wild Sample Runner")
    print(f" Sample        : {sample_path}")
    print(f" Target Runs   : {count}")
    print(f" Trace Duration: {duration:.2f} seconds")
    trigger_desc = f"ACT LED ({trigger.act_led_brightness_path})" if trigger.use_act_led else f"Pin {trigger.pin}"
    print(f" GPIO Trigger  : {trigger_desc} (Dry-run: {trigger.dry_run})")
    print(f" Cooldown      : {cooldown:.2f} seconds")
    print(f"=======================================================\n")

    ok, digest = verify_sample(sample_path, expected_hash)
    if not ok:
        print("[Bashlite] Aborting: sample verification failed. Record the correct hash and re-run.")
        return

    if not dry_run:
        print("[Bashlite] Running containment pre-flight check...")
        check_containment()
        print()

    # Initial settling time to stabilize CPU clock (matches goodware_runner).
    time.sleep(1.0)

    for run_idx in range(1, count + 1):
        print(f"[{run_idx:04d}/{count:04d}] Arming Trigger -> Executing Bashlite...", end="", flush=True)

        # 1. Start Trigger (GPIO HIGH)
        trigger.on()

        # 2. Execute workload (Bashlite sample, time-bounded)
        stats = workload_bashlite(sample_path, duration, dry_run=dry_run)

        # 3. Stop Trigger (GPIO LOW)
        trigger.off()

        killed_tag = " [KILLED:timeout]" if stats["killed"] else ""
        pid_tag = f" pid={stats['pid']}" if stats["pid"] else ""
        print(f" Done in {stats['duration']:.3f}s (exit={stats['exit_code']}{killed_tag}{pid_tag})")

        # 4. Inter-trace cooldown (allow CPU to return to baseline governor frequency)
        time.sleep(cooldown)

    print(f"\n[Completed] Executed {count} traces of Bashlite.\n")
    if not dry_run:
        print("[Bashlite] Reminder: regenerate the victim honeypot directory between runs "
              "if files were modified, and re-verify containment counters.")


def main():
    parser = argparse.ArgumentParser(
        description="Bashlite Level C — Real In-the-Wild Sample Runner & GPIO Trigger (Side-Channel Analysis)"
    )
    parser.add_argument(
        "--sample", "-s",
        required=True,
        help="Path to the real Bashlite ELF sample (static aarch64 binary)."
    )
    parser.add_argument(
        "--expected-hash",
        help="Expected SHA-256 of the sample. Aborts on mismatch (recommended)."
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
        default=2.5,
        help="Execution duration in seconds per trace (default: 2.5s)"
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
        help="Force dry-run mode (skips GPIO toggling and sample execution for testing)"
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=0.5,
        help="Cooldown pause between traces in seconds (default: 0.5s)"
    )
    parser.add_argument(
        "--skip-containment-check",
        action="store_true",
        help="Skip the iptables pre-flight check (NOT recommended for real-sample runs)"
    )

    args = parser.parse_args()

    trigger = HardwareTrigger(pin=args.gpio_pin, use_act_led=args.use_act_led, dry_run=args.dry_run)

    try:
        run_bashlite(
            sample_path=args.sample,
            count=args.count,
            duration=args.duration,
            trigger=trigger,
            cooldown=args.cooldown,
            expected_hash=args.expected_hash,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        print("\n[Interrupted] Execution aborted by user.")
    finally:
        trigger.off()
        trigger.cleanup()


if __name__ == "__main__":
    main()
