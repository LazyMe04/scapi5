#!/usr/bin/env python3
"""
Bashlite EM Measurement Runner - VM rehearsal / Pi 5 capture (v2).

Purpose
-------
Run a Bashlite sample under a time-bounded, GPIO-synchronized capture window so
that electromagnetic traces for the malware class are directly comparable with
the goodware traces produced by ``goodware_runner.py`` (same trigger pin, same
edges, same settle/cooldown timing).

The VM does NOT produce EM data. A QEMU guest only validates the *workflow*:
start -> time-bound -> kill -> leftover sweep -> manifest. Real capture happens
on the Raspberry Pi 5 with the oscilloscope on GPIO 17 (or the ACT LED).

Design notes (v2 - changes from third_run/bashlite_runner.py)
-------------------------------------------------------------
* ``--software-trigger``  decouples "no GPIO available" from "do not execute".
  v2 never silently turns an execution into a dry run when GPIO init fails;
  a failed GPIO init only disables the pin, and is recorded in the manifest.
* ``--execute`` required  for any real sample execution (default is dry run).
* ``--expected-hash``     required for ``--execute``; recorded in the manifest.
* Containment check       now parses real ``iptables -S OUTPUT`` output
  (``-A OUTPUT -p tcp -m tcp --dport 23 -j DROP``), understands policy DROP,
  catch-all DROP rules, ``--dports`` multiport lists, and refuses to count an
  unconditional ACCEPT rule as containment. IPv4 and IPv6 are both checked.
* Leftover sweep          every launched process carries a per-run environment
  marker; after each trace the runner scans /proc for that marker and kills
  survivors, which catches a sample that daemonizes with setsid().
* Manifest                JSON per invocation: sample hash/ELF arch, containment
  verdict, per-trace timings, exit codes, killed leftovers, warnings.
* Dry run                 no longer requires the sample file to exist.
* ``--skip-containment-check`` is actually wired to the safety gate, and a
  second, narrower override (``--allow-partial-containment``) exists for the
  per-port-rule setup used on the Pi.

Safety model
------------
Bashlite is real malware (Telnet brute force, DDoS flooding, C2). It must only
ever run:
  1. on isolated hardware or in a disposable VM with outbound traffic dropped,
  2. as an unprivileged account (the Pi uses ``victim``; the VM uses ``ubuntu``),
  3. for a bounded time window, followed by a leftover-process sweep.

This runner refuses to execute when: it is not Linux, it is running as root
(unless ``--allow-root``), the sample hash does not match, or the containment
verdict is not "full" and no explicit override flag was given.

Usage
-----
Dry run (safe on any host, no sample needed)::

    python3 bashlite_runner.py --sample samples/bashlite.bin --count 2

VM rehearsal with the safe mimic, no GPIO::

    python3 bashlite_runner.py --sample ~/work/bashlite_mimic \\
        --expected-hash <sha256> --execute --software-trigger \\
        --count 2 --duration 2.5 --manifest ~/work/mimic_manifest.json

Pi 5 capture (operator drops to victim first)::

    sudo -u victim python3 bashlite_runner.py \\
        --sample /home/victim/work/samples/bashlite.bin \\
        --expected-hash <sha256> --execute \\
        --gpio-pin 17 --count 30 --duration 2.5 --cooldown 0.5
"""

import argparse
import hashlib
import ipaddress
import json
import os
import platform
import re
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

RUNNER_VERSION = "2.0.0"
MANIFEST_SCHEMA = 2

# (protocol number, port) that Bashlite uses for C2 / scanning / flooding.
# 6 = TCP, 17 = UDP.
#
# 999 is the C2 port hardcoded in this bench's accepted sample
# (349d2476…b777: "181.214.147.11:999", reached by initConnection). It only
# affects the 'partial' branch: a default-DROP policy is enough for 'full', but
# a per-port ruleset (--allow-partial-containment) must cover this port or the
# sample's own C2 traffic is unaccounted for.
REQUIRED_PORTS = ((6, 999), (6, 23), (6, 2323), (6, 80), (17, 53))
PROTO_NAMES = {6: "tcp", 17: "udp"}

ELF_MACHINES = {
    3: "Intel 80386 (x86)",
    8: "MIPS",
    20: "PowerPC",
    40: "ARM (32-bit, EABI)",
    62: "AMD x86-64",
    183: "AArch64 (ARM64)",
}

RUN_ENV_MARKER = "EMLAB_RUN_ID"


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------
def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def is_linux():
    return sys.platform.startswith("linux")


def effective_uid():
    return os.geteuid() if hasattr(os, "geteuid") else None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# -----------------------------------------------------------------------------
