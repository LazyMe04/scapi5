# Raspberry Pi 5 — Setup and Compatibility Verification

**Purpose:** Prepare a Raspberry Pi 5 as the measurement target for EM side-channel malware
classification research. This document is executable by an AI agent or a human working on a
machine that is not where the project is being developed.

**Read Section 0 and Section 4 before running anything.** Section 4 is a gate. Do not continue
past it until the result is known, because the result determines which malware can be used and
therefore what the rest of the project looks like.

---

## 0. Context the operator needs

This is graduate research on detecting IoT malware using electromagnetic side-channel analysis.
An EM probe, amplifier and oscilloscope measure the CPU's electromagnetic emissions while
software executes. A machine learning classifier later learns to distinguish benign software
from malware using those EM traces.

Facts that constrain the setup:

- EM emissions come only from physical silicon. Virtual machines and emulators cannot produce
  them. This Pi 5 is the real measurement target. Anything done in a VM is preparation only.
- The reference paper (`OG research.pdf`, Pham and Marion, ACSAC 2021) used a **Raspberry Pi 2B**
  with a **32-bit** OS and **32-bit ARM** malware. This project uses a **Pi 5**, which is 64-bit.
  That difference is the reason for Section 4.
- Two of the paper's malware classes, `keysniffer` and `maK_it`, are **Linux kernel modules**.
  Kernel modules must match kernel version, kernel config and CPU architecture exactly, so the
  paper's prebuilt `.ko` files will not load on a Pi 5 under any circumstance. Do not attempt to
  load them. `keysniffer` may instead be rebuilt from its published GPL-2.0 source for this
  kernel — see §4.5 item 2 and `Keysniffer/analysis_notes/KEYSNIFFER_PHASE0_APPROVAL.md`.
- The paper deliberately kept default background services, no overclocking, and no clock tuning.
  This setup follows that. Section 6 has one deliberate exception, which is explained there.

---

## 1. Prerequisites

### Hardware

| Item | Requirement | Note |
|---|---|---|
| Raspberry Pi 5 | 4 GB or 8 GB | 2 GB works but is tight for malware analysis tooling |
| Power supply | Official 27 W USB-C PD | Third-party 15 W supplies cause throttling |
| microSD card | 64 GB minimum, A2 rated | See Section 1.3 |
| Storage for the OS | Any | Can be flashed from any host OS |
| Host machine | Windows, macOS, or Linux | Raspberry Pi Imager runs on all three |
| Network | Wired Ethernet strongly preferred | WiFi works but is noisier for EM measurement |

### 1.1 Why power supply matters here

A Pi 5 drawing 5 A on an undersupplied USB port will clock-throttle. Throttling changes the CPU
clock mid-trace, which destroys the consistency the dataset depends on. Verify with
`vcgencmd get_throttled` in Section 3. Expected value is `0x0`.

### 1.2 Cooling

A Pi 5 runs hot. Thermal throttling has the same effect as power throttling. Fit the official
active cooler, or a good passive heatsink with airflow. Check temperature in Section 3.

### 1.3 Storage media

SD cards have widely varying latency, and wear makes latency worse over time. Inconsistent I/O
timing adds jitter to every trace.

Preferred order:

1. NVMe SSD over USB 3.1 (fastest, most consistent, needs HAT or PCIe adapter)
2. High-endurance A2-rated microSD
3. Any microSD

If a USB SSD is used, the OS is still flashed to the microSD; the SSD is attached later and
`/var` can be moved to it if needed. This is optional and not required to start.

---

## 2. Flash Raspberry Pi OS Lite (64-bit)

### 2.1 Get the imaging tool

Download Raspberry Pi Imager from the official site:

    https://www.raspberrypi.com/software/

Install it on the host machine. Available for Windows, macOS, and Linux.

### 2.2 Select the image

In Raspberry Pi Imager, three selections must be made. Getting the third one wrong is the most
common failure, because Imager lists a Desktop image first.

1. **Raspberry Pi Device** — choose **Raspberry Pi 5**
2. **Operating System** — click the **"Raspberry Pi OS (other)"** entry at the bottom of the list
3. Under that, choose **"Raspberry Pi OS Lite (64-bit)"**

Two warnings:

- Choose **Lite**, not Desktop. This Pi is a headless measurement target. A desktop environment
  adds background CPU and GPU activity that shows up directly in the EM trace as noise.
