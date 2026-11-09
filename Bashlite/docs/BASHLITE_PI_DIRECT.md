# Bashlite on the Pi 5 — direct runbook

Runs the accepted sample (`349d2476…b777`, ELF32 ARM, static) **natively on the
Pi 5**, with no REMnux and no VM rehearsal. The Pi is both the static-triage host
and the instrument that runs the sample.

`BASHLITE_32BIT_PLAN.md` still describes the *what*. This file changes *where*
each step happens and in what order. Where the two disagree on ordering, this
file wins — the order below is forced by one fact: `isolation-on.sh` sets
`OUTPUT DROP` and drops UDP/53, so **anything that needs the internet must run
before it is applied**.

Target host: Pi 5, Debian 13 aarch64, bench address `192.168.7.2`.
Operator host: laptop, `192.168.7.1`, runs the lab C2.

---

## 0. What this route costs, and what replaces it

| REMnux gave you | Here |
|---|---|
| A disposable box to hold the sample | The Pi is not disposable — **Phase P0's image is the rollback**, and the plaintext ELF lives in tmpfs, not on the SD card |
| Analysis tools preinstalled | Phase P1 install list, ~5 minutes |
| A host separate from the runner | Lost. Accepted: the Pi is a dedicated instrument, not a dev box |
| `qemu-arm-static` for ARM binaries | Not needed — `CONFIG_COMPAT` runs the sample natively, so behaviour is *more* representative than the VM rehearsal was |

The last row is the real gain. The VM rehearsal only ever checked workflow; this
route checks the actual code path.

**Precondition:** the Pi must be a device you can reimage without losing anything
you care about. If it is not, stop and use a VM.

---

## Phase P0 — Restore point

Power the Pi off and image the SD card from the laptop. Confirm the device name
first — this command destroys whatever it points at.

```bash
lsblk -o NAME,SIZE,MODEL,MOUNTPOINT
sudo dd if=/dev/sdX of=pi5-clean-$(date +%F).img bs=4M status=progress conv=fsync
sha256sum pi5-clean-$(date +%F).img > pi5-clean-$(date +%F).img.sha256
```

Fingerprint, into the thesis appendix and every manifest:

```bash
uname -a; cat /etc/os-release
vcgencmd get_throttled                  # must be 0x0
grep -E 'arm_freq|overclock|force_turbo' /boot/firmware/config.txt   # must be empty
id victim
sudo bash preflight.sh            # run it now, while the internet still works
```

**Why preflight now and not later:** its NETWORK section treats a `dpt:53` rule as
a failure ("package installs will fail"). After Phase P4 that rule exists *by
design*, so preflight will report a FAIL that is not a problem. Run it before
isolation; after isolation use the §1.3 checks instead.

**Gate:** image exists and hashes, `get_throttled` is `0x0`, no clock tuning.

---

## Phase P0.5 — Accounts, SSH, and the bench link

Three accounts, three jobs. Do not collapse them onto one.

| Account | Used for | Why separate |
|---|---|---|
| `emlab` | you, over SSH | created by Raspberry Pi Imager; has sudo |
| `victim` | the sample, via `--run-as` | no password, no sudo, owns only the sample directories |
| `root` | runner, GPIO, iptables | required by `--run-as` and by the trigger |

`victim` does not exist after imaging — Imager only creates `emlab`. Create it now:

```bash
sudo adduser --disabled-password --gecos "" victim
sudo passwd -l victim
sudo install -d -o victim -g victim -m 0750 \
     /home/victim/work/{tools,staging,shmsamples,manifests}
```

`--disabled-password` plus `passwd -l` means nobody can log in as `victim`; the account
exists only to own the process. `sudo -u victim` still works.

### Bench link — static, no default route

On the Pi:

```bash
sudo nmcli con add type ethernet ifname eth0 con-name bench-static \
     ipv4.method manual ipv4.addresses 192.168.7.2/24 \
     ipv4.never-default yes ipv6.method disabled
sudo nmcli con up bench-static
ip -4 addr show eth0          # 192.168.7.2/24
ip route                      # 192.168.7.0/24 only - no default route
```

On the laptop, give the USB-Ethernet adapter `192.168.7.1/24` with **no gateway**
(IPv4 properties → "Use the following IP address"; leave Default gateway and DNS
blank). Keep WiFi for the laptop's own internet; the bench NIC must not carry a
default route.

### SSH from the laptop

Switch to keys before the sample exists — a password on a malware host is a bad
trade.

```bash
ssh-keygen -t ed25519 -C "emlab bench"
ssh-copy-id emlab@192.168.7.2
ssh emlab@192.168.7.2 'uname -m; id'
```

`~/.ssh/config` on the laptop:

```
Host bench-pi
    HostName 192.168.7.2
    User emlab
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

Then `ssh bench-pi` works everywhere above.

**Two things that will bite you:**

- Re-imaging the Pi changes its SSH host key. Run `ssh-keygen -R 192.168.7.2` and
  reconnect. Otherwise you get a scary warning at the exact moment you are most
  tempted to type `yes` without reading it.
- On the bench link there is no DHCP and no DNS, so `pi5-em-target.local` will
  not resolve. Use the IP. mDNS is a provisioning-phase convenience only.

After Phase P4 the Pi stays reachable, but only from `192.168.7.1` on port 22 —
that is what `--admin` buys. `scp` keeps working; `apt` does not.

---

## Phase P1 — Tooling (needs internet)

```bash
sudo apt update
sudo apt install -y python3 python3-venv file binutils strace procps \
                    iptables iproute2 gpiod
python3 -m venv /home/victim/work/tools/venv
/home/victim/work/tools/venv/bin/pip install pyzipper capstone
```

Copy the scripts up. They go in `tools/`, never in the directory that will hold
the sample:

```bash
# laptop
scp Bashlite/runner/bashlite_runner.py Bashlite/isolation-on.sh isolation-off.sh \
    preflight.sh victim@192.168.7.2:/home/victim/work/tools/
scp Bashlite/analysis/elfdump.py Bashlite/analysis/simparse.py Bashlite/analysis/pool_check.py \
    victim@192.168.7.2:/home/victim/work/tools/
```

Re-confirm AArch32 execution before anything else depends on it:

```bash
# re-run the exit-42 probe built in pi5_setup/, or:
sudo apt install -y gcc-arm-linux-gnueabihf
printf 'int main(void){return 42;}' > /tmp/t.c
arm-linux-gnueabihf-gcc -static /tmp/t.c -o /tmp/t32
/tmp/t32; echo "exit=$?"          # must print 42
file /tmp/t32                     # ELF 32-bit LSB executable, ARM, EABI5, statically linked
```

**Gate:** exit code 42, and `qemu-arm-static` is *not* in the path.

---

## Phase P2 — Transfer and stage

Layout — the separation is deliberate (scripts must not sit next to untrusted data):

```
/home/victim/work/
├── tools/        scripts + venv
├── staging/      the encrypted zip, and only that
├── shmsamples/   tmpfs — the plaintext ELF, gone on reboot
└── manifests/    runner output
```

Transfer the **encrypted zip**, not the ELF. The plaintext binary then never
exists on Windows and never crosses the link in the clear.

```bash
# laptop
sha256sum 349d24768645262ce4bc0d75cdbd4b5b16c20c64a423b966a8215ed70740b777.zip
scp 349d2476….zip victim@192.168.7.2:/home/victim/work/staging/

# Pi — the zip hash must match what the laptop printed
sha256sum /home/victim/work/staging/349d2476….zip
```

Decrypt straight into tmpfs. Check first whether `/dev/shm` can execute — Debian
sometimes mounts it `noexec`, which would fail silently at the worst moment:

```bash
findmnt -no OPTIONS /dev/shm
```

If it contains `noexec`, mount a dedicated one instead (contents vanish on reboot,
which is the point):

```bash
sudo install -d -o victim -g victim -m 0750 /home/victim/work/shmsamples
sudo mount -t tmpfs -o rw,nosuid,nodev,size=64m,mode=0750 \
     -o uid=$(id -u victim),gid=$(id -g victim) emlab /home/victim/work/shmsamples
findmnt /home/victim/work/shmsamples      # must NOT show noexec
```

```bash
cat > /home/victim/work/tools/decrypt_zip.py <<'EOF'
#!/usr/bin/env python3
"""Decrypt one member of an AES zip to an explicit path. Run with `python3 -I`."""
import os, sys, pyzipper

zip_path, member, out_path, password = sys.argv[1:5]
with pyzipper.AESZipFile(zip_path) as zf:
    zf.setpassword(password.encode())
    with zf.open(member) as src, open(out_path, "wb") as dst:
        dst.write(src.read())
print(f"{out_path}: {os.path.getsize(out_path)} bytes")
EOF
chmod 0700 /home/victim/work/tools/decrypt_zip.py

# list members first - decrypt by the exact name you see
/home/victim/work/tools/venv/bin/python -I -c \
  'import sys,pyzipper; z=pyzipper.AESZipFile(sys.argv[1]); z.setpassword(b"infected"); print("\n".join(z.namelist()))' \
  /home/victim/work/staging/349d2476….zip

sudo /home/victim/work/tools/venv/bin/python -I /home/victim/work/tools/decrypt_zip.py \
  /home/victim/work/staging/349d2476….zip \
  349d24768645262ce4bc0d75cdbd4b5b16c20c64a423b966a8215ed70740b777.elf \
  /home/victim/work/shmsamples/bashlite.bin infected