# Triggers
# -----------------------------------------------------------------------------
class SoftwareTrigger:
    """No-op physical trigger that still records edge timestamps.

    Used for VM rehearsal. The recorded on/off deltas prove that the capture
    window is bounded even though no pin is toggled.
    """

    mode = "software"

    def __init__(self):
        self.pin = None
        self.use_act_led = False
        self.available = True
        self.edges = []
        self._armed = False

    def _mark(self, label):
        self.edges.append({
            "label": label,
            "perf_counter": time.perf_counter(),
            "utc": utc_now(),
        })

    def on(self):
        self._armed = True
        self._mark("on")

    def off(self):
        if not self._armed:
            return
        self._armed = False
        self._mark("off")

    def cleanup(self):
        pass

    def describe(self):
        return "software (no GPIO toggled - VM rehearsal only; no EM trace)"


class HardwareTrigger:
    """GPIO / ACT LED trigger, identical semantics to goodware_runner.py.

    Toggling is active-high on the GPIO pin and active-low on the ACT LED, so
    malware and goodware traces see the same edge polarity and the same pin.
    """

    mode = "hardware"

    def __init__(self, pin=17, use_act_led=False):
        self.pin = pin
        self.use_act_led = use_act_led
        self.device = None
        self.available = True
        self.original_trigger = None
        self.edges = []
        self._armed = False
        self.act_led_brightness_path = "/sys/class/leds/ACT/brightness"
        self.act_led_trigger_path = "/sys/class/leds/ACT/trigger"

        if self.use_act_led:
            try:
                if not os.path.exists(self.act_led_trigger_path) and \
                        os.path.exists("/sys/class/leds/led0/trigger"):
                    self.act_led_trigger_path = "/sys/class/leds/led0/trigger"
                    self.act_led_brightness_path = "/sys/class/leds/led0/brightness"

                if os.path.exists(self.act_led_trigger_path):
                    with open(self.act_led_trigger_path, "r") as fh:
                        match = re.search(r"\[(.*?)\]", fh.read())
                    self.original_trigger = match.group(1) if match else "mmc0"
                    with open(self.act_led_trigger_path, "w") as fh:
                        fh.write("none\n")
                    print(f"[Trigger] ACT LED ready ({self.act_led_brightness_path}); "
                          f"kernel trigger disabled (was '{self.original_trigger}').")
                else:
                    print("[Trigger] WARNING: ACT LED path not found; trigger disabled. "
                          "Setback: capture will not be synchronized.")
                    self.available = False
            except Exception as exc:  # noqa: BLE001 - report and degrade, never hide
                print(f"[Trigger] WARNING: ACT LED init failed ({exc}); trigger disabled.")
                self.available = False
        else:
            try:
                from gpiozero import OutputDevice  # type: ignore
                self.device = OutputDevice(self.pin, active_high=True, initial_value=False)
                print(f"[Trigger] GPIO pin {self.pin} ready via gpiozero.")
            except Exception as exc:  # noqa: BLE001
                print(f"[Trigger] WARNING: GPIO init failed ({exc}); trigger disabled. "
                      "Execution is NOT downgraded to dry run - only the pin is off.")
                self.available = False

    def _mark(self, label):
        self.edges.append({
            "label": label,
            "perf_counter": time.perf_counter(),
            "utc": utc_now(),
        })

    def on(self):
        self._armed = True
        self._mark("on")
        if not self.available:
            return
        if self.use_act_led:
            try:
                with open(self.act_led_brightness_path, "w") as fh:
                    fh.write("0\n")  # active-low: 0 = ON
            except Exception as exc:  # noqa: BLE001
                print(f"[Trigger] Error setting LED ON: {exc}")
        elif self.device:
            self.device.on()

    def off(self):
        if not self._armed:
            return
        self._armed = False
        self._mark("off")
        if not self.available:
            return
        if self.use_act_led:
            try:
                with open(self.act_led_brightness_path, "w") as fh:
                    fh.write("1\n")  # active-low: 1 = OFF
            except Exception as exc:  # noqa: BLE001
                print(f"[Trigger] Error setting LED OFF: {exc}")
        elif self.device:
            self.device.off()

    def cleanup(self):
        if not self.available:
            return
        if self.use_act_led:
            try:
                with open(self.act_led_brightness_path, "w") as fh:
                    fh.write("1\n")
                restore = self.original_trigger or "mmc0"
                if os.path.exists(self.act_led_trigger_path):
                    with open(self.act_led_trigger_path, "w") as fh:
                        fh.write(f"{restore}\n")
                print(f"[Trigger] Restored ACT LED trigger to '{restore}'.")
            except Exception as exc:  # noqa: BLE001
                print(f"[Trigger] Error during ACT LED cleanup: {exc}")
        elif self.device:
            self.device.close()

    def describe(self):
        if not self.available:
            return f"hardware UNAVAILABLE (pin {self.pin if not self.use_act_led else 'ACT LED'})"
        if self.use_act_led:
            return f"ACT LED ({self.act_led_brightness_path}, active-low)"
        return f"GPIO {self.pin} (active-high)"


def make_trigger(args):
    if args.software_trigger:
        return SoftwareTrigger()
    return HardwareTrigger(pin=args.gpio_pin, use_act_led=args.use_act_led)