- Choose **64-bit**, not 32-bit. Raspberry Pi OS 32-bit is not published for the Pi 5. The
  aarch64 image is the only supported one.

### 2.3 Configure before writing

**This must be done before clicking Write.** After writing, the host OS mounts the boot partition
in a way that makes these settings awkward to change.

Press **Ctrl+Shift+X** (Windows and Linux) or **Cmd+Shift+X** (macOS) in Raspberry Pi Imager to
open the OS customization dialog.

Under the **General** tab:

| Field | Value | Why |
|---|---|---|
| Hostname | `pi5-em-target` | Stable name for scripts |
| Username | `emlab` | Non-default, so brute-force login guessing does not work |
| Password | a strong unique password | Record it in the project password manager |
| Wireless LAN SSID | leave blank if using Ethernet | WiFi is optional |
| Country | set correctly | Sets locale, timezone, keyboard |

Under the **Services** tab:

| Field | Value | Why |
|---|---|---|
| Enable SSH | **on** | Only way to reach a Lite install without a keyboard |
| Use password authentication | **on** | Key-only auth complicates recovery |

### 2.4 Write the image

Insert the microSD card into the host machine. Select it as the storage device in Imager.
Click **Write** and confirm the erase warning.

When it finishes, safely eject the card.

---

## 3. First boot and baseline verification

### 3.1 Connect and boot

1. Insert the microSD card into the Pi 5.
2. Connect Ethernet. Connect the power supply.
3. Wait for the ACT LED to stop blinking in an irregular pattern. A solid green or dim green
   LED means boot finished. Allow up to two minutes on first boot.
4. Find the IP address. Either run `hostname -I` on a local console, or check the DHCP server
   on the router, or scan the network from the host machine:

       ssh emlab@pi5-em-target.local

The `.local` hostname works with mDNS on most networks without extra setup.

### 3.2 Verify identity and architecture

Run all of these and record the output. These values are part of the experimental record and
must be captured before any data is collected.

    uname -m
    uname -a
    tr -d '\000' < /proc/device-tree/model; echo
    cat /etc/os-release
    dpkg-query -W libc6
    vcgencmd get_throttled
    vcgencmd measure_temp

Expected:

| Command | Expected value |
|---|---|
| `uname -m` | `aarch64` |
| `/proc/device-tree/model` | `Raspberry Pi 5 Model B` |
| `os-release` | Debian GNU/Linux, codename `bookworm` or `trixie` |
| `libc6` | `2.36` on bookworm, `2.41` on trixie |
| `get_throttled` | `throttled=0x0` — **must be zero** |
| `measure_temp` | below 70 degrees C at idle |

**If `get_throttled` reports anything other than `0x0`, stop and fix the power or cooling
before continuing.** A throttling CPU produces inconsistent traces and the resulting dataset
will be unusable. `0x5000` means under-voltage, `0x40000` means throttling has occurred at some
point since boot.

### 3.3 Confirm the 64-bit flag

    sudo nano /boot/firmware/config.txt

Confirm the line `arm_64bit=1` is present and not commented out. On a Pi 5 this is the default
and it should already be there. Do not change it.

Note the path. On current Raspberry Pi OS the boot partition is mounted at `/boot/firmware`, not
`/boot`. Some older documentation refers to `/boot/config.txt`, which will not exist here.

---

## 4. GATE — 32-bit compatibility test

**Do not skip this section.** The result determines the entire malware strategy for the project.

### 4.1 Why this test exists

The reference paper used 32-bit ARM malware on a 32-bit ARM device. Real-world IoT malware
samples, including Mirai, are overwhelmingly 32-bit ARM. On a 64-bit CPU, 32-bit binaries run
only if the kernel was built with `CONFIG_COMPAT`, which performs the syscall translation
between the two worlds. Without it, 32-bit code cannot execute at all.

This is not a question of CPU capability. The Pi 5 CPU is powerful enough. The question is
purely whether the kernel was configured to allow it.

### 4.2 Check the kernel configuration

    zgrep CONFIG_COMPAT /boot/firmware/config-$(uname -r)

Record the output. Expected values are `CONFIG_COMPAT=y` or the line being absent.

### 4.3 Empirical test — this is authoritative

Kernel configuration files lie. Run an actual 32-bit binary.

