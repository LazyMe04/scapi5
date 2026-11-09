"""Disassemble one function from the staged sample, read-only, in memory.

Usage: python -I func_dump.py <zip> infected 0xE820 0x400
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

import capstone
import elfdump


def main():
    if len(sys.argv) < 5:
        sys.exit(__doc__.strip())
    _name, data = elfdump.load(sys.argv[1], sys.argv[2])
    secs = elfdump.sections(data)
    start = int(sys.argv[3], 16)
    length = int(sys.argv[4], 0)
    t = secs['.text']
    code = data[t['off'] + (start - t['addr']):][:length]
    md = capstone.Cs(capstone.CS_ARCH_ARM,
                     capstone.CS_MODE_ARM | capstone.CS_MODE_LITTLE_ENDIAN)
    md.skipdata = True
    for ins in md.disasm(code, start):
        print(f'0x{ins.address:06x}  {ins.mnemonic:8s} {ins.op_str}')


if __name__ == '__main__':
    main()