# -----------------------------------------------------------------------------
# Sample verification
# -----------------------------------------------------------------------------
def read_elf_info(path):
    """Return a small ELF descriptor, or {'is_elf': False} for non-ELF files."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(20)
    except OSError as exc:
        return {"is_elf": False, "error": str(exc)}

    if len(header) < 20 or header[:4] != b"\x7fELF":
        return {"is_elf": False}

    ei_class = header[4]
    ei_data = header[5]
    endian = "<" if ei_data == 1 else ">"
    machine = struct.unpack(endian + "H", header[18:20])[0]
    return {
        "is_elf": True,
        "class": "ELF64" if ei_class == 2 else "ELF32",
        "endian": "little" if ei_data == 1 else "big",
        "e_machine": machine,
        "machine": ELF_MACHINES.get(machine, f"unknown ({machine})"),
    }


def verify_sample(path, expected_hash):
    """Return (info_dict, errors, warnings). Never executes anything."""
    info = {"path": os.path.abspath(path), "exists": False}
    errors = []
    warnings = []

    if not os.path.isfile(path):
        info["error"] = "file not found"
        errors.append(f"sample not found: {path}")
        return info, errors, warnings

    info["exists"] = True
    info["size_bytes"] = os.path.getsize(path)
    info["sha256"] = sha256_file(path)
    info["executable"] = os.access(path, os.X_OK)
    info["elf"] = read_elf_info(path)
    info["modified_utc"] = datetime.fromtimestamp(
        os.path.getmtime(path), timezone.utc).isoformat(timespec="seconds")

    if expected_hash:
        info["expected_sha256"] = expected_hash.lower()
        if info["sha256"] != expected_hash.lower():
            errors.append(
                f"SHA-256 mismatch: expected {expected_hash.lower()}, got {info['sha256']}")
    if not info["executable"]:
        errors.append("sample is not executable (chmod +x) - Bashlite must be launched directly")
    if not info["elf"]["is_elf"]:
        warnings.append("sample is not an ELF file; arch check skipped")

    return info, errors, warnings


# -----------------------------------------------------------------------------
# Containment check (iptables / ip6tables)
# -----------------------------------------------------------------------------
def _sudo_prefix():
    """Prefer passwordless sudo for read-only iptables queries; root raises no prefix."""
    if not hasattr(os, "geteuid"):
        return []
    if os.geteuid() == 0:
        return []
    return ["sudo", "-n"]


def _rule_target(rule):
    match = re.search(r"-j\s+(\w+)", rule)
    return match.group(1).upper() if match else None


def _rule_proto(rule):
    match = re.search(r"(?:^|\s)-p\s+(\w+)", rule)
    return match.group(1).lower() if match else None


def _rule_is_local_only(rule):
    """True when a rule only covers loopback traffic."""
    if re.search(r"(?:^|\s)-o\s+lo(?:\s|$)", rule):
        return True
    if re.search(r"(?:^|\s)-d\s+127\.", rule):
        return True
    if "::1" in rule:
        return True
    return False


# Ranges a lab bench is allowed to reach. Anything a sample can only reach inside
# these ranges cannot leave the bench link, so an ACCEPT rule scoped to them is
# not "open egress" in the sense that matters here.
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::1/128"),
]


def _destinations(rule):
    """All addresses a rule's -d matches, as ip_network objects (empty if unparseable)."""
    nets = []
    for match in re.finditer(r"(?:^|\s)-d\s+(\S+)", rule):
        try:
            nets.append(ipaddress.ip_network(match.group(1), strict=False))
        except ValueError:
            continue
    return nets


def _rule_scoped_to_bench(rule):
    """True when every -d target of the rule is inside a private/bench range.

    An ACCEPT rule with no -d, with 0.0.0.0/0, or with a public address opens a
    path off the bench and is NOT considered scoped.
    """
    nets = _destinations(rule)
    if not nets:
        return False
    for net in nets:
        if net.prefixlen == 0:
            return False
        allowed_same_family = [n for n in _PRIVATE_NETS if n.version == net.version]
        if not any(net.subnet_of(n) for n in allowed_same_family):
            return False
    return True


def _rule_ports(rule):
    """Return the set of destination ports a rule matches, or None if unrestricted."""
    ports = set()
    for match in re.finditer(r"--dports?\s+([0-9,:]+)", rule):
        for item in match.group(1).split(","):
            head = item.split(":")[0]
            if head.isdigit():
                ports.add(int(head))
    if ports:
        return ports
    if "--dport" in rule or "--dports" in rule:
        return set()
    return None


def _rule_is_catch_all_drop(rule):
    if _rule_target(rule) not in ("DROP", "REJECT"):
        return False
    if _rule_is_local_only(rule):
        return False
    return (_rule_proto(rule) is None
            and _rule_ports(rule) is None
            and "--dport" not in rule
            and "-s " not in rule and "-d " not in rule)


