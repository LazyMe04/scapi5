"""Disassemble one function from the staged sample, read-only, in memory.

Usage: python -I func_dump.py <zip> infected 0xE820 0x400
"""
import sys

sys.path.insert(0, r'C:\Users\Minh_Trinh\Downloads\bench\.pylib')
sys.path.insert(0, r'C:\Users\Minh_Trinh\Downloads\bench\analysis')

import capstone
import elfdump


def main():
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
