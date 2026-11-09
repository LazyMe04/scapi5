# Bench Operations Guide — Raspberry Pi 5

**Audience:** an AI agent or technician preparing this device for electromagnetic trace capture.
**Device:** Raspberry Pi 5 Model B Rev 1.0, hostname `pi5`, Debian 13 (trixie), aarch64.
**Project:** malware detection on IoT devices using electromagnetic side-channel analysis.

Read the whole file before acting. Sections 3 and 8 contain rules that, if ignored, invalidate
an entire dataset without producing any visible error.

---

## 1. What this device is for

This Pi is a measurement target. An EM probe sits above the CPU, wired through an amplifier to
an oscilloscope on a laptop. Software runs on the Pi while the scope records the CPU's
electromagnetic emissions. A machine learning classifier later learns to separate benign
software from malware using those traces.

The Pi produces no measurements itself. It only runs workloads. Measurement is the scope's job.

## 2. Verified device state

Facts confirmed by direct inspection. Re-verify anything load-bearing before relying on it.

| Property | Value |
|---|---|
| Architecture | aarch64 |
| Kernel | 6.18.50+rpt-rpi-2712 |
| OS | Debian GNU/Linux 13 (trixie) |
| C library | 2.41 |
| Python | 3.13.5 |
| Thermal state at last check | throttled=0x0, 48.8 C |
| Network interface | eth0, NetworkManager managed |
| Wireless | wlan0 down, radio soft-blocked |
| Malware account | `victim`, home `/home/victim` |
| Malware binary | `/home/victim/gonnacry.bin`, ELF 64-bit ARM aarch64 |

The device executes 32-bit ARM binaries natively. Verified twice, most recently by compiling a
static ARM test binary with `arm-linux-gnueabihf-gcc` and confirming exit code 42. Kernel
`CONFIG_COMPAT` is present.

## 3. Hard rules

**Never overclock, underclock, or set any frequency.** A dataset collected at one clock speed
cannot be compared against traces collected at another. Check
`/boot/firmware/config.txt` for `arm_freq`, `overclock`, `force_turbo` and comment them out if
present. Preflight checks this.

**Never disable background services to reduce signal noise.** The reference methodology keeps
all default services running, because malware executes alongside genuine device activity and a
classifier trained against a stripped system does not generalise. The single exception is the
wireless radio, which is external stimulus rather than background workload.

**Never let WiFi transmit during capture.** Radio bursts are orders of magnitude larger than
the CPU's own emission and will swamp the probe. Confirm `wlan0` is down before every run.

**Never let malware run as the administrative account.** It determines its target from the
executing user's home directory. Running as `pi5` would encrypt the working environment,
including SSH keys.

**Never run a trace while the CPU is throttling.** A throttled CPU changes clock frequency
mid-capture. Traces look valid and are not. Preflight checks this.

**Never let a kernel module panic the device unattended.** A locally built module is the only
kernel-module workload permitted, and only for architecturally compatible published GPL source
whose rebuild is approved in writing (`Keysniffer/analysis_notes/KEYSNIFFER_PHASE0_APPROVAL.md`).
Before loading one: image the SD card, confirm a recovery path (HDMI + USB keyboard, or UART
console, or a re-flashable card), and complete the load/unload rehearsal in
`Keysniffer/KEYSNIFFER_PLAN.md` Phase 5. A panic ends the session and can corrupt the card.
Never use `insmod --force`; if signature enforcement rejects the module, report the blocker and
stop. `maK_it` is excluded in all forms.

**Never point a sample at the public internet.** Use a synthetic command server on the bench
link only.

## 4. Step 0 — always start here

```bash
echo '123123' | sudo -S bash ~/preflight.sh
```

Exit code 0 means ready, 1 means blocked. Fix every FAIL line before proceeding. WARN lines are
advisory; read them rather than dismissing them.

Preflight checks architecture, throttling, temperature, network mode, radio state, clock tuning,
malware binary validity, honeypot exhaustion, toolchain presence, and free space. It exists
because the most damaging failure modes are silent.

## 5. Step 1 — bench network

Two configurations exist. `netplan-eth0` uses DHCP on the institutional network. `bench-static`
is a point-to-point link for working away from that network.