def _rule_opens_path(rule):
    """An ACCEPT rule opens egress unless it is loopback / stateful / bench-scoped."""
    if _rule_target(rule) != "ACCEPT":
        return False
    if _rule_is_local_only(rule):
        return False
    if "--ctstate" in rule or "-m conntrack" in rule:
        return False
    if _rule_scoped_to_bench(rule):
        return False
    return True


def _rule_is_bench_scoped_accept(rule):
    """ACCEPT to a private/bench destination only - allowed but worth reporting."""
    return (_rule_target(rule) == "ACCEPT"
            and not _rule_is_local_only(rule)
            and "--ctstate" not in rule and "-m conntrack" not in rule
            and _rule_scoped_to_bench(rule))


def parse_iptables_s(output):
    """Parse ``iptables -S OUTPUT`` into (policy, rules)."""
    policy = None
    rules = []
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("-P OUTPUT"):
            parts = line.split()
            if len(parts) >= 3:
                policy = parts[2].upper()
        elif line.startswith("-A OUTPUT"):
            rules.append(line)
    return policy, rules


def evaluate_family(policy, rules):
    """Return a containment verdict for one address family."""
    default_drop = policy in ("DROP", "REJECT") or any(
        _rule_is_catch_all_drop(r) for r in rules)
    open_paths = [r for r in rules if _rule_opens_path(r)]

    # Ports covered by explicit DROP/REJECT rules.
    covered = set()
    for rule in rules:
        if _rule_target(rule) not in ("DROP", "REJECT"):
            continue
        proto_name = _rule_proto(rule)
        ports = _rule_ports(rule)
        if not ports:
            continue
        for (proto, port) in REQUIRED_PORTS:
            if port not in ports:
                continue
            if proto_name is None or proto_name == PROTO_NAMES[proto] or proto_name == "all":
                covered.add((proto, port))

    missing = [p for p in REQUIRED_PORTS if p not in covered]
    if default_drop and not open_paths:
        level = "full"
        covered_ports = ["all (default DROP)"]
    else:
        level = "partial" if (not open_paths and not missing) else "none"
        covered_ports = sorted(f"{PROTO_NAMES[p]}/{port}" for (p, port) in covered)

    bench_scoped = [r for r in rules if _rule_is_bench_scoped_accept(r)]

    return {
        "level": level,
        "policy": policy,
        "default_drop": default_drop,
        "open_accept_rules": open_paths,
        "bench_scoped_accept_rules": bench_scoped,
        "covered_ports": covered_ports,
        "missing_ports": ([] if level == "full"
                          else sorted(f"{PROTO_NAMES[p]}/{port}" for (p, port) in missing)),
        "rules": rules,
    }