Install the cross compiler and the user-mode emulator:

    sudo apt update
    sudo apt install -y gcc-arm-linux-gnueabihf qemu-user-static

Build a static 32-bit ARM test program:

    echo 'int main(){return 42;}' > /tmp/t.c
    arm-linux-gnueabihf-gcc -static /tmp/t.c -o /tmp/t32
    file /tmp/t32

The `file` output must report an ELF 32-bit LSB ARM executable. If it does not, the cross
compiler is not working and the rest of this section is invalid.

Now run it:

    /tmp/t32
    echo "exit=$?"

### 4.4 Interpreting the result

| Result | Meaning | Action |
|---|---|---|
| `exit=42` and `file` says ELF 32-bit LSB ARM | 32-bit malware runs on this Pi 5 | Proceed. The paper is fully replicable. Use existing 32-bit ARM Mirai samples. |
| `Exec format error` | The kernel refuses 32-bit binaries | Proceed with the fallback below. |

Additional diagnostic if it fails:

    /lib64/ld-linux-aarch64.so.1 /tmp/t32

This error message names the missing interpreter and confirms the rejection is architectural
rather than a missing library.

### 4.5 Fallback plan if 32-bit is rejected

This is a workable outcome, not a failure. Do not attempt to change the kernel configuration.

1. Restrict the malware class list to architecture-independent and naturally 64-bit samples.
   **Do not cross-compile.** Rebuilding replaces the author's toolchain, optimisation level, and
   hardcoded constants; the result is no longer in-the-wild malware, and its SHA-256 no longer
   matches any recorded manifest. Select a **naturally aarch64** sample instead. This is settled
   in `Bashlite/docs/BASHLITE_32BIT_PLAN.md` §1 and in the lab invariants.
   *Scope note:* this rule governs **in-the-wild userland binaries**, whose identity is a hash of
   one author-built artifact. It does not govern **published open-source modules**, whose identity
   is a pinned source revision — item 2 below is the only such case, and it carries its own
   provenance and deviation requirements.
2. **Drop `maK_it`.** It is a kernel module whose source is not published by the same route,
   and it adds hidden-module, packet-sniffer and reverse-shell components. Do not attempt it.
   `keysniffer` is **not** dropped: it is open source (GPL-2.0), its published source still builds
   against current mainline interfaces, and `Keysniffer/KEYSNIFFER_PLAN.md` §0 records a verified
   written approval to rebuild it for this kernel. The resulting trace is a same-source
   re-instantiation on new hardware, not a replication of the paper's sample, and must be
   reported that way.
3. Reduce the class count from six to five, with the rootkit class represented by `keysniffer`
   alone.
4. Record the change in the thesis as a documented deviation, with the reason: the paper used a
   32-bit device and a 4.19 kernel, this project uses a 64-bit device, and the prebuilt
   foreign-arch module cannot be loaded. The rebuilt module describes this kernel's code, not
   the paper's.

A five-class problem on hardware that actually exists is worth more than a six-class problem
that does not.

### 4.6 Note on cross-compiling 32-bit samples

If the test passes, 32-bit ARM samples are usable directly and no cross-compilation is needed
anywhere in this project. Rebuilding a sample for aarch64 is **not** an option: it replaces the
author's toolchain, optimisation level, and hardcoded constants, and the result stops being
in-the-wild malware. `Bashlite/docs/BASHLITE_32BIT_PLAN.md` §1 settles this; a rebuild also
invalidates the SHA-256 recorded in every manifest.

This applies to in-the-wild userland binaries. It does not apply to published open-source kernel
modules, whose identity is a pinned source revision rather than one author-built artifact; the
only approved case is `keysniffer` (§4.5 item 2).

---

## 5. Base tooling

Install the analysis toolchain:

    sudo apt install -y build-essential git cmake make pkg-config file binutils
    sudo apt install -y python3 python3-pip python3-venv
    sudo apt install -y radare2 binwalk upx-ucl yara tcpdump iproute2 net-tools
    sudo apt install -y gdb strace ltrace

Set up Python environments for the data collection work:

    mkdir -p ~/work && cd ~/work
    python3 -m venv emenv
    source emenv/bin/activate
    pip install numpy scipy matplotlib scikit-learn
    pip install lgpio

If `lgpio` fails to build, fall back to `RPi.GPIO` or use direct `/sys/class/gpio` writes in the
trigger code. The trigger mechanism does not require any one library.