```bash
# switch to bench link
echo '123123' | sudo -S nmcli con up bench-static

# revert to DHCP
nmcli con up netplan-eth0
```

Bench link addressing:

| Side | Address |
|---|---|
| Laptop | 192.168.7.1/24 |
| Pi | 192.168.7.2/24 |

Connect the two with a straight-through Ethernet cable. This arrangement is deliberate: it keeps
the wireless radio blocked, gives fixed addressing with no DHCP dependency, and provides total
network isolation so a sample cannot reach anything.

The Pi has no internet on the bench link. That is correct for malware runs. Perform any
installation before leaving.

## 6. Step 2 — regenerate the honeypot

This is the current blocker. The victim home contains zero plaintext files because a previous
execution encrypted all of them.

```bash
echo '123123' | sudo -S bash ~/regen_honeypot.sh
echo '123123' | sudo -S bash ~/preflight.sh
```

Preflight must report the honeypot as ready afterwards.

### Why randomisation is mandatory

Run the same file set every time and the electromagnetic trace is deterministic. A classifier
trained on that learns file count and total byte volume rather than encryption behaviour. It
will score well in testing and fail on any real sample.

The reference methodology requires a randomly initialised environment per execution so that
recorded traces are not biased towards a fixed workload.

### Why total bytes must stay fixed

Cryptographic runtime scales with bytes processed. If each run encrypts a different volume, the
trace duration drifts and traces become incomparable.

Therefore: hold total plaintext bytes constant across runs, and randomise everything else —
file count, extension distribution, and individual file sizes. The workload stays comparable
while the file layout stays unpredictable.

The script also records the achieved byte count so run-to-run variance can be verified. If that
count drifts between runs, the traces are not comparable and the reason must be found before
collecting more.

## 7. Step 3 — run the workloads

Both classes must be triggered identically. The measured window is the delta between a trigger
edge and the end of the capture, not wall-clock time.

### Benign

`goodware_runner.py` exists with profiles including `idle`, `crypto`, `compress`, `math` and
`network`. It drives GPIO 17 as the capture trigger.

It writes an append-only JSONL manifest, and that manifest is not optional: without it a
benign trace has no record of which workload produced it or when, so it cannot be joined to
its capture and cannot enter a dataset. One manifest per cell; `--task all` writes one per
task.

```bash
python3 goodware_runner.py --task crypto --count 3000 --duration 2.5 \
    --capture-duration 2.5 --run-dir runs/crypto-01
```

`--duration` must be at least the scope's capture window, or the capture extends past the
trace's recorded span and cannot be joined. The runner warns when it is shorter. The
`vcgencmd get_throttled` gate runs before and after every session; a non-zero or unreadable
answer aborts. `--skip-throttle-check` exists only for a dry run on a PC and is recorded in
the manifest header.

### Malicious

`malware_runner.py` is not yet written. It must match the benign runner on:

- trigger pin and edge
- pre-trigger and post-trigger delay
- capture window duration
- process count and thread topology

It must also force observable activity rather than permitting an idle process. A bot that is
merely sleeping produces a trace indistinguishable from benign idle activity, which contributes
nothing to the dataset.

Run Gonnacry as the victim account against the freshly regenerated home:

```bash
echo '123123' | sudo -S -u victim bash -c 'cd /tmp && /home/victim/gonnacry.bin'
```

## 8. Step 4 — capture

**Blocked. Do not attempt until the oscilloscope model is known.**

Different PicoScope models expose different Python APIs, bandwidths, and maximum sample rates.
Capture code written against the wrong model will fail or, worse, silently sample below the
required rate.

Reference parameters from the published methodology, for when the model is confirmed:

| Parameter | Value |
|---|---|
| Sample rate | 2 MHz |
| Capture window | 2.5 seconds |
| Points per trace | 5,000,000 |
| Raw size per trace | 10 MB int16 (40 MB as float64 .npy) |
| Probe placement | 45 degrees above the processor |
| STFT window | 8192 |
| STFT overlap | 4096 |
| Feature selection | normalised inter-class variance, 20 bands |