def _query_iptables(binary):
    """Run '<binary> -S OUTPUT'. Returns (stdout, error_string)."""
    cmd = _sudo_prefix() + [binary, "-S", "OUTPUT"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return None, f"{binary} not found"
    except PermissionError:
        return None, f"cannot run {binary} (permission denied)"
    except subprocess.TimeoutExpired:
        return None, f"{binary} timed out"
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        return None, f"{binary} exit {proc.returncode}: {detail[-1] if detail else 'unknown error'}"
    return proc.stdout, None


def _ipv6_disabled():
    try:
        with open("/proc/sys/net/ipv6/conf/all/disable_ipv6", "r") as fh:
            return fh.read().strip() == "1"
    except OSError:
        return False


def check_containment():
    """Return a structured containment report covering IPv4 and IPv6."""
    report = {"ipv4": None, "ipv6": None, "errors": [], "level": "unknown"}

    if not is_linux():
        report["errors"].append("not Linux - containment cannot be verified")
        return report

    out4, err4 = _query_iptables("iptables")
    if out4 is None:
        report["errors"].append(err4)
        report["ipv4"] = {"level": "unknown", "error": err4}
    else:
        policy, rules = parse_iptables_s(out4)
        report["ipv4"] = evaluate_family(policy, rules)

    if _ipv6_disabled():
        report["ipv6"] = {"level": "full", "note": "IPv6 disabled on this host"}
    else:
        out6, err6 = _query_iptables("ip6tables")
        if out6 is None:
            report["errors"].append(err6)
            report["ipv6"] = {"level": "unknown", "error": err6}
        else:
            policy, rules = parse_iptables_s(out6)
            report["ipv6"] = evaluate_family(policy, rules)

    levels = [v.get("level") for v in (report["ipv4"], report["ipv6"]) if isinstance(v, dict)]
    order = {"unknown": 0, "none": 1, "partial": 2, "full": 3}
    report["level"] = min(levels, key=lambda lvl: order.get(lvl, 0)) if levels else "unknown"
    return report


def describe_containment(report):
    """Human-readable summary printed before execution."""
    lines = []
    for family in ("ipv4", "ipv6"):
        info = report.get(family)
        if not isinstance(info, dict):
            continue
        if info.get("level") == "unknown":
            lines.append(f"  {family}: UNKNOWN - {info.get('error', '')}")
            continue
        note = f" ({info['note']})" if info.get("note") else ""
        lines.append(
            f"  {family}: {info['level'].upper()} - policy={info.get('policy')} "
            f"covered={info.get('covered_ports')} missing={info.get('missing_ports')}{note}")
        for rule in info.get("open_accept_rules", []):
            lines.append(f"      open egress rule: {rule}")
        for rule in info.get("bench_scoped_accept_rules", []):
            lines.append(f"      bench-scoped ACCEPT (cannot leave the lab net): {rule}")
    lines.append(f"  overall: {report['level'].upper()}")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Leftover-process sweep
# -----------------------------------------------------------------------------
def _read_proc(pid, name):
    with open(f"/proc/{pid}/{name}", "rb") as fh:
        return fh.read()


def find_marked_pids(marker, sample_abspath):
    """PIDs that either carry this run's env marker or run the sample binary."""
    needle = marker.encode()
    sample = os.path.abspath(sample_abspath)
    own = {os.getpid(), os.getppid()}
    hits = []
    if not os.path.isdir("/proc"):
        return hits
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in own:
            continue
        matched = False
        try:
            environ = _read_proc(pid, "environ")
            matched = needle in environ
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
        if not matched:
            try:
                exe = os.readlink(f"/proc/{pid}/exe").replace(" (deleted)", "")
                matched = os.path.abspath(exe) == sample
            except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
                pass
        if matched:
            hits.append(pid)
    return hits


def sweep_leftovers(marker, sample_path, max_rounds=3):
    """Kill surviving processes carrying this run's marker. Returns (pids, note)."""
    if not is_linux() or not os.path.isdir("/proc"):
        return [], "leftover sweep skipped (no /proc on this platform)"
    killed = []
    for _ in range(max_rounds):
        hits = find_marked_pids(marker, sample_path)
        if not hits:
            break
        for pid in hits:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.append(pid)
            except ProcessLookupError:
                pass
            except PermissionError:
                return killed, (f"cannot kill pid {pid}: permission denied "
                                "(run the runner as the account that owns the sample)")
        time.sleep(0.2)
    return killed, ("killed surviving processes: " + ", ".join(map(str, killed))) if killed else ""


def _kill_tree(proc, grace=3.0):
    """SIGTERM then SIGKILL the sample's process group."""
    if proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, grace)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


# -----------------------------------------------------------------------------
# Privilege drop (Pi: operator owns GPIO, sample runs as `victim`)
# -----------------------------------------------------------------------------
def resolve_run_as(user):
    """Return a dict describing the target account, or raise ValueError."""
    if not is_linux():
        raise ValueError("--run-as requires a Linux host (no account database here)")
    try:
        import grp
        import pwd
    except ImportError:
        raise ValueError("--run-as is unsupported on this platform") from None
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        raise ValueError(f"user '{user}' does not exist on this host") from None

    groups = {entry.pw_gid}
    for group in grp.getgrall():
        if entry.pw_name in group.gr_mem:
            groups.add(group.gr_gid)

    return {
        "name": entry.pw_name,
        "uid": entry.pw_uid,
        "gid": entry.pw_gid,
        "groups": sorted(groups),
        "home": entry.pw_dir,
        "shell": entry.pw_shell,
    }


def check_sample_readable_by(sample_path, account):
    """Best-effort: can the target account stat and execute this file?"""
    try:
        mode = os.stat(sample_path).st_mode
    except OSError as exc:
        return False, str(exc)
    owner = os.stat(sample_path).st_uid
    group = os.stat(sample_path).st_gid

    if account["uid"] == 0:
        return True, ""
    if owner == account["uid"]:
        bits = (mode >> 6) & 0o7
    elif group in account["groups"]:
        bits = (mode >> 3) & 0o7
    else:
        bits = mode & 0o7
    if not bits & 0o4:
        return False, f"{account['name']} cannot read the sample (mode {oct(mode & 0o777)})"
    if not bits & 0o1:
        return False, f"{account['name']} cannot execute the sample (mode {oct(mode & 0o777)})"
    return True, ""


def build_preexec(account):
    """Return a callable that drops to `account` inside the child process."""
    def _drop():
        os.setgroups(account["groups"])
        os.setgid(account["gid"])
        os.setuid(account["uid"])
    return _drop


def child_environment(account):
    env = dict(os.environ)
    env["HOME"] = account["home"]
    env["USER"] = account["name"]
    env["LOGNAME"] = account["name"]
    env["SHELL"] = account["shell"] or "/bin/sh"
    return env


