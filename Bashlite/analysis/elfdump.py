"""Read-only static inspection of the staged Bashlite sample.

The zip is decrypted in memory; nothing is ever written to disk as an ELF.
Usage: python -I elfdump.py <zip> <password> [--func 0xADDR] [--len N]
"""
import json
import os
import re
import struct
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
import pyzipper
import capstone

BASE = 0x8000


def load(path, pw):
    with pyzipper.AESZipFile(path) as z:
        z.setpassword(pw.encode())
        name = z.infolist()[0].filename
        return name, z.read(z.infolist()[0])


def sections(data):
    e_shoff = struct.unpack_from('<I', data, 32)[0]
    e_shentsize = struct.unpack_from('<H', data, 46)[0]
    e_shnum = struct.unpack_from('<H', data, 48)[0]
    e_shstrndx = struct.unpack_from('<H', data, 50)[0]
    secs = [struct.unpack_from('<IIIIIIIIII', data, e_shoff + i * e_shentsize)
            for i in range(e_shnum)]
    so = secs[e_shstrndx][4]

    def nm(o):
        return data[so + o:data.index(b'\x00', so + o)].decode('latin1')

    return {nm(s[0]): {'addr': s[3], 'off': s[4], 'size': s[5]} for s in secs}


def symbols(data, secs):
    sy, st = secs['.symtab'], secs['.strtab']
    sto = st['off']
    out = []
    for i in range(sy['size'] // 16):
        name, val, size, info, other, shndx = struct.unpack_from('<IIIBBH', data, sy['off'] + i * 16)
        e = data.index(b'\x00', sto + name)
        out.append({'name': data[sto + name:e].decode('latin1'), 'addr': val,
                    'size': size, 'type': info & 0xf, 'shndx': shndx})
    return out


def rodata_strings(data, secs):
    r = secs['.rodata']
    out = {}
    # Virtual address = section vaddr + offset of the string inside the section.
    # Do not hardcode 0x16310 here: that is this one file's file offset, and
    # using it silently shifted every address by the section's own offset.
    for m in re.finditer(rb'[\x20-\x7e]{3,}', data[r['off']:r['off'] + r['size']]):
        out[m.start() + r['addr']] = m.group().decode('latin1')
    return out


def pool(data, secs, start, end, strs):
    """Map <literal address> -> list of (instruction addr, register)."""
    t = secs['.text']
    code = data[t['off']:t['off'] + t['size']]
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM | capstone.CS_MODE_LITTLE_ENDIAN)
    # Without this, capstone stops at the first data word it cannot decode and
    # every later reference is silently missed.
    md.skipdata = True
    hits = {}
    for ins in md.disasm(code, t['addr']):
        if ins.address < start or ins.address >= end:
            continue
        if ins.mnemonic == 'ldr' and 'pc' in ins.op_str:
            parts = [p.strip().rstrip(']') for p in ins.op_str.split(',')]
            if len(parts) < 3 or not parts[2].startswith('#'):
                continue
            lit = ins.address + 8 + int(parts[2][1:], 0)
            if not (t['addr'] <= lit < t['addr'] + t['size']):
                continue
            val = struct.unpack_from('<I', data, lit - t['addr'] + t['off'])[0]
            if val in strs:
                hits.setdefault(val, []).append((ins.address, parts[0]))
    return hits


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__.strip())
    zip_path, pw = sys.argv[1], sys.argv[2]
    name, data = load(zip_path, pw)
    secs = sections(data)
    syms = symbols(data, secs)
    strs = rodata_strings(data, secs)
    args = sys.argv[3:]
    func = None
    length = None
    for i, a in enumerate(args):
        if a == '--func':
            func = int(args[i + 1], 16)
        if a == '--len':
            length = int(args[i + 1], 0)
    if func is None:
        print(json.dumps({'name': name, 'size': len(data), 'sections': secs,
                          'strings': len(strs)}, indent=2))
        return
    if length is None:
        for s in syms:
            if s['addr'] == func and s['size']:
                length = s['size']
    hits = pool(data, secs, func, func + (length or 0), strs)
    print(f'=== string references inside {func:#x} .. {func + (length or 0):#x} ===')
    for v, refs in sorted(hits.items(), key=lambda kv: min(r[0] for r in kv[1])):
        print(f'{strs[v]!r:60s} <- ' + ', '.join(f'{a:#x}[{r}]' for a, r in refs))


if __name__ == '__main__':
    main()
