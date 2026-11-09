# Bashlite runner — VM rehearsal runbook

**Status:** draft, ready for the first VM run.
**Scope:** proves the runner harness (start → time-bound → kill → sweep → manifest) works
on the run-2 ARM64 QEMU guest.
**Not in scope:** EM capture. A VM has no electromagnetic signature. The same script with
GPIO 17 enabled is what produces traces on the Pi 5.

---

## 0. Decision record

| Question | Answer |
|---|---|
| VM | run-2 ARM64 QEMU guest (`~/arm64-vm/` on REMnux), Ubuntu 24.04, kernel 6.8, snapshot `cloudinit-done` |
| Sample | **not yet obtained.** Phase C covers acquisition and verification |
| Hardware trigger | `--software-trigger` (no GPIO in the guest) |
| Runner | `Bashlite/runner/bashlite_runner.py` v2.0.0 |
| Live malware execution | **not approved** until E1 and E2 pass |

The runner refuses `--execute` when: the host is not Linux, the caller is root (unless
`--allow-root`), `--expected-hash` is missing, or containment is not verifiably active
(unless `--skip-containment-check` / `--allow-partial-containment` is given explicitly).

Exit codes: `0` ok · `2` containment refused · `3` sample verification failed ·
`4` abort (exec format error) · `130` interrupted.

---

## Phase A — Bring the VM chain up

```bash
# A1. REMnux reachable?
ssh remnux "echo ok; uname -m"                     # -> ok / x86_64

# A2. Reset the guest to the clean snapshot, then boot (approval: yes)
ssh remnux "~/arm64-vm/stop-arm64.sh; \
             qemu-img snapshot -a cloudinit-done ~/arm64-vm/images/ubuntu-arm64-malware-test.qcow2; \
             ~/arm64-vm/start-arm64.sh"

# A3. Wait for boot and open the tunnel
ssh remnux "~/arm64-vm/wait-guest.sh"              # -> ARM64_GUEST_READY
ssh -N -f -L 2232:127.0.0.1:2222 remnux
ssh -p 2232 ubuntu@127.0.0.1                        # in guest: uname -m -> aarch64
```

Rollback: `ssh remnux "~/arm64-vm/stop-arm64.sh"`.

---

## Phase B — Containment inside the guest (mandatory before any sample)

QEMU user-mode NAT lets the guest reach the internet. Close that first.

```bash
# B1. Default-drop egress, allow loopback and replies only (approval: yes)
sudo iptables  -P OUTPUT DROP
sudo iptables  -A OUTPUT -o lo -j ACCEPT
sudo iptables  -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo ip6tables -P OUTPUT DROP
sudo ip6tables -A OUTPUT -o lo -j ACCEPT
sudo ip6tables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# B2. Verify it really blocks (both commands must fail)
sudo iptables -S OUTPUT
curl -m 5 -s http://1.1.1.1 >/dev/null; echo "curl exit=$?"     # non-zero / 28
nc -zv -w 3 1.1.1.1 80; echo "nc exit=$?"                        # non-zero
```

SSH survives because replies match `ESTABLISHED,RELATED`.

Rollback:

```bash
sudo iptables  -P OUTPUT ACCEPT; sudo iptables  -F OUTPUT
sudo ip6tables -P OUTPUT ACCEPT; sudo ip6tables -F OUTPUT
```

The runner reads `iptables -S OUTPUT` (not `-L -v`) and reports `full` when the policy is
DROP with no unconditional ACCEPT rule. Per-port rules on the Pi (`tcp/23, 2323, 80`,
`udp/53`) are reported as `partial` and need `--allow-partial-containment`.

---

## Phase C — Obtain and verify the sample

I will not download malware. Use the route you already use for samples (institutional
corpus, MalwareBazaar, VirusTotal academic access) on the isolated machine.

**C1. Identify the file before it leaves the staging machine**

```bash
sha256sum bashlite.bin
file bashlite.bin
```

Expect `ELF 32-bit LSB executable, ARM, EABI5, statically linked` for classic Bashlite.
Anything else (`ELF 64-bit`, x86) is a different build — record what you actually have.

**C2. Can this guest run it?**

```bash
grep CONFIG_COMPAT /boot/config-$(uname -r)     # expect CONFIG_COMPAT=y
```

The run-2 acceptance test showed an x86_64 binary rejected with `Exec format error`
(exit 126) and native aarch64 running normally, so the kernel is genuine aarch64. If a
32-bit sample also returns 126, the guest has no 32-bit compat — use `qemu-arm-static`
for workflow rehearsal only, and reserve the real sample for the Pi 5.

**C3. Transfer into the guest (approval: yes)**