sudo chown victim:victim /home/victim/work/shmsamples/bashlite.bin
sudo chmod 0750 /home/victim/work/shmsamples/bashlite.bin
```

---

## Phase P3 — Static verification on the Pi

This replaces the REMnux triage pass. It is read-only: nothing here executes the
sample. It confirms the bytes on the Pi are the bytes that were triaged.

```bash
cd /home/victim/work/shmsamples
sha256sum bashlite.bin                 # 349d2476…b777, exactly
file bashlite.bin                      # ELF 32-bit LSB executable, ARM, EABI5, statically linked
readelf -h bashlite.bin | grep -E 'Class|Machine|Flags|Entry'
readelf -S bashlite.bin | grep -E 'symtab|strtab|rodata'
strings -a -n 8 bashlite.bin | grep -E '181\.214\.147\.11|^STDHEX$|^CNC$|snoopy'
```

The last line is the cheap consistency check against
`analysis_notes/STATIC_TRIAGE_349d2476.md`: the C2 endpoint, the two command
tokens and the source name should all appear.

Optional, to re-derive the wire format on this host rather than trusting the
recorded one:

```bash
/home/victim/work/tools/venv/bin/python -I /home/victim/work/tools/simparse.py \
  /home/victim/work/staging/349d2476….zip infected
```

**Gate:** SHA-256 matches. If it does not, delete the file, re-transfer, and stop
— do not "fix" it and continue.

---

## Phase P4 — Isolation

Inspect, then apply:

```bash
sudo bash /home/victim/work/tools/isolation-on.sh \
     --admin 192.168.7.1 --c2 192.168.7.1 --c2-port 999 \
     --owner-user victim --dry-run
sudo bash /home/victim/work/tools/isolation-on.sh \
     --admin 192.168.7.1 --c2 192.168.7.1 --c2-port 999 \
     --owner-user victim
```

Verify (§1.3 of the main plan):

```bash
curl -m 5 -s http://1.1.1.1 >/dev/null; echo "curl=$?"    # non-zero
nc -z -w 3 1.1.1.1 80;                echo "nc=$?"         # non-zero
sudo iptables -L OUTPUT -n -v | head -20                   # policy DROP
sudo iptables -t nat -L OUTPUT -n -v | head -20            # DNAT rules present, 0 hits
```

Then the runner's own gate — this is the one that matters, because it parses the
ruleset instead of trusting the script's own report:

```bash
sudo python3 /home/victim/work/tools/bashlite_runner.py \
  --sample /home/victim/work/shmsamples/bashlite.bin \
  --count 1 --duration 2.5 --manifest /home/victim/work/manifests/e0-containment.json
```

**Gate:** dry run exits 0 and the containment verdict is `full`. Anything else
means the ruleset has a hole the runner can see; do not use
`--skip-containment-check` to get past it.

---

## Phase P5 — Ladder

Start the C2 on the laptop. Observe mode logs without sending anything:

```bash
python3 Bashlite/c2/c2_server.py --mode observe --bind 192.168.7.1 --port 999 \
        --log Bashlite/runs/discover-$(date +%H%M).jsonl
```

**E1 — mimic.** Proves the whole path (DNAT, privilege drop, marker sweep) without
the sample. This is the step that isolates "the machinery is broken" from "the
sample is not doing what you think".

```bash
cat > /tmp/mimic.c <<'EOF'
#include <arpa/inet.h>
#include <string.h>
#include <unistd.h>
int main(void) {
    char banner[] = "mimic: hello\n";
    int s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET;
    a.sin_port = htons(999);
    a.sin_addr.s_addr = inet_addr("181.214.147.11");   /* the real C2, DNAT'd away */
    if (connect(s, (void *)&a, sizeof a) < 0) return 1;
    write(s, banner, strlen(banner));
    sleep(2);
    close(s);
    return 0;
}
EOF
arm-linux-gnueabihf-gcc -static /tmp/mimic.c -o /home/victim/work/tools/mimic
sudo python3 /home/victim/work/tools/bashlite_runner.py \
  --sample /home/victim/work/tools/mimic --expected-hash $(sha256sum /home/victim/work/tools/mimic | cut -d' ' -f1) \
  --execute --run-as victim --software-trigger \
  --count 1 --duration 2.5 --manifest /home/victim/work/manifests/e1-mimic.json
```

**E2 — real sample, observe.** The bot speaks first, so the log should contain an
`accept` and one received line even though the server sends nothing:

```bash
sudo python3 /home/victim/work/tools/bashlite_runner.py \
  --sample /home/victim/work/shmsamples/bashlite.bin \
  --expected-hash 349d24768645262ce4bc0d75cdbd4b5b16c20c64a423b966a8215ed70740b777 \
  --execute --run-as victim --gpio-pin 17 \
  --count 1 --duration 2.5 --manifest /home/victim/work/manifests/e2-observe.json
