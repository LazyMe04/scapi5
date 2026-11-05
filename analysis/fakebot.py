"""Loopback bot stand-in for testing c2_server.py without running the sample.

Mimics the observed behaviour of Gafgyt 349d2476: connect, send one banner
line immediately, then block reading. Prints every line the C2 sends back.

Usage: python -I fakebot.py <host> <port> [seconds]
"""
import socket
import sys
import time


def main():
    host = sys.argv[1]
    port = int(sys.argv[2])
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0

    sock = socket.create_connection((host, port), timeout=5)
    sock.settimeout(0.1)
    started = time.monotonic()

    banner = b"\x1b[0m[\x1b[1;31mSnoopy.\x1b[0m][\x1b[1;31mArm4\x1b[0m]" \
             b"\x1b[1;31m:\x1b[0m[\x1b[1;31m127.0.0.1\x1b[0m] > [x]\n"
    sock.sendall(banner)
    print(f"[fakebot] connected, sent banner ({len(banner)} B)", flush=True)

    buf = b""
    deadline = started + seconds
    try:
        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                print(f"[fakebot] socket error: {exc}", flush=True)
                break
            if not chunk:
                print("[fakebot] closed by peer", flush=True)
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                print(f"[fakebot] {time.monotonic()-started:7.3f}s CMD {line.decode('latin1')!r}",
                      flush=True)
    finally:
        sock.close()

    print(f"[fakebot] done, {time.monotonic()-started:.3f}s", flush=True)


if __name__ == "__main__":
    main()