```bash
scp -P 2232 bashlite.bin ubuntu@127.0.0.1:~/samples/
# in the guest
chmod 700 ~/samples && chmod 755 ~/samples/bashlite.bin
sha256sum ~/samples/bashlite.bin     # must equal C1
```

Rollback: `rm -rf ~/samples/bashlite.bin`, then snapshot revert.

---

## Phase D — Install the runner

```bash
scp -P 2232 "C:/Users/Minh_Trinh/Downloads/bench/Bashlite/runner/bashlite_runner.py" \
    ubuntu@127.0.0.1:~/work/
ssh -p 2232 ubuntu@127.0.0.1 "python3 ~/work/bashlite_runner.py --help"
```

Rollback: `rm ~/work/bashlite_runner.py`.

---

## Phase E — Test ladder (never skip)

### E1 — Dry run (no sample execution, no GPIO)

```bash
python3 ~/work/bashlite_runner.py --sample ~/samples/bashlite.bin \
    --count 2 --duration 2.5 --manifest ~/work/e1_manifest.json
```

Pass criteria: banner says `DRY RUN`; two lines with `wall_s ≈ 2.5`; manifest written with
`"mode": "dry-run"`; `sample.exists` may be `false` and that is not fatal.

### E2 — Real execution path with the safe mimic (no network risk)

Compile the mimic in the guest first (it only talks to `127.0.0.1`):

```bash
scp -P 2232 "C:/Users/Minh_Trinh/Downloads/bench/Bashlite/bashlite_mimic.c" ubuntu@127.0.0.1:~/work/
ssh -p 2232 ubuntu@127.0.0.1 "gcc -O2 -o ~/work/bashlite_mimic ~/work/bashlite_mimic.c"
HASH=$(ssh -p 2232 ubuntu@127.0.0.1 "sha256sum ~/work/bashlite_mimic | cut -d' ' -f1")

python3 ~/work/bashlite_runner.py --sample ~/work/bashlite_mimic \
    --expected-hash "$HASH" --execute --software-trigger \
    --count 2 --duration 2.5 --manifest ~/work/e2_manifest.json
```

Pass criteria:

- containment gate prints `OK: outbound traffic is default-dropped`
- each trace `done in ≈2.5s` with `[killed:timeout]` (the mimic runs a fixed 2.5 s loop)
- manifest `runs[*].exit_code` is `-15` / `-9` or `0`, `trigger_window_s ≈ 2.5`
- no surviving process: `pgrep -af bashlite_mimic || echo none`

### E3 — Real sample, small (separate approval required)

```bash
python3 ~/work/bashlite_runner.py --sample ~/samples/bashlite.bin \
    --expected-hash <sha256 from C1> --execute --software-trigger \
    --count 3 --duration 2.5 --cooldown 0.5 --manifest ~/work/e3_manifest.json

pgrep -af bashlite || echo "no surviving processes"
sudo iptables -S OUTPUT; sudo iptables -L OUTPUT -n -v   # DROP counters should rise
```

Pass criteria: three bounded traces; leftover sweep reports `[leftovers:N]` if the sample
daemonizes; nothing survives; counters increased. `exit 126` means the sample is not
runnable on this guest — stop and read Phase C2.

### E4 — Shut down and reset

```bash
exit
ssh remnux "~/arm64-vm/stop-arm64.sh; \
             qemu-img snapshot -a cloudinit-done ~/arm64-vm/images/ubuntu-arm64-malware-test.qcow2"
```

---

## Manifest fields that go into the paper

`sample.sha256`, `sample.elf.machine`, `host.platform`, `containment.level`,
`params.duration_s`, `trigger.mode`, and per-run `wall_s` / `exit_code` / `killed`.
Keep the JSON next to the trace files; a run without its manifest is not reproducible.

---

## Rollback summary

| Action | Undo |
|---|---|
| Guest firewall | `iptables -P OUTPUT ACCEPT; iptables -F OUTPUT` (v4 and v6), or snapshot revert |
| Sample / mimic in guest | `rm`, then snapshot revert |
| Runner in guest | `rm ~/work/bashlite_runner.py` |
| Whole guest | `stop-arm64.sh` + `qemu-img snapshot -a cloudinit-done` |
| Windows host | nothing is executed or modified outside the repo file |

---

## Known limits

- The VM path validates timing and containment logic only. No EM trace comes from QEMU.
- The 2.5 s window and the 1.0 s pre-trace settle match `goodware_runner.py`; do not change
  one script without changing the other, or goodware/malware traces stop being comparable.
- The ACT LED / GPIO 17 path is untested until the Pi 5 run; E2 exercises everything except
  the pin toggle.