# -----------------------------------------------------------------------------
# One trace
# -----------------------------------------------------------------------------
def run_trace(index, sample_path, duration, trigger, marker, log_dir,
              run_as_account=None, cwd=None):
    """Execute the sample once for at most `duration` seconds. Never raises."""
    record = {
        "index": index,
        "start_utc": utc_now(),
        "pid": None,
        "exit_code": None,
        "killed": False,
        "wall_s": 0.0,
        "trigger_window_s": None,
        "leftovers_killed": [],
        "log_file": None,
        "run_as": run_as_account["name"] if run_as_account else None,
        "cwd": cwd,
        "notes": [],
    }

    env = child_environment(run_as_account) if run_as_account else dict(os.environ)
    env[RUN_ENV_MARKER] = marker
    log_path = os.path.join(log_dir, f"run_{index:03d}.log")
    record["log_file"] = log_path

    proc = None
    started = time.perf_counter()
    try:
        with open(log_path, "wb") as log_fh:
            proc = subprocess.Popen(
                [os.path.abspath(sample_path)],
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,   # own process group -> clean group kill
                env=env,
                cwd=cwd,
                close_fds=True,
                preexec_fn=build_preexec(run_as_account) if run_as_account else None,
            )
            record["pid"] = proc.pid
            try:
                proc.wait(timeout=duration)
            except subprocess.TimeoutExpired:
                record["killed"] = True
                _kill_tree(proc)
    except FileNotFoundError as exc:
        record["notes"].append(f"launch failed: {exc}")
    except PermissionError as exc:
        record["notes"].append(f"launch failed: {exc}")
    except OSError as exc:
        record["notes"].append(f"launch failed: {exc}")
    finally:
        record["wall_s"] = round(time.perf_counter() - started, 6)
        if proc is not None and proc.poll() is not None:
            record["exit_code"] = proc.returncode

    # Catch daemonized children that left the process group.
    killed, note = sweep_leftovers(marker, sample_path)
    record["leftovers_killed"] = killed
    if note:
        record["notes"].append(note)

    record["end_utc"] = utc_now()
    return record


def window_seconds(trigger):
    """Duration between the most recent on/off edge pair (None if unpaired)."""
    labels = [edge["label"] for edge in trigger.edges]
    if not labels or labels[-1] != "off" or "on" not in labels:
        return None
    on = next(e for e in reversed(trigger.edges) if e["label"] == "on")
    off = next(e for e in reversed(trigger.edges) if e["label"] == "off")
    return round(off["perf_counter"] - on["perf_counter"], 6)


# -----------------------------------------------------------------------------
# Runner loop
# -----------------------------------------------------------------------------
def write_manifest(path, manifest):
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def banner(args, trigger, sample_info, containment):
    print("\n=======================================================")
    print(" Bashlite runner v{} - {}".format(
        RUNNER_VERSION, "EXECUTE" if args.execute else "DRY RUN"))
    print(f" Sample        : {sample_info['path']}")
    if sample_info.get("sha256"):
        print(f" SHA-256       : {sample_info['sha256']}")
    elf = sample_info.get("elf", {})
    if elf.get("is_elf"):
        print(f" Binary        : {elf.get('class')} {elf.get('machine')}")
    print(f" Traces        : {args.count} x {args.duration:.2f}s "
          f"(cooldown {args.cooldown:.2f}s)")
    print(f" Trigger       : {trigger.describe()}")
    print(f" Manifest      : {args.manifest}")
    if args.run_as:
        print(f" Run as        : {args.run_as}")
    if containment is not None:
        print(" Containment   :")
        print(describe_containment(containment))
    print("=======================================================\n")


