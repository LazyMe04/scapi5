"""Emulate main()'s C2 line parser to settle the exact wire format.

Why this exists
---------------
Disassembler text for the parser disagreed with the raw instruction words on one
stack slot, and the wire format (`!CMD a b c` vs `! CMD a b c`) decides whether
the sample acts on a command at all. Instead of reading the disassembly, this
runs the sample's own ARM instructions (0x1299c..0x12cb4) on a synthetic stack,
with the handful of libc helpers reimplemented, and reports the `argc`/`argv`
that processCmd() would receive.

Read-only: the zip is decrypted in memory; no ELF is written to disk.
Usage: python -I simparse.py <zip> <password> ["!STDHEX ..."]
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = _HERE
while not os.path.isdir(os.path.join(_LIB, '.pylib')):
    _parent = os.path.dirname(_LIB)
    if _parent == _LIB:
        break
    _LIB = _parent
sys.path.insert(0, os.path.join(_LIB, '.pylib'))
sys.path.insert(0, _HERE)

import elfdump

MASK = 0xFFFFFFFF
TEXT = 0x0080D0
RODATA = 0x01E310


def ror(v, n):
    n &= 31
    return v if not n else ((v >> n) | (v << (32 - n))) & MASK


def arm_imm(w):
    return ror(w & 0xFF, ((w >> 8) & 0xF) * 2)


class Machine:
    def __init__(self, text_bytes, rodata_bytes):
        self.mem = bytearray(0x80000)
        self.mem[TEXT:TEXT + len(text_bytes)] = text_bytes
        self.mem[RODATA:RODATA + len(rodata_bytes)] = rodata_bytes
        self.r = [0] * 16
        self.n = self.z = self.c = self.v = 0
        self.heap = 0x50000
        self.calls = []

    def rb(self, a):  return self.mem[a & 0x7FFFF]
    def wb(self, a, v): self.mem[a & 0x7FFFF] = v & 0xFF
    def rw(self, a):  return int.from_bytes(self.mem[a:a + 4], "little")
    def ww(self, a, v): self.mem[a:a + 4] = (v & MASK).to_bytes(4, "little")

    def cstr(self, a):
        out = bytearray()
        while self.rb(a):
            out.append(self.rb(a))
            a += 1
            if len(out) > 0x1800:
                break
        return bytes(out)

    def put_cstr(self, a, data):
        for i, b in enumerate(data):
            self.wb(a + i, b)
        self.wb(a + len(data), 0)

    def flags_nz(self, res):
        self.n = (res >> 31) & 1
        self.z = int(res == 0)

    def cond(self, c):
        return {
            0x0: self.z == 1, 0x1: self.z == 0,
            0x2: self.c == 1, 0x3: self.c == 0,
            0x4: self.n == 1, 0x5: self.n == 0,
            0x8: self.c == 1 and self.z == 0, 0x9: self.c == 0 or self.z == 1,
            0xA: self.n == self.v, 0xB: self.n != self.v,
            0xC: self.z == 0 and self.n == self.v, 0xD: self.z == 1 or self.n != self.v,
            0xE: True,
        }.get(c, False)

    def step(self):
        """Execute one instruction. Returns a callee address for BL, else None."""
        pc = self.r[15]
        w = self.rw(pc)
        self.r[15] = pc + 4
        cond = w >> 28
        if cond == 0xF:
            raise SystemExit(f"unsupported unconditional encoding at {pc:#x}")
        if not self.cond(cond):
            return None

        # ARM encoding class is bits 27:25. Using 27:26 here loses the I bit
        # and misroutes every immediate-offset load/store.
        cls = (w >> 25) & 0x7
        if cls == 0x5:                                 # B / BL
            imm = w & 0xFFFFFF
            if imm & 0x800000:
                imm -= 0x1000000
            target = (pc + 8 + imm * 4) & MASK
            if (w >> 24) & 1:                          # BL
                self.r[14] = pc + 4
                return target
            self.r[15] = target
            return None

        if cls in (0x2, 0x3):                          # LDR/STR immediate offset
            self._sdt(w, pc)
            return None
        if cls in (0x0, 0x1):                          # data processing
            self._dp(w)
            return None
        raise SystemExit(f"unsupported {w:#010x} at {pc:#x}")

    def _sdt(self, w, pc):
        U = (w >> 23) & 1
        B = (w >> 22) & 1
        L = (w >> 20) & 1
        rn = (w >> 16) & 0xF
        rd = (w >> 12) & 0xF
        off = w & 0xFFF
        base = (pc + 8) if rn == 15 else self.r[rn]
        addr = (base + off) if U else (base - off)
        if L:
            self.r[rd] = self.rb(addr) if B else self.rw(addr)
        else:
            self.wb(addr, self.r[rd]) if B else self.ww(addr, self.r[rd])

    def _dp(self, w):
        I = (w >> 25) & 1
        op = (w >> 21) & 0xF
        S = (w >> 20) & 1
        rn = (w >> 16) & 0xF
        rd = (w >> 12) & 0xF
        if I:
            b = arm_imm(w)
        else:
            b = self.r[w & 0xF]
            sh = (w >> 5) & 3
            amt = (w >> 7) & 0x1F
            if sh == 0:
                b = (b << amt) & MASK
            elif sh == 1:
                b = (b & MASK) >> amt
            elif sh == 2:
                b = ((b & MASK) >> amt) | ((b << (32 - amt)) & MASK) if amt else b
            else:
                b = ror(b & MASK, amt)
        a = self.r[rn]
        cin = self.c

        if op == 0x0:   res = a & b
        elif op == 0x1: res = (a ^ b) & MASK
        elif op == 0x2: res = (a - b) & MASK
        elif op == 0x3: res = (b - a) & MASK
        elif op == 0x4: res = (a + b) & MASK
        elif op == 0x5: res = (a + b + cin) & MASK
        elif op == 0x6: res = (a - b - (1 - cin)) & MASK
        elif op == 0x7: res = (b - a - (1 - cin)) & MASK
        elif op == 0xA: res = (a - b) & MASK
        elif op == 0xB: res = (a + b) & MASK
        elif op == 0xC: res = (a | b) & MASK
        elif op == 0xD: res = b & MASK
        elif op == 0xE: res = (a & ~b) & MASK
        elif op == 0xF: res = (~b) & MASK
        else:
            raise SystemExit(f"dp op {op:#x}")

        if S:
            self.flags_nz(res)
            if op in (0x4, 0x5, 0xB):
                full = a + b + (cin if op != 0x4 else 0)
                self.c = int(full > MASK)
                self.v = int((~(a ^ b) & (a ^ res) & 0x80000000) != 0)
            elif op in (0x2, 0x3, 0x6, 0x7, 0xA):
                self.c = int(a >= b)
                self.v = int(((a ^ b) & (a ^ res) & 0x80000000) != 0)
        if rd != 15:
            self.r[rd] = res


def emplace(m, addr, data):
    for i, b in enumerate(data):
        m.wb(addr + i, b)


def run_line(text_blob, line_bytes, entry=0x1299C, trace=False):
    text_bytes, rodata_bytes = text_blob
    m = Machine(text_bytes, rodata_bytes)
    fp = 0x30000
    buf = fp - 0x107C
    m.put_cstr(buf, line_bytes)
    m.ww(fp - 0x48, len(line_bytes))     # recvLine()'s return value
    m.r[11] = fp
    m.r[15] = entry

    saved = [0]
    argc = argv = None
    for _ in range(400000):
        # main() loops back to recvLine() for every line it does not accept.
        # Leaving the parser's own address range means it wants another line;
        # model that as "connection closed" so the emulation terminates.
        if not (0x12600 <= m.r[15] < 0x12D44):
            break
        callee = m.step()
        if callee is None:
            continue
        pc = m.r[14] - 4
        if trace:
            print(f"  bl {callee:#07x} from {pc:#07x}")
        if callee == 0x149D0:                                   # strlen
            m.r[0] = len(m.cstr(m.r[0]))
        elif callee == 0x14E30:                                 # strtok
            s, d = m.r[0], m.r[1]
            delims = m.cstr(d)
            if s:
                saved[0] = s
            p = saved[0]
            if not p:
                m.r[0] = 0
            else:
                while m.rb(p) and m.rb(p) in delims:
                    p += 1
                if not m.rb(p):
                    saved[0] = 0
                    m.r[0] = 0
                else:
                    start = p
                    while m.rb(p) and m.rb(p) not in delims:
                        p += 1
                    if m.rb(p):
                        m.wb(p, 0)
                        saved[0] = p + 1
                    else:
                        saved[0] = 0
                    m.r[0] = start
        elif callee == 0x14C48:                                 # strcpy
            m.put_cstr(m.r[0], m.cstr(m.r[1]))
            m.r[0] = m.r[0]
        elif callee == 0x14930:                                 # memset
            for i in range(m.r[2]):
                m.wb(m.r[0] + i, m.r[1])
            m.r[0] = m.r[0]
        elif callee == 0x15C38:                                 # malloc
            size = m.r[0]
            m.r[0] = m.heap
            m.heap += ((size + 7) & ~7) + 0x80
        elif callee == 0x13428:                                 # toupper
            c = m.r[0] & 0xFF
            m.r[0] = ord(chr(c).upper()) if 97 <= c <= 122 else c
        elif callee == 0x87FC:                                  # trim()
            # Verified against the binary's own ctype table: the only class bit
            # tested is 0x20, which is set for space, \t, \n, \r, \v, \f.
            buf = m.r[0]
            s = m.cstr(buf)
            stripped = s.strip(b" \t\n\r\v\f")
            m.put_cstr(buf, stripped)
            m.r[0] = buf
        elif callee == 0x9318:                                  # recvLine()
            # main() blocks here for the next line. One line was already in the
            # buffer, so model the next read as EOF: recvLine returns -1 and
            # main() falls back to initConnection(). Nothing is dispatched.
            break
        elif callee == 0xE820:                                  # processCmd(argc, argv)
            argc, argv = m.r[0], m.r[1]
            break
        else:
            raise SystemExit(f"unexpected call {callee:#x} from {pc:#x}")
    else:
        raise SystemExit("step limit reached")

    if argc is None:
        return None
    out = []
    for i in range(max(0, min(argc, 16))):
        a = m.rw(argv + 4 * i)
        out.append(m.cstr(a).decode("latin1") if a else None)
    return argc, out


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__.strip())
    zip_path, pw = sys.argv[1], sys.argv[2]
    _name, data = elfdump.load(zip_path, pw)
    secs = elfdump.sections(data)
    t, r = secs[".text"], secs[".rodata"]
    blob = (data[t["off"]:t["off"] + t["size"]],
            data[r["off"]:r["off"] + r["size"]])

    cases = sys.argv[3:] or [
        "!STDHEX,192.168.7.1,9999,30\n",
        "!STDHEX 192.168.7.1 9999 30\n",
        "! STDHEX 192.168.7.1 9999 30\n",
        "!stdhex 192.168.7.1 9999 30\n",
        "! STDHEX 192.168.7.1,9999,30\n",
        "!CNC 192.168.7.1 9999 30\n",
        "STDHEX 192.168.7.1 9999 30\n",
        "! STDHEX 192.168.7.1\n",
    ]
    for c in cases:
        line = c.encode("latin1").decode("unicode_escape").encode("latin1")
        try:
            res = run_line(blob, line)
        except SystemExit as exc:
            print(f"{c!r:42s} -> emulation error: {exc}")
            continue
        if res is None:
            print(f"{c!r:42s} -> no command dispatched (parser exits before processCmd)")
        else:
            argc, argv = res
            print(f"{c!r:42s} -> argc={argc} argv={argv}")


if __name__ == "__main__":
    main()
