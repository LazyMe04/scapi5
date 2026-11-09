#!/usr/bin/env python3
"""
Lab C2 server for Bashlite behavioural rehearsal.

What this is
------------
A *spoofed* command-and-control endpoint that lives on the bench link (laptop
192.168.7.1) and makes a Bashlite sample behave like a live bot instead of a
process that retries a dead address and sleeps. The paper does the same thing
(ACSAC '21 section 6.1.2): a synthetic C&C that hands the bot commands so that
every run exercises a comparable workload.

What this is NOT
----------------
* It never forwards, proxies, or resolves anything. There is no path from here
  to the internet.
* It never accepts connections from outside the bench subnet.
* It does not implement any real botnet protocol feature beyond command delivery
  to drive the sample.

Why this matters for the EM dataset
-----------------------------------
A bot that cannot reach a C2 produces a retry loop that is indistinguishable
from an idle process. An idle trace is useless: it teaches a classifier the
shape of "nothing happening". Fixed-offset command delivery gives every trace
the same sequence of work, which is what makes traces comparable across runs.

Modes
-----
observe   listen, log every byte the bot sends, reply with nothing. Use this
          first: it tells you what the specific sample expects before you invent
          answers.

serve     listen and follow a command script whose offsets are measured from
          accept().

Both modes start the UDP/TCP sinks if their ports are free, so a flood can be
measured in observe mode too. If a unicast peer other than the bench host shows
up, the flood is not going where the script says — that is the case the sink
exists to expose.

Wire format note for the bundled sample
---------------------------------------
The default script speaks the protocol of Gafgyt 349d2476, recovered by
emulating that sample's own parser (Bashlite/analysis/simparse.py). It is `!` + exactly
one space + COMMAND + space-separated arguments. The classic `.tcp` / `.udp`
vocabulary and the IRC-style NICK/PING handshake of other Bashlite builds are
not used here. If you swap in a different sample, re-run observe first and
rewrite c2_script.json — a mismatched script is silently ignored by the bot.

Typical session
---------------
    # 1. discovery - find out what this sample says on connect
    python3 c2_server.py --mode observe --bind 192.168.7.1 --port 999 \
        --log runs/discover.log

    # 2. rehearsal - deterministic command timeline
    python3 c2_server.py --mode serve --bind 192.168.7.1 --port 999 \
        --script c2_script.json --sink-port 9999 --log runs/run01.log

    # 3. evidence - the JSONL log plus the sink counters are the proof that the
    #    sample was driven, and they belong next to the manifest.

Safety defaults
---------------
* Binds only to the address you pass. There is no 0.0.0.0 fallback.
* Refuses peers outside --allow-cidr (default 192.168.7.0/24, plus loopback so
  --self-test works on one machine).
* No DNS, no outbound sockets, no subprocesses.
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone

SERVER_VERSION = "1.0.0"

DEFAULT_ALLOW_CIDR = "192.168.7.0/24"

# Wire format of this specific sample, recovered by emulating its own parser
# (Bashlite/analysis/simparse.py) rather than by reading disassembly:
#
#   ! CMD arg arg arg          -> argv[0] = "CMD", dispatches
#   !CMD arg arg arg          -> the first token is eaten, argc too small, ignored
#   ! CMD a,b,c               -> one token, argc too small, ignored
#
# So the bang must be followed by exactly one space, and the arguments must be
# separated by spaces. Commands are case-insensitive: the bot uppercases argv[0]
# itself. STDHEX is the plainest primitive (SendSTDHEX: 1460-byte TCP sends
# until the duration expires, called four times in a row).
DEFAULT_SCRIPT = {
    "name": "bashlite-bench-default",
    "version": 2,
    "description": (
        "Timeline for Gafgyt 349d2476: greet, hand over one STDHEX flood early "
        "so the trace has real work, then a second command later so activity "
        "covers most of the 2.5 s capture window."
    ),
    # The bot speaks first and then blocks; the C2 has nothing to say on accept.
    "handshake_at_ms": 0,
    "commands": [
        {"at_ms": 60, "send": "{flood_stdhex}\n", "label": "flood-stdhex"},
        {"at_ms": 1200, "send": "{flood_cnc}\n", "label": "flood-cnc"},
        {"at_ms": 2200, "send": "{stop}\n", "label": "stop"}
    ],
    "close_at_ms": 2450,
    "auto_replies": []
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ms_since(start):
    return round((time.monotonic() - start) * 1000.0, 3)


# -----------------------------------------------------------------------------
# Peer filtering
# -----------------------------------------------------------------------------
class PeerPolicy:
    def __init__(self, allowed_cidrs, allow_loopback=True):
        import ipaddress
        self.networks = []
        for cidr in allowed_cidrs:
            try:
                self.networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                raise SystemExit(f"invalid --allow-cidr: {cidr}")
        if allow_loopback:
            self.networks += [ipaddress.ip_network("127.0.0.0/8"),
                              ipaddress.ip_network("::1/128")]

    def allows(self, ip):
        import ipaddress
        try:
            addr = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            return False
        return any(addr.version == net.version and addr in net
                   for net in self.networks)


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
class RunLog:
    """JSONL event log. One file per server run, append-only, flushed per event."""

    def __init__(self, path, echo=True):
        self.path = path
        self.echo = echo
        self.lock = threading.Lock()
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8")

    def event(self, **fields):
        fields.setdefault("utc", utc_now())
        line = json.dumps(fields, ensure_ascii=False, sort_keys=True)
        with self.lock:
            self.fh.write(line + "\n")
            self.fh.flush()
            if self.echo:
                print(line)

    def close(self):
        self.fh.close()


# -----------------------------------------------------------------------------
# Script rendering
# -----------------------------------------------------------------------------
class Script:
    def __init__(self, data):
        self.name = data.get("name", "unnamed")
        self.version = data.get("version", 1)
        self.handshake_at_ms = data.get("handshake_at_ms", 0)
        self.commands = sorted(data.get("commands", []), key=lambda c: c["at_ms"])
        self.close_at_ms = data.get("close_at_ms")
        self.auto_replies = data.get("auto_replies", [])

    @classmethod
    def load(cls, path):
        if not path:
            return cls(dict(DEFAULT_SCRIPT))
        with open(path, "r", encoding="utf-8") as fh:
            return cls(json.load(fh))

    def render(self, template, ctx):
        return template.format(**ctx)

    def validate(self, ctx_keys):
        """Fail at startup, not mid-run, if a template references an unknown key.

        A worker thread that dies while rendering would leave the bot with an
        empty connection and produce a trace that looks like an idle process -
        the one outcome the EM dataset cannot use. Catch it here instead.
        """
        ctx = {k: "x" for k in ctx_keys}
        for cmd in self.commands:
            template = cmd.get("send", "")
            try:
                template.format(**ctx)
            except KeyError as exc:
                raise SystemExit(
                    f"script '{self.name}': command {cmd.get('label', '?')!r} "
                    f"uses {{{exc.args[0]}}}, which the server does not provide. "
                    f"Available: {', '.join(sorted(ctx_keys))}")
            except (IndexError, ValueError) as exc:
                raise SystemExit(
                    f"script '{self.name}': command {cmd.get('label', '?')!r} "
                    f"has a malformed template: {exc}")

    def fingerprint(self):
        """Stable description recorded in the manifest so a run can be reproduced."""
        return {
            "name": self.name,
            "version": self.version,
            "handshake_at_ms": self.handshake_at_ms,
            "close_at_ms": self.close_at_ms,
            "commands": [{"at_ms": c["at_ms"], "label": c.get("label", "")}
                         for c in self.commands],
        }


# -----------------------------------------------------------------------------
# Sinks: where flood commands actually point
# -----------------------------------------------------------------------------
class UdpSink:
    """Counts UDP datagrams so flood activity is measurable, not assumed."""

    def __init__(self, bind_addr, port, log):
        self.log = log
        self.port = port
        self.packets = 0
        self.bytes = 0
        self.first_utc = None
        self.last_utc = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((bind_addr, port))
        self.sock.settimeout(0.5)
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="udp-sink", daemon=True)

    def start(self):
        self.thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                data, peer = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            self.packets += 1
            self.bytes += len(data)
            now = utc_now()
            self.first_utc = self.first_utc or now
            self.last_utc = now
            if self.packets in (1, 10, 100, 1000) or self.packets % 5000 == 0:
                self.log.event(event="udp_sink", packets=self.packets,
                               bytes=self.bytes, peer=f"{peer[0]}:{peer[1]}")

    def stats(self):
        return {"port": self.port, "packets": self.packets, "bytes": self.bytes,
                "first_utc": self.first_utc, "last_utc": self.last_utc}

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


class TcpSink:
    """Accepts and immediately drains TCP connections (flood / scan targets)."""

    def __init__(self, bind_addr, port, log):
        self.log = log
        self.port = port
        self.connections = 0
        self.bytes = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((bind_addr, port))
        self.sock.listen(64)
        self.sock.settimeout(0.5)
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="tcp-sink", daemon=True)

    def start(self):
        self.thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                conn, peer = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.connections += 1
            try:
                conn.settimeout(0.2)
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    self.bytes += len(chunk)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
            if self.connections in (1, 10, 100) or self.connections % 500 == 0:
                self.log.event(event="tcp_sink", connections=self.connections,
                               bytes=self.bytes, peer=f"{peer[0]}:{peer[1]}")

    def stats(self):
        return {"port": self.port, "connections": self.connections, "bytes": self.bytes}

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


# -----------------------------------------------------------------------------
# Connection handling
# -----------------------------------------------------------------------------
def _peer_name(peer):
    return f"{peer[0]}:{peer[1]}"


def build_context(args, peer):
    """Template values available to a command script.

    Kept as one function so validate() and handle_connection() can never drift:
    a key added here is visible to the startup check automatically.
    """
    return {
        "peer_ip": peer[0],
        "peer_port": peer[1],
        "c2_ip": args.bind,
        "c2_port": args.port,
        "sink_ip": args.bind,
        "sink_port": args.sink_port,
        "flood_seconds": args.flood_seconds,
        # Exactly one space after "!". See the DEFAULT_SCRIPT comment: the bot's
        # parser consumes the character after the bang, so "!CMD" loses the
        # command name and "! CMD a,b" yields a single over-long token.
        "flood_stdhex": f"! STDHEX {args.bind} {args.sink_port} {args.flood_seconds}",
        "flood_cnc": f"! CNC {args.bind} {args.sink_port} {args.flood_seconds}",
        "stop": "! STOP",
        "rest": "",
    }


def handle_connection(conn, peer, args, script, log, policy):
    """One bot connection. Everything is timed from accept()."""
    conn_id = f"{peer[0]}:{peer[1]}-{int(time.time() * 1000) % 100000}"
    start = time.monotonic()

    if not policy.allows(peer[0]):
        log.event(event="rejected", conn=conn_id, reason="peer outside bench subnet")
        try:
            conn.close()
        except OSError:
            pass
        return

    log.event(event="accept", conn=conn_id, peer=_peer_name(peer),
              handshake_at_ms=script.handshake_at_ms,
              command_count=len(script.commands))

    ctx = build_context(args, peer)

    conn.settimeout(0.05)
    pending = list(script.commands)
    closed = False

    try:
        while True:
            elapsed = ms_since(start)

            if script.close_at_ms is not None and elapsed >= script.close_at_ms:
                log.event(event="close_by_script", conn=conn_id, at_ms=elapsed)
                closed = True
                break

            # Send everything that is due.
            while pending and elapsed >= pending[0]["at_ms"]:
                cmd = pending.pop(0)
                payload = script.render(cmd.get("send", ""), ctx).encode()
                try:
                    conn.sendall(payload)
                except OSError as exc:
                    log.event(event="send_failed", conn=conn_id, error=str(exc))
                    return
                log.event(event="send", conn=conn_id, at_ms=elapsed,
                          label=cmd.get("label", ""),
                          bytes=len(payload),
                          preview=payload[:120].decode("latin-1"))

            # Sleep only until the next scheduled event, so offsets stay tight
            # (a fixed 50 ms poll would add up to 50 ms of jitter per command).
            deadlines = [c["at_ms"] for c in pending]
            if script.close_at_ms is not None:
                deadlines.append(script.close_at_ms)
            if deadlines:
                remaining = max(0.001, (min(deadlines) - ms_since(start)) / 1000.0)
                poll = min(0.05, remaining)
            else:
                poll = 0.05
            conn.settimeout(poll)

            # Read whatever the bot sent; never block the schedule.
            try:
                data = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                log.event(event="recv_failed", conn=conn_id,
                          at_ms=ms_since(start), error=f"{type(exc).__name__}: {exc}")
                break

            if not data:
                log.event(event="bot_closed", conn=conn_id, at_ms=elapsed)
                closed = True
                break

            text = data.decode("latin-1")
            log.event(event="recv", conn=conn_id, at_ms=ms_since(start),
                      bytes=len(data), preview=text[:160])

            if args.mode == "observe":
                continue

            for rule in script.auto_replies:
                haystack = text.upper()
                if rule["match"].upper() in haystack:
                    reply = rule.get("send", "")
                    if not reply:
                        continue
                    reply = reply.replace("{rest}", text.strip())
                    try:
                        conn.sendall(reply.encode())
                        log.event(event="auto_reply", conn=conn_id,
                                  at_ms=ms_since(start), rule=rule["match"])
                    except OSError:
                        pass
                    break
    finally:
        try:
            conn.close()
        except OSError:
            pass
        if not closed:
            log.event(event="end", conn=conn_id, at_ms=ms_since(start))
        else:
            log.event(event="end", conn=conn_id, at_ms=ms_since(start))


# -----------------------------------------------------------------------------
# Self test - proves the server works without a malware sample
# -----------------------------------------------------------------------------
def self_test(args):
    """Connect to the running server and act like a dumb bot.

    The real sample sends a banner and then blocks. This sends the banner, then
    only reads, so it exercises the same path the sample does.
    """
    print(f"[self-test] connecting to {args.bind}:{args.port}")
    sock = socket.create_connection((args.bind, args.port), timeout=3)
    sock.settimeout(0.2)
    start = time.monotonic()
    sent_banner = False
    received = []
    try:
        while time.monotonic() - start < 3.0:
            if not sent_banner:
                banner = b"[self-test] Arm4:127.0.0.1 > [x]\n"
                sock.sendall(banner)
                print(f"[self-test] sent banner ({len(banner)} B)")
                sent_banner = True
            try:
                data = sock.recv(4096)
            except socket.timeout:
                time.sleep(0.05)
                continue
            except OSError as exc:
                print(f"[self-test] recv ended: {type(exc).__name__}: {exc}")
                break
            if not data:
                print("[self-test] server closed the connection")
                break
            received.append(data)
            print(f"[self-test] recv {len(data)}B: {data[:100]!r}")
    finally:
        sock.close()
    print(f"[self-test] done, {len(received)} message(s) received")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        description="Lab spoofed C2 for Bashlite rehearsal (bench link only).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--bind", default="192.168.7.1",
                   help="address to listen on (no 0.0.0.0 fallback)")
    p.add_argument("--port", type=int, default=999,
                   help="C2 TCP port (this sample hardcodes 999)")
    p.add_argument("--mode", choices=["serve", "observe"], default="serve",
                   help="serve = follow the script; observe = log only")
    p.add_argument("--script", help="JSON command script (default: built-in timeline)")
    p.add_argument("--allow-cidr", action="append", default=None,
                   help=f"permitted peer subnet (repeatable; default {DEFAULT_ALLOW_CIDR})")
    p.add_argument("--deny-loopback", action="store_true",
                   help="do not implicitly allow 127.0.0.0/8 (self-test needs it)")
    p.add_argument("--sink-port", type=int, default=9999,
                   help="UDP/TCP sink port advertised in flood commands")
    p.add_argument("--flood-seconds", type=int, default=3,
                   help="duration argument handed to the bot in flood commands; "
                        "keep it just above the capture window so the forked flood "
                        "child stops soon after the trace ends")
    p.add_argument("--no-sink", action="store_true", help="do not start the sinks")
    p.add_argument("--log", default=None, help="JSONL event log path")
    p.add_argument("--max-connections", type=int, default=0,
                   help="stop after N connections (0 = unlimited)")
    p.add_argument("--duration", type=float, default=0,
                   help="stop after N seconds (0 = until Ctrl-C)")
    p.add_argument("--self-test", action="store_true",
                   help="act as a client against an already-running instance")
    p.add_argument("--print-script", action="store_true",
                   help="print the effective script and exit")
    p.add_argument("--summary", help="write a JSON summary here on exit")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    script = Script.load(args.script)
    script.validate(build_context(args, ("0.0.0.0", 0)).keys())

    if args.print_script:
        print(json.dumps({
            "fingerprint": script.fingerprint(),
            "commands": script.commands,
            "auto_replies": script.auto_replies,
        }, indent=2))
        return 0

    if args.self_test:
        self_test(args)
        return 0

    log_path = args.log or f"c2_{datetime.now().strftime('%Y%m%dT%H%M%S')}.jsonl"
    log = RunLog(log_path)
    policy = PeerPolicy(args.allow_cidr or [DEFAULT_ALLOW_CIDR],
                        allow_loopback=not args.deny_loopback)

    sinks = []
    if not args.no_sink:
        udp = UdpSink(args.bind, args.sink_port, log)
        udp.start()
        sinks.append(udp)
        tcp = TcpSink(args.bind, args.sink_port, log)
        tcp.start()
        sinks.append(tcp)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.bind, args.port))
    server.listen(16)
    server.settimeout(0.5)

    log.event(event="start", version=SERVER_VERSION, bind=args.bind, port=args.port,
              mode=args.mode, log=os.path.abspath(log_path),
              script=script.fingerprint(),
              allow=[str(n) for n in policy.networks],
              sinks=[s.stats() for s in sinks])

    print(f"[c2] listening on {args.bind}:{args.port} mode={args.mode}")
    print(f"[c2] script: {script.name} v{script.version} "
          f"({len(script.commands)} commands)")
    print(f"[c2] log: {os.path.abspath(log_path)}")
    print("[c2] Ctrl-C to stop")

    started = time.monotonic()
    accepted = 0
    stop = False
    workers = []

    try:
        while not stop:
            if args.duration and time.monotonic() - started >= args.duration:
                log.event(event="stop", reason="duration")
                break
            try:
                conn, peer = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            accepted += 1
            log.event(event="connection", index=accepted, peer=_peer_name(peer))
            worker = threading.Thread(target=handle_connection,
                                      args=(conn, peer, args, script, log, policy),
                                      name=f"conn-{accepted}", daemon=True)
            worker.start()
            workers.append(worker)
            if args.max_connections and accepted >= args.max_connections:
                log.event(event="stop", reason="max-connections")
                break
    except KeyboardInterrupt:
        print("\n[c2] interrupted")
        log.event(event="stop", reason="interrupt")
    finally:
        try:
            server.close()
        except OSError:
            pass
        # Let in-flight connections finish their script (the close_at_ms timeline
        # is what makes the trace deterministic), then record the summary.
        for worker in workers:
            worker.join(timeout=(script.close_at_ms or 3000) / 1000.0 + 5.0)
        for sink in sinks:
            sink.stop()
        summary = {
            "version": SERVER_VERSION,
            "bind": args.bind,
            "port": args.port,
            "mode": args.mode,
            "script": script.fingerprint(),
            "connections": accepted,
            "sinks": [s.stats() for s in sinks],
            "log": os.path.abspath(log_path),
            "stopped_utc": utc_now(),
        }
        log.event(event="summary", **summary)
        if args.summary:
            with open(args.summary, "w", encoding="utf-8") as fh:
                json.dump(summary, fh, indent=2)
                fh.write("\n")
            print(f"[c2] summary -> {args.summary}")
        log.close()
        print(json.dumps(summary["sinks"], indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