```

**E3 — real sample, scripted.** Restart the C2 in serve mode first:

```bash
python3 Bashlite/c2/c2_server.py --mode serve --bind 192.168.7.1 --port 999 \
        --script Bashlite/c2/c2_script.json --sink-port 9999 --flood-seconds 3 \
        --log Bashlite/runs/run01.jsonl --summary Bashlite/runs/run01.json
```

```bash
sudo python3 /home/victim/work/tools/bashlite_runner.py \
  --sample /home/victim/work/shmsamples/bashlite.bin \
  --expected-hash 349d24768645262ce4bc0d75cdbd4b5b16c20c64a423b966a8215ed70740b777 \
  --execute --run-as victim --gpio-pin 17 \
  --count 3 --duration 2.5 --cooldown 0.5 \
  --manifest /home/victim/work/manifests/run01.json

python3 Bashlite/c2/c2_server.py --print-script     # the timeline you think you sent
```

**Gate for E3 (all must hold):**

- `send` events in the JSONL at roughly 60 / 1200 / 2200 ms after each `accept`
- sink counters in `runs/run01.json` are non-zero
- `sudo pgrep -a bashlite` prints nothing after the run
- `sudo iptables -t nat -L OUTPUT -n -v` shows DNAT hits — this is the proof the
  sample dialled its live C2 and was redirected, not blocked

---

## Phase P6 — Prove the window is not idle

An idle trace teaches a classifier nothing, and this is the only check that
catches it before capture. The C2 must be running (see the note below).

```bash
sudo -u victim bash -c 'timeout 2.5 /home/victim/work/shmsamples/bashlite.bin & \
                        sleep 0.4; ps -o pid,pcpu,cmd -C bashlite.bin'
sudo -u victim strace -f -c -o /tmp/syscalls.txt -w timeout 2.5 \
     /home/victim/work/shmsamples/bashlite.bin
grep -E 'socket|connect|sendto|recvfrom' /tmp/syscalls.txt
```

Pass: CPU roughly above 5 %, thousands of syscalls including `socket`/`connect`,
and `pgrep -a bashlite` empty afterwards.

**If CPU is near zero, the C2 is not answering.** That is the failure mode this
sample has: it sends its banner, blocks on `recvLine`, and if nothing comes back
it sits still. Do not proceed to capture on a near-zero trace.

---

## Phase P7 — Capture

Unchanged from the main plan, Phase 6: `--duration 2.5`, 2 MHz, 5 000 000 points,
`vcgencmd get_throttled` = `0x0` before and after every session, and never move
the Pi or the probe inside one dataset.

---

## Phase P8 — Cleanup

```bash
sudo pkill -f bashlite.bin; sudo pgrep -a bashlite      # must be empty
sudo umount /home/victim/work/shmsamples                # plaintext ELF gone
shred -u /home/victim/work/staging/*.zip                # or keep for provenance - record which
sudo bash /home/victim/work/tools/isolation-off.sh
```

`shred` on an SD card is unreliable: wear levelling keeps old blocks. **The only
real cleanup is restoring the P0 image.** Restore it on any device you intend to
use for anything other than this experiment, and archive the P0 image itself as
the "before" half of the provenance record.

Archive: sample SHA-256 and source URL, `STATIC_TRIAGE_349d2476.md`,
`c2_script.json` + version, the C2 JSONL and summary, every manifest, the
fingerprint, and a note of any deviation.

---

## Risks specific to this route

| Risk | Effect | Mitigation |
|---|---|---|
| Plaintext ELF on the instrument's own disk | forensic residue on an SD card you cannot reliably wipe | tmpfs execution (P2) + image restore (P8) |
| No disposable host | a mistake is a mistake on the instrument | P0 image first; Pi must not be the primary dev box |
| `isolation-on.sh` runs before `apt` | installs fail and the run is half-configured | all internet steps are P1, isolation is P4 |
| `/dev/shm` mounted `noexec` | sample fails with 126 at the worst moment | `findmnt` check, dedicated tmpfs |
| Preflight's DNS check fails after isolation | a FAIL that looks alarming but is by design | run preflight in P0, use §1.3 checks after P4 |
| Sample runs as `root` if `--run-as` is forgotten | runner refuses (`--allow-root` is opt-in) — fails safe | keep `--run-as victim` in every `--execute` invocation |

## What this route still cannot fix

The goodware group in this repo is 64-bit Python; the malware is 32-bit ARM. A
classifier trained on that pair can learn *architecture*, not *malice*. Running
directly on the Pi changes nothing here — it is the same open gap as before, and
it must be resolved (a 32-bit ARM benign group) or written down as a limitation
before any training happens.