The paper (section 6.2.1) states "500 000 points to get a 2.5s recording with a
sampling rate of 2MHz", which is arithmetically inconsistent: 500,000 points at
2 MHz is 0.25 s. The 2.5 s window is the quantity the rest of this document and
every runner workload are built around, so it is treated as authoritative and
the point count is derived from it. The paper's "about 8 MB per trace" matches
neither figure and is not used. See `pico-em-capture/README.md` for the full
reconciliation.

The 2.5 second window was selected empirically, partly because idle periods in malware sleep
cycles would otherwise yield empty windows. If a workload finishes faster than the window, the
window must be reduced or the workload enlarged, and the choice recorded.

Validate the trigger against real instrumentation with a single short capture before beginning
any large acquisition. A misaligned trigger produces a dataset that cannot be repaired after
the fact.

## 9. Gonnacry build provenance

Source: https://github.com/tarcisio-marinho/GonnaCry, GPL-2.0, cloned to `~/GonnaCry`.

The upstream code predates current Python 3 and PyCryptodome. Four classes of defect were
corrected, all behavioural no-ops that leave the encryption scheme and its security properties
unchanged:

1. `generate_keys.py` used `Crypto.Random.OSRNG.posix.DevURandomRNG()`, an internal class
   removed in PyCryptodome 3.20. Migrated to the public `get_random_bytes()`.
2. `symmetric.py` padded to 32 bytes. AES operates on 16-byte blocks. Corrected to
   `AES.block_size`.
3. Python 3 bytes and string strictness required coercion at four call sites in `main.py` and
   `symmetric.py`.
4. PyInstaller did not statically detect the PyCryptodome import. Fixed with an explicit
   hidden-import directive.

Build command:

```bash
cd ~/GonnaCry/src
export PATH=$HOME/.local/bin:$PATH
pyinstaller -F --clean --hidden-import=Crypto GonnaCry/main.py -n gonnacry
```

Any dataset produced from this binary must state the source revision and the patch set. Results
are not reproducible otherwise.

## 10. Known traps

**Containment self-interference.** An outbound firewall rule dropping all UDP port 53 was
installed during initial provisioning to contain a different malware family. It broke this
device's own package management, which depends on hostname resolution. The rule was removed.
The lesson generalises: a containment rule must be validated against the administrative
workflows that share the same host, because a rule intended to block one threat can disable the
capability needed to respond to the next.

Do not reinstate a DNS drop rule for Gonnacry. It performs no network operations. The rule is
required before any Mirai-family execution.

**Kernel configuration path.** The configuration file is at `/boot/config-$(uname -r)` on this
Debian 13 installation, not `/boot/firmware/config-$(uname -r)`. Earlier documentation specified
the wrong path. Both should be checked.

**Desktop manipulation failures are expected.** Gonnacry attempts to change the desktop
wallpaper and reports failures for `gsettings`, `xfconf-query` and the session message bus on a
headless installation. These are non-fatal and do not affect encryption.

**Decryptor not verified.** The recovery component requires the operator-side key escrow server
and has not been exercised. Recovery capability affects threat model realism, not the
electromagnetic signature of the encryption workload. Recorded as an open item.

**Administrative password.** The device password is a short numeric sequence and has been used
repeatedly during setup. Change it before the device is used on any network it is not
explicitly isolated from.

## 11. Firewall state

Current outbound rules, retained from provisioning:

| Port | Protocol | Purpose |
|---|---|---|
| 23 | TCP | Telnet scanner containment |
| 2323 | TCP | Alternative Telnet scanner containment |
| 80 | TCP | HTTP containment |

These were written for Mirai-family samples and are irrelevant to Gonnacry. Retaining them does
no harm.

`netfilter-persistent` stores the ruleset. A ruleset change made in the live table will not
survive a reboot until persistence is refreshed with:

```bash
echo '123123' | sudo -S netfilter-persistent save
```

## 12. Completion criteria

A capture session is properly finished when all of the following hold:

- preflight exits 0 with no FAIL lines
- the honeypot byte count matches the recorded target within a stated tolerance
- benign and malicious traces were captured with identical trigger configuration
- the oscilloscope sample rate and window match the recorded parameters
- throttling was zero at both the start and the end of the session
- the environment fingerprint has been refreshed and copied off the device
- the number of traces collected per binary is recorded

If any of these cannot be asserted, the session is incomplete and the gap must be documented
before the data is used.