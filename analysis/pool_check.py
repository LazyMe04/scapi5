"""Resolve literal-pool pointers used by main() to their .rodata strings.

Read-only: the zip is decrypted in memory, nothing is written as an ELF.
Usage: python -I pool_check.py <zip> infected 0x12d60 0x12d48 ...
"""
import sys
import struct

sys.path.insert(0, r'C:\Users\Minh_Trinh\Downloads\bench\.pylib')
sys.path.insert(0, r'C:\Users\Minh_Trinh\Downloads\bench\analysis')

import pyzipper
import elfdump


def cstr(data, addr, secs):
    """Read a NUL-terminated string living at virtual address `addr`."""
    for name, s in secs.items():
        if s['addr'] and s['addr'] <= addr < s['addr'] + s['size']:
            off = s['off'] + (addr - s['addr'])
            end = data.index(b'\x00', off)
            return data[off:end].decode('latin1'), name
    return None, None


def main():
    _name, data = elfdump.load(sys.argv[1], sys.argv[2])
    secs = elfdump.sections(data)
    text = secs['.text']
    for arg in sys.argv[3:]:
        lit = int(arg, 16)
        word = struct.unpack_from('<I', data, text['off'] + (lit - text['addr']))[0]
        s, sec = cstr(data, word, secs)
        print(f'literal @{lit:#x} = {word:#010x} -> {s!r} [{sec}]')


if __name__ == '__main__':
    main()
