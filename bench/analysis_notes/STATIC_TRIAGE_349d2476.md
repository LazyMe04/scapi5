# Static triage — 349d2476…b777

Sample: `349d24768645262ce4bc0d75cdbd4b5b16c20c64a423b966a8215ed70740b777.elf`
Triaged: 2026-11-05. Method: in-memory decrypt of the MalwareBazaar ZIP (password
`infected`), parsed with a read-only Python ELF reader. **The ELF was never written to
disk and never executed.**

## Analysis tools (all read-only, all on Windows, none of them execute the sample)

| Tool | Purpose |
|---|---|
| `analysis/elfdump.py` | ELF sections, symbols, `.rodata` strings, literal-pool → string references |
| `analysis/func_dump.py` | disassemble one function by address (`capstone`, ARM mode) |
| `analysis/pool_check.py` | resolve a PC-relative literal to the string it points at |
| `analysis/simparse.py` | **execute the sample's own line parser** and print `argc`/`argv` |
| `analysis/fakebot.py` | loopback bot stand-in, to test the C2 without malware |

Run them with `python -I` and pass the zip path as an argument; they decrypt in
memory and never write an ELF.

`simparse.py` is the one that matters for the protocol: it runs the real ARM
instructions of `main()`'s parser on a synthetic stack, re-implementing only
`strlen`, `strtok`, `strcpy`, `memset`, `malloc`, `toupper` and `trim`. Reading
the disassembly is not reliable enough here — an earlier pass through the
disassembler produced the wrong answer for the wire format, which is exactly why
the emulator exists.

## Identity

| Field | Value |
|---|---|
| SHA-256 | `349d24768645262ce4bc0d75cdbd4b5b16c20c64a423b966a8215ed70740b777` |
| MD5 | `9d5a922a637ed89863e440b87d5d564d` |
| Size | 147 686 bytes |
| Format | ELF32, little-endian, `e_type = EXEC` |
| Machine | `EM_ARM` (40), `e_flags = 0x04000002` → EABI v4 (`0x04…` Tag_conformance "4.09"), `EF_ARM_EABI_VER4`, `EF_ARM_HASENTRY` |
| Linkage | **static** — no `PT_INTERP`, no `PT_DYNAMIC`; only two `PT_LOAD` + `PT_ARM_EXIDX` + `PT_GNU_STACK` |
| Entry | `0x81b0` (`.text` at `0x80d0`) |
| Packing | **none** — no `UPX!` magic, normal section table with `.symtab`/`.strtab` |
| Symbols | **not stripped** — 1 297 symbols, 496 functions, `main`, `processCmd`, `initConnection` all named |
| Toolchain | uClibc (symbols `__uClibc_main`, `__GI_*`), compiled by GCC **4.2.1** (one object by GCC 3.3.2) |
| Source file name | `snoopy.c` in `.symtab` STT_FILE |

### Acceptance against BASHLITE_32BIT_PLAN.md §2

- [x] machine is ARM, 32-bit, EABI5-era ARMv4T code — machine `EM_ARM`, class ELF32, `Tag_CPU_arch = v4T`
- [x] **statically linked** — no interpreter, so no `ld-linux-armhf.so.3` dependency
- [x] family label bashlite/gafgyt — MalwareBazaar + Triage both `gafgyt`; strings confirm the Bashlite/Gafgyt command set
- [x] source URL, date, SHA-256, first-seen, packer status recorded (this file)
- [ ] stored on the analyser host — **pending** (quarantined as an encrypted zip in
      `malware_staging/`; the plaintext ELF has never been written to disk)

## Build facts relevant to the EM measurement

`Tag_CPU_arch = v4T` and `EF_ARM_EABI_VER4` mean this is **ARMv4T Thumb-interworking-era
code**, not ARMv7. It runs on the Pi 5 only under the ARM32 compat layer, and the
instruction mix (`ldr`/`mov`/`bl`-heavy, almost no NEON/VFP) is the old 32-bit profile.
That is exactly the "in-the-wild 2016-2020 sample" shape the paper used — do not rebuild.

