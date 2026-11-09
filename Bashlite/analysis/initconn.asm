0x0123cc  mov      ip, sp
0x0123d0  push     {fp, ip, lr, pc}
0x0123d4  sub      fp, ip, #4
0x0123d8  sub      sp, sp, #0x210
0x0123dc  sub      r3, fp, #0x210
0x0123e0  mov      r0, r3
0x0123e4  mov      r1, #0
0x0123e8  mov      r2, #0x200
0x0123ec  bl       #0x14930
0x0123f0  ldr      r3, [pc, #0x158]
0x0123f4  ldr      r3, [r3]
0x0123f8  cmp      r3, #0
0x0123fc  beq      #0x1241c
0x012400  ldr      r3, [pc, #0x148]
0x012404  ldr      r3, [r3]
0x012408  mov      r0, r3
0x01240c  bl       #0x133f4
0x012410  ldr      r2, [pc, #0x138]
0x012414  mov      r3, #0
0x012418  str      r3, [r2]
0x01241c  ldr      r3, [pc, #0x130]
0x012420  ldr      r3, [r3]
0x012424  cmp      r3, #0
0x012428  bne      #0x1243c
0x01242c  ldr      r2, [pc, #0x120]
0x012430  mov      r3, #0
0x012434  str      r3, [r2]
0x012438  b        #0x12450
0x01243c  ldr      r3, [pc, #0x110]
0x012440  ldr      r3, [r3]
0x012444  add      r2, r3, #1
0x012448  ldr      r3, [pc, #0x104]
0x01244c  str      r2, [r3]
0x012450  sub      r1, fp, #0x210
0x012454  ldr      r3, [pc, #0xf8]
0x012458  ldr      r2, [r3]
0x01245c  ldr      r3, [pc, #0xf4]
0x012460  ldr      r3, [r3, r2, lsl #2]
0x012464  mov      r0, r1
0x012468  mov      r1, r3
0x01246c  bl       #0x14c48
0x012470  mov      r3, #0x1b40
0x012474  add      r3, r3, #6
0x012478  str      r3, [fp, #-0x10]
0x01247c  sub      r3, fp, #0x210
0x012480  mov      r0, r3
0x012484  mov      r1, #0x3a
0x012488  bl       #0x14d28
0x01248c  mov      r3, r0
0x012490  cmp      r3, #0
0x012494  beq      #0x124e0
0x012498  sub      r3, fp, #0x210
0x01249c  mov      r0, r3
0x0124a0  mov      r1, #0x3a
0x0124a4  bl       #0x14d28
0x0124a8  mov      r3, r0
0x0124ac  add      r3, r3, #1
0x0124b0  mov      r0, r3
0x0124b4  bl       #0x17168
0x0124b8  mov      r3, r0
0x0124bc  str      r3, [fp, #-0x10]
0x0124c0  sub      r3, fp, #0x210
0x0124c4  mov      r0, r3
0x0124c8  mov      r1, #0x3a
0x0124cc  bl       #0x14d28
0x0124d0  mov      r3, r0
0x0124d4  mov      r2, r3
0x0124d8  mov      r3, #0
0x0124dc  strb     r3, [r2]
0x0124e0  mov      r0, #2
0x0124e4  mov      r1, #1
0x0124e8  mov      r2, #0
0x0124ec  bl       #0x15a48
0x0124f0  mov      r2, r0
0x0124f4  ldr      r3, [pc, #0x54]
0x0124f8  str      r2, [r3]
0x0124fc  ldr      r3, [pc, #0x4c]
0x012500  ldr      r3, [r3]
0x012504  sub      r2, fp, #0x210
0x012508  mov      r0, r3
0x01250c  mov      r1, r2
0x012510  ldr      r2, [fp, #-0x10]
0x012514  mov      r3, #0x1e
0x012518  bl       #0x95f0
0x01251c  mov      r3, r0
0x012520  cmp      r3, #0
0x012524  bne      #0x12534
0x012528  mov      r3, #1
0x01252c  str      r3, [fp, #-0x218]
0x012530  b        #0x1253c
0x012534  mov      r3, #0
0x012538  str      r3, [fp, #-0x218]
0x01253c  ldr      r3, [fp, #-0x218]
0x012540  mov      r0, r3
0x012544  sub      sp, fp, #0xc
0x012548  ldm      sp, {fp, sp, lr}
0x01254c  bx       lr
0x012550  andeq    sl, r2, r8, lsl r8
0x012554  andeq    sl, r2, r8, lsl #11
0x012558  andeq    sl, r2, r8, ror #10