def run(args):
    """Run the benchmark. Returns (exit_code, manifest)."""
    trigger = make_trigger(args)
    run_stamp = stamp()
    marker = f"{run_stamp}-{uuid.uuid4().hex[:8]}"
    log_dir = os.path.join(os.path.dirname(os.path.abspath(args.manifest)) or ".",
                           f"bashlite_logs_{run_stamp}")
    errors = []
    warnings = []

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "runner_version": RUNNER_VERSION,
        "started_utc": utc_now(),
        "finished_utc": None,
        "run_id": marker,
        "mode": "execute" if args.execute else "dry-run",
        "invocation": sys.argv,
        "host": {
            "node": socket.gethostname(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "euid": effective_uid(),
        },
        "params": {
            "count": args.count,
            "duration_s": args.duration,
            "cooldown_s": args.cooldown,
            "gpio_pin": None if args.software_trigger else args.gpio_pin,
            "use_act_led": bool(args.use_act_led),
            "software_trigger": bool(args.software_trigger),
            "cwd": os.path.abspath(args.cwd or os.getcwd()),
            "run_as": args.run_as,
        },
        "trigger": {"mode": trigger.mode, "available": trigger.available,
                    "description": trigger.describe()},
        "sample": None,
        "containment": None,
        "run_as": None,
        "runs": [],
        "warnings": warnings,
        "errors": errors,
        "interrupted": False,
    }

    # ---- sample verification (dry run tolerates a missing sample) ----
    sample_info, sample_errors, sample_warnings = verify_sample(
        args.sample, args.expected_hash)
    manifest["sample"] = sample_info
    warnings.extend(sample_warnings)

    if sample_errors:
        if args.execute:
            for msg in sample_errors:
                print(f"[FATAL] {msg}")
            errors.extend(sample_errors)
            manifest["finished_utc"] = utc_now()
            write_manifest(args.manifest, manifest)
            trigger.cleanup()
            return 3, manifest
        for msg in sample_errors:
            print(f"[WARN] {msg} (ignored in dry run)")

    # ---- privilege drop target ----
    run_as_account = None
    if args.run_as:
        try:
            run_as_account = resolve_run_as(args.run_as)
        except ValueError as exc:
            print(f"[FATAL] --run-as: {exc}")
            errors.append(str(exc))
            manifest["finished_utc"] = utc_now()
            write_manifest(args.manifest, manifest)
            trigger.cleanup()
            return 5, manifest
        manifest["run_as"] = run_as_account
        if not args.execute:
            print(f"[Run-as] Dry run: would drop to '{run_as_account['name']}' "
                  f"(uid {run_as_account['uid']}, home {run_as_account['home']}).")
        else:
            if effective_uid() != 0:
                print(f"[FATAL] --run-as '{run_as_account['name']}' requires running the "
                      "runner as root (needed to setuid down).")
                errors.append("--run-as requires root")
                manifest["finished_utc"] = utc_now()
                write_manifest(args.manifest, manifest)
                trigger.cleanup()
                return 5, manifest
            readable, why = check_sample_readable_by(sample_info.get("path", args.sample),
                                                     run_as_account)
            if not readable:
                print(f"[FATAL] --run-as: {why}")
                errors.append(why)
                manifest["finished_utc"] = utc_now()
                write_manifest(args.manifest, manifest)
                trigger.cleanup()
                return 5, manifest
            print(f"[Run-as] Sample will run as '{run_as_account['name']}' "
                  f"(uid {run_as_account['uid']}), cwd={args.cwd or run_as_account['home']}.")

    # ---- containment gate ----
    containment = None
    if args.execute:
        print("[Containment] Querying iptables / ip6tables ...")
        containment = check_containment()
        manifest["containment"] = containment
        level = containment["level"]
        if level == "full":
            print("[Containment] OK: outbound traffic is default-dropped.")
        elif level == "partial" and args.allow_partial_containment:
            print("[Containment] WARNING: only specific ports are dropped. Bashlite "
                  "can still flood arbitrary ports. Proceeding because "
                  "--allow-partial-containment was given.")
            warnings.append("partial containment accepted via --allow-partial-containment")
        elif args.skip_containment_check:
            print("[Containment] WARNING: verification skipped by --skip-containment-check. "
                  "You are asserting containment is active.")
            warnings.append("containment check skipped by operator")
        else:
            print("[Containment] FATAL: containment is not verifiably active "
                  f"(level={level}). Refusing to execute live malware.")
            print(describe_containment(containment))
            print("  Fix the guest/host firewall (see Bashlite/docs/BASHLITE_VM_TEST.md Phase B), "
                  "or pass --skip-containment-check only if you verified it yourself.")
            errors.append(f"containment level {level}")
            manifest["finished_utc"] = utc_now()
            write_manifest(args.manifest, manifest)
            trigger.cleanup()
            return 2, manifest
    else:
        containment = check_containment()
        manifest["containment"] = containment
        print("[Containment] Dry run: report only, not enforced.")

    banner(args, trigger, sample_info, containment if containment else None)
    os.makedirs(log_dir, exist_ok=True)
    manifest["log_dir"] = os.path.abspath(log_dir)

    if args.cwd:
        os.makedirs(args.cwd, exist_ok=True)
        os.chdir(args.cwd)

    # The working directory for the sample (HOME of the run-as account on the Pi)
    # must exist and be usable before any trace starts.
    sample_cwd = args.cwd or (run_as_account["home"] if run_as_account else None)
    if args.execute and sample_cwd:
        if not os.path.isdir(sample_cwd):
            print(f"[FATAL] sample working directory does not exist: {sample_cwd}")
            errors.append(f"cwd missing: {sample_cwd}")
            manifest["finished_utc"] = utc_now()
            write_manifest(args.manifest, manifest)
            trigger.cleanup()
            return 5, manifest

    # Settle before the first trace, matching goodware_runner.
    time.sleep(1.0)

    abort_reason = None
    exit_code = 0
    try:
        for index in range(1, args.count + 1):
            print(f"[{index:04d}/{args.count:04d}] Arming trigger -> "
                  f"{'executing sample' if args.execute else 'simulating'} ...",
                  end="", flush=True)

            if args.execute:
                trigger.on()
                record = run_trace(index, sample_info["path"], args.duration,
                                   trigger, marker, log_dir,
                                   run_as_account=run_as_account,
                                   cwd=sample_cwd)
                trigger.off()
                record["trigger_window_s"] = window_seconds(trigger)
            else:
                trigger.on()
                time.sleep(args.duration)
                trigger.off()
                record = {
                    "index": index,
                    "start_utc": utc_now(),
                    "end_utc": utc_now(),
                    "pid": None,
                    "exit_code": None,
                    "killed": False,
                    "wall_s": args.duration,
                    "trigger_window_s": window_seconds(trigger),
                    "leftovers_killed": [],
                    "log_file": None,
                    "notes": ["dry run: sample not executed"],
                }

            manifest["runs"].append(record)
            killed_tag = " [killed:timeout]" if record["killed"] else ""
            leftover_tag = (f" [leftovers:{len(record['leftovers_killed'])}]"
                            if record["leftovers_killed"] else "")
            print(f" done in {record['wall_s']:.3f}s "
                  f"(exit={record['exit_code']}{killed_tag}{leftover_tag})")

            # A 32-bit ARM sample on an aarch64 guest without CONFIG_COMPAT
            # fails immediately with ENOEXEC (126) - stop instead of spamming.
            if (args.execute and record["exit_code"] in (126, 127)
                    and not record["killed"] and record["wall_s"] < 0.5):
                abort_reason = (
                    f"sample could not be executed (exit {record['exit_code']}). "
                    "126 = Exec format error: the guest cannot run this binary "
                    "(check 32-bit ARM CONFIG_COMPAT, or use the aarch64 mimic). "
                    "127 = command not found / missing interpreter.")
                break

            time.sleep(args.cooldown)
    except KeyboardInterrupt:
        print("\n[Interrupted] Stopping; killing any surviving sample processes.")
        manifest["interrupted"] = True
        exit_code = 130
        killed, note = sweep_leftovers(marker, sample_info["path"])
        if killed:
            manifest["final_leftovers_killed"] = killed
            print(f"[Interrupted] {note}")

    finally:
        trigger.off()
        trigger.cleanup()

    if abort_reason:
        print(f"\n[ABORT] {abort_reason}")
        errors.append(abort_reason)
        exit_code = 4

    print(f"\n[Completed] {len(manifest['runs'])} trace(s). Manifest: {args.manifest}\n")
    manifest["finished_utc"] = utc_now()
    manifest["trigger"]["edges"] = trigger.edges
    write_manifest(args.manifest, manifest)
    return exit_code, manifest


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        description="Bashlite EM measurement runner (time-bounded, trigger-synchronized).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--sample", "-s", required=True,
                        help="path to the Bashlite sample (or the aarch64 mimic)")
    parser.add_argument("--expected-hash",
                        help="expected SHA-256; REQUIRED with --execute")
    parser.add_argument("--count", "-c", type=int, default=10,
                        help="number of traces")
    parser.add_argument("--duration", "-d", type=float, default=2.5,
                        help="capture window per trace, seconds (paper: 2.5)")
    parser.add_argument("--cooldown", type=float, default=0.5,
                        help="pause between traces, seconds")
    parser.add_argument("--execute", action="store_true",
                        help="actually run the sample (default: dry run)")
    parser.add_argument("--software-trigger", action="store_true",
                        help="no GPIO; record edge timestamps only (VM rehearsal)")
    parser.add_argument("--gpio-pin", "-p", type=int, default=17,
                        help="BCM pin for the oscilloscope trigger")
    parser.add_argument("--use-act-led", action="store_true",
                        help="use the on-board ACT LED as trigger (active-low)")
    parser.add_argument("--cwd", help="working directory for the sample (default: run-as HOME, else current)")
    parser.add_argument("--run-as", metavar="USER",
                        help="drop the sample to this unprivileged account (Pi: victim); "
                             "requires the runner itself to run as root")
    parser.add_argument("--manifest", default=f"bashlite_manifest_{stamp()}.json",
                        help="manifest output path")
    parser.add_argument("--skip-containment-check", action="store_true",
                        help="skip iptables verification (asserts containment yourself)")
    parser.add_argument("--allow-partial-containment", action="store_true",
                        help="accept per-port DROP rules without a default DROP policy")
    parser.add_argument("--allow-root", action="store_true",
                        help="permit --execute with euid 0 (strongly discouraged)")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.count < 1:
        parser.error("--count must be >= 1")
    if args.duration <= 0:
        parser.error("--duration must be > 0")
    if args.cooldown < 0:
        parser.error("--cooldown must be >= 0")
    if args.software_trigger and args.use_act_led:
        parser.error("--software-trigger and --use-act-led are mutually exclusive")

    if args.execute:
        if not args.expected_hash:
            parser.error("--execute requires --expected-hash (record it in the manifest)")
        if not is_linux():
            parser.error("--execute is Linux-only; use a dry run on this host")
        if effective_uid() == 0 and not args.allow_root and not args.run_as:
            parser.error("refusing to run malware as root; use --run-as <user> (Pi: victim), "
                         "or run the runner as an unprivileged account, or pass --allow-root")

    code, _manifest = run(args)
    return code


if __name__ == "__main__":
    sys.exit(main())