## C2 configuration

```
0x01e310  "181.214.147.11:999"
0x01e63c  "8.8.8.8"              (used with /proc/net/route for getOurIP)
0x01e644  "/proc/net/route"
```

`initConnection()` (0x123cc) parses the config string at runtime: it copies the
selected entry into a 0x200 stack buffer, sets a default port of `0x1b46` (6982),
then `strchr(':')` — if a colon is present it `atoi()`s the suffix as the port and
NUL-terminates the address. For `181.214.147.11:999` that yields address
`181.214.147.11`, port `999`. It then calls `connectTimeout()` at `0x95f0` with a
30 s timeout (`mov r3, #0x1e`).

The pointer table at 0x2a568 holds 8 entries:

```
[0] 0x1e310  "181.214.147.11:999"      <- the C2
[1] 0x1e324  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/60..."
[2] 0x1e398  "Mozilla/5.0 (Windows NT 6.1; Win64; x64) ... Chrome/60..."
[3] 0x1e40c  "Mozilla/5.0 (X11; Linux x86_64) ... Chrome/44..."
         ...  [4]..[7] more User-Agent strings
```

Only `[0]` is ever used as a C2. The index lives at 0x2a588, is initialised to
`-1`, and the update logic is `if (index == 0) index = 0; else index++` — so it
**clamps at 0** and the sample retries the same endpoint every time. Entries `[1]`
onward are the `User-Agent:` values used by the HTTP-flood primitives, not
fallback C2s. `main()` retries forever:

```
0x01264c  bl initConnection
0x012650  cmp r3, #0
0x012658  beq 0x12668          ; connected -> banner
0x01265c  mov r0, #5
0x012660  bl sleep             ; 5 s backoff, loop
```

So the window for the measurement starts at `accept()`, and the bot sends its banner
**before** it reads any command.

## Protocol (confirmed by emulating the sample's own parser)

The wire format below was recovered by **executing the sample's parser instructions**
(`main()` 0x1299c–0x12cb4) on a synthetic stack — not by reading disassembly.
The tool is `analysis/simparse.py`; it re-implements only `strlen`, `strtok`,
`strcpy`, `memset`, `malloc`, `toupper` and `trim`, and reports the `argc`/`argv`
that `processCmd()` receives.

1. On connect, `main()` sends one banner line via `sockprintf` (0x912c) and then
   blocks in `recvLine` (0x9318). **The bot speaks first**; the C2 has nothing to
   send on `accept()`, so `handshake_at_ms` must be 0.
2. `trim()` (0x87fc) strips leading and trailing whitespace only. It tests ctype
   class bit `0x20` against the binary's own `__ctype_b` table (0x20f08), which is
   set for space, `\t`, `\n`, `\r`, `\v`, `\f` — nothing else. **`trim()` does not
   lowercase anything.**
3. `main()` requires the line to start with `!` (`cmp r3, #0x21`), then takes
   `buf+1`, skips to the next space, NUL-terminates there, and resumes at the
   *next* character. It then uppercases that token in place with `toupper`
   (0x13428) — so the **command word is case-insensitive, the arguments are not**.
4. `strtok(p, " ")` (delimiter string at 0x1eaec) splits the rest into arguments.
5. `processCmd(argc, argv)` (0xe820) compares `argv[0]` against this exact, ordered
   list (35 string comparisons, verified by scanning every literal reference):

   `STDHEX  CNC  TCP  TCP-H  UDPHIT  UDPFULL  UDPKILL  UDPBYPASS  UDPCUSTOM  OVH
   OVH-SMACK  OVH-SAS  OVH-SMELL  C-UDP  IPS-UDP  DISCORD  GAME  FORTNITE  MINECRAFT
   VALVE  FIVEM  HANDSHAKE  TS3  S4MP  SAMP  SUBNET  PTS3  SAMP2  U-BYPASS  U-PPS
   U-GBPS  RAND  STOP  stop  Stop`

   Flood branches require `argc > 3`.

### Exact wire format