### 5.1 EM measurement libraries

When an oscilloscope is available, the relevant Python packages will be needed. These are
listed here so they are not a surprise later:

- **PicoScope** — `picoscope` or the vendor's own `picosdk` package
- **Rigol** — `pyvisa` plus a NI-VISA backend
- **Saleae** — `saleae` or `pyserial` depending on the unit

Do not install these until the oscilloscope model is known.

---

## 6. EM measurement preparation

### 6.1 Radio shutdown — the one deliberate deviation

The paper kept all default services including networking. This section disables the wireless
radios, which the paper did not.

Rationale: WiFi and Bluetooth transmit in bursts with large, stochastic power swings. On a
bench with a probe near the CPU, those bursts are orders of magnitude larger than the CPU's own
EM emission and will swamp the signal. A WiFi association event can invalidate a whole trace.

Wired Ethernet does not have this problem. Its power draw is far more stable and its PHY
activity is continuous rather than bursty.

    sudo rfkill block wifi
    sudo rfkill block bluetooth

Confirm:

    rfkill list

Both `wlan` and `bluetooth` should show `Soft blocked: yes`.

This is a deviation from the paper's setup and should be documented as one, with the reason.

### 6.2 Clock and CPU settings — do not change

Leave these alone. The paper applied no overclocking and no clock tuning, and a dataset
collected at one clock speed cannot be compared against traces collected at another.

Do not set `arm_freq`, `overclock`, or any `force_turbo` setting in `config.txt`. Verify that
none are present:

    grep -E "arm_freq|overclock|force_turbo" /boot/firmware/config.txt

Expected: no output. Any match is a line that must be commented out.

### 6.3 GPIO trigger

The data collection scripts use a GPIO pin to trigger the oscilloscope capture, so the pin
transition is synchronized with the start of the measured workload. `goodware_runner.py` uses
GPIO 17 or the ACT LED.

Confirm the pin is free and exportable:

    ls /sys/class/gpio/
    gpioinfo

Do not enable the SPI or I2C interfaces on GPIO 17 without checking the pin assignment table
in `config.txt` first.

### 6.4 Physical probe placement

This has no software component but determines whether any of the work above matters.

| Item | Reference paper value |
|---|---|
| Scope | Picoscope 6407, 1 GHz bandwidth |
| Probe | Langer RF-R 0.3-3 H-field probe |
| Amplifier | Langer PA-303, +30 dB |
| Probe placement | 45 degrees above the processor |
| Sample rate | 2 MHz |
| Capture window | 2.5 seconds, 500,000 points, roughly 8 MB per trace |

Reproducing the probe angle and distance matters more than the equipment model. Write down the
physical position once established, and do not move the Pi afterwards without re-establishing
it. Movement changes the coupling and invalidates the dataset.

---

## 7. Network isolation

**Complete this section before any malware runs on this device. Not after.**

Malware in the Mirai family scan the internet on ports 23 and 2323, generate random target
addresses, and attempt credential brute-force. On a normal network this reaches devices the
operator does not own. That is a legal problem, not just a technical one.

The reference paper handled this by running several virtual machines on the same local network
to absorb the attack traffic.

### 7.1 Preferred — isolated VLAN

If the network infrastructure allows, place the Pi on a VLAN with no route to the internet. A
separate VLAN is the correct solution because it also stops DNS resolution, which is needed to
direct the botnet at a command server.

### 7.2 Fallback — local firewall rules

If a VLAN is not available, block the outbound traffic that causes harm while keeping the
device usable:

    sudo apt install -y iptables
    sudo iptables -A OUTPUT -p tcp --dport 23 -j DROP
    sudo iptables -A OUTPUT -p tcp --dport 2323 -j DROP
    sudo iptables -A OUTPUT -p tcp --dport 80 -j DROP
    sudo iptables -A OUTPUT -p udp --dport 53 -j DROP

Verify:

    sudo iptables -L OUTPUT -n -v

Confirm each rule shows a non-zero packet count after a test run, which proves the rules are
actually being hit and not silently bypassed.

Make the rules survive a reboot:

    sudo apt install -y iptables-persistent
    sudo netfilter-persistent save

### 7.3 Command and control server

The paper used a synthetic spoofed command server that issues random commands to the bot:
network scan, TCP and UDP flood, hibernation, self-terminate. This makes runs repeatable.