| Line the C2 sends | `argc` | `argv` | Result |
|---|---|---|---|
| `! STDHEX a b c` | 4 | `STDHEX a b c` | **dispatched** |
| `! stdhex a b c` | 4 | `STDHEX a b c` | dispatched (command case-insensitive) |
| `!STDHEX a b c` | 3 | `a b c` | **ignored** — the command name is eaten |
| `!  STDHEX a b c` (two spaces) | 5 | `` STDHEX a b c`` | **ignored** |
| `! STDHEX a,b,c` | 2 | `STDHEX a,b,c` | **ignored** — one over-long token |
| `STDHEX a b c` (no `!`) | — | — | never parsed |

So the format is exactly **`!` + one space + COMMAND + space-separated arguments**.
A comma-joined line collapses to a single token and the bot drops it silently.
This is *not* the classic `.tcp`/`.udp` Bashlite vocabulary.

### Argument order for the two usable primitives

`processCmd` reads `argv[1]` as the target *string* and also runs `atoi()` on it as
a sanity check (`> 0`), then `atoi(argv[2])` = port and `atoi(argv[3])` = duration:

```
STDHEX <target> <port> <duration>
```

Because `atoi("192.168.7.1") == 192 > 0`, a dotted quad passes the check. A
hostname such as `google.com` would `atoi()` to 0 and be **rejected** — the target
must be a numeric address. `STDHEX` resolves it with `gethostbyname` (0x157e4),
`CNC` with `inet_addr` (0x157bc), so a dotted quad also avoids any DNS lookup
being attempted at all.

What each one does, from disassembly:

- `SendSTDHEX` (0x9d44) — `gethostbyname`, `socket(AF_INET, SOCK_STREAM)`,
  `connect`, then repeated **1460-byte `send()`** calls until the duration
  expires, then `close` + `_exit(0)` in the forked child.
- `sendCNC` (0x9fbc) — `inet_addr`, then a loop of `socket`/`connect`/
  `sleep(1)`/`close` until the duration expires. Generates connections, not data.

Both are reached through `listFork()` (0x9864), so the work happens in a child
process that the runner's leftover sweep can find by its `EMLAB_RUN_ID` marker.

## Persistence and hunt surface

Strings in `.rodata`:

```
0x20c24  /usr/bin/python     0x20c38  /usr/bin/python3
0x20c4c  /usr/bin/perl       0x20c5c  /usr/sbin/telnetd
```

These are the standard Gafgyt `getpids`/killer targets, not this sample's own
persistence. There is **no** `crontab`, `rc.local`, no `/etc/init.d` write, no
`/dev/watchdog` string — this build is memory-resident with `setsid()` + fork.
That matters for Phase 7 cleanup: killing the process and the env-marker sweep in
`bashlite_runner.py` should be sufficient; no file artefacts to remove.

## Notes and oddities

- `.comment` repeats `GCC: (GNU) 4.2.1` ~160 times — a multi-object static link, normal
  for this family, not an artefact of a packer.
- `0x1e7b0`…`0x1e9f0` is a table of 20-character alnum strings (nickname / key
  candidates), and `0x1e9f0`/`0x1ea00` hold `YakuzaBotnet` / `Scarface1337` — author tags,
  useful as a YARA anchor.
- `0x20785` contains `dedsecrunsyoulilassnigga` inside a run of `A`s — sandbox-evasion
  padding / graffiti, also a good YARA anchor.
- `0x20890`…`0x209b0` is a DNS-style fake-Host table for the HTTP flood primitives:
  `www.google.com`, `live.com`, `office.com`, `digikala.com`, `salesforce.com`,
  `sogou.com`, `discord.com`, `wikihow.com`, `manoramaonline.com`. Note the labels are
  stored with length bytes (`\x03com`), i.e. wire-format DNS names, not plain strings.
- Triage behavioural run: 150 s, **0 TCP / 0 UDP connections**, only `/proc/net/route`
  read. Consistent with the code: the bot connects once at startup, and if the C2 is
  unreachable it sleeps 5 s and retries — the sandbox had no listener on 999, so nothing
  was captured. It does not mean the sample is inert.