A local lab command server on the host-only network is required. Pointing the botnet at real
command servers is illegal. Never connect a sample to the public internet.

### 7.4 Before the first malware run

Confirm all of the following:

- [ ] Section 4 result known and recorded
- [ ] Section 7.1 or 7.2 in place and verified with non-zero packet counts
- [ ] Section 6.1 radios confirmed blocked
- [ ] A host-only or isolated network segment exists for the command server
- [ ] A snapshot or SD card image exists, so the device can be restored to a known clean state
- [ ] The operator understands that running malware will modify the filesystem

Take the restore point now, before anything else runs:

    sudo apt install -nfs-common
    # or, on the host machine, image the SD card with balenaEtcher or similar

---

## 8. Record the environment fingerprint

Every value below must be captured and stored. A dataset without its environment fingerprint
cannot be reproduced or defended in review.

Create the record:

    mkdir -p ~/work/environment
    cd ~/work/environment
    uname -a > kernel.txt
    dpkg-query -W libc6 > libc.txt
    cat /etc/os-release > os-release.txt
    vcgencmd get_throttled > throttle.txt
    vcgencmd measure_temp > temperature.txt
    systemctl list-units --type=service --state=running > services.txt
    tr -d '\000' < /proc/device-tree/model > model.txt
    ls -l /sys/firmware/devicetree/base/ > devicetree.txt
    zgrep CONFIG_COMPAT /boot/firmware/config-$(uname -r) > compat.txt

Copy the whole directory to the host machine so it survives a device failure.

The `services.txt` file is particularly important. The paper argued that keeping all default
background services makes the measurement environment realistic. A reviewer will want to see
exactly which services were running.

---

## 9. What to report back

The operator needs the following, in this order of priority:

1. **Section 4 result.** Whether 32-bit ARM binaries execute, and the exact output of the test.
   This is the single most important result. If it failed, the fallback plan in Section 4.5 is
   in force and the malware class list is reduced to four.
2. **Section 3 verification table**, filled in with real values. Flag anything that is not as
   expected, especially a non-zero `get_throttled` value.
3. **Section 8 fingerprint files**, transferred to the host machine.
4. **Section 7 isolation status**, with the `iptables -L OUTPUT -n -v` output showing non-zero
   packet counts.
5. **Any deviation from this document**, with the reason.

Do not report success on a section that was skipped. A section that was skipped and not
reported will be assumed to have failed later.

---

## Appendix A — Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `vcgencmd get_throttled` shows non-zero | Undersized power supply or overheating | Official 27 W supply, fit active cooler, recheck |
| SSH connection refused | `enableSSH.txt` not created, or boot incomplete | Wait two full minutes, recheck, re-flash if needed |
| `.local` hostname does not resolve | mDNS not available on the network | Use the DHCP-assigned IP address instead |
| `arm-linux-gnueabihf-gcc: command not found` | Package not installed | `sudo apt install gcc-arm-linux-gnueabihf` |
| 32-bit binary gives `Exec format error` | Kernel lacks `CONFIG_COMPAT` | Expected on Pi 5. Use the Section 4.5 fallback. Do not modify the kernel. |
| `file /tmp/t32` reports x86-64 | Cross compiler silently not installed | Reinstall the package, verify with `arm-linux-gnueabihf-gcc --version` |
| Thermal warnings in `dmesg` | Cooling insufficient | Fit active cooler before collecting any data |

## Appendix B — What not to do

- Do not overclock, underclock, or set any frequency in `config.txt`. The dataset is only valid
  at the speed it was collected at.
- Do not disable background services to reduce EM noise. The paper's argument for keeping them
  is sound: malware runs alongside real services, and a classifier trained against a stripped
  system will not generalise. Section 6.1 is the only exception, and it exists because radio
  transmission is not background service load, it is unbounded external stimulus.
- Do not attempt to load `maK_it`. It remains excluded. `keysniffer` may be loaded only as a
  locally built module for exactly `uname -r`, after Phase 0 approval is recorded in
  `Keysniffer/analysis_notes/KEYSNIFFER_PHASE0_APPROVAL.md`, and never with `insmod --force`.
- Do not run any malware before Section 7 is verified.
- Do not move or re-cable the Pi after measurement begins without restarting the capture log.
- Do not collect traces before the throttle check in Section 3.2 passes. A throttling CPU
  produces a dataset that looks valid and is not.
