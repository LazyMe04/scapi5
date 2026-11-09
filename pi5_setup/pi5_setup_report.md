# Raspberry Pi 5 Setup & Compatibility Verification Report

**Date of Execution:** 2026-09-27  
**Target Device:** Raspberry Pi 5 Model B Rev 1.0 (`pi5@192.168.102.36`)  
**Operator:** AI Agent  
**Reference Document:** `pi5_setup_instructions.md`  
**Status:** **SUCCESS / GATE PASSED**

---

## 1. Section 4 Gate Result — 32-bit ARM Compatibility

### Status: PASS (Native Execution Supported)

* **Kernel Configuration Check (`/boot/config-6.18.34+rpt-rpi-2712`):**
  ```text
  CONFIG_COMPAT=y
  CONFIG_COMPAT_VDSO=y
  # CONFIG_COMPAT_ALIGNMENT_FIXUPS is not set
  CONFIG_COMPAT_OLD_SIGACTION=y
  CONFIG_COMPAT_32BIT_TIME=y
  CONFIG_COMPAT_BINFMT_ELF=y
  # CONFIG_COMPAT_BRK is not set
  CONFIG_COMPAT_NETLINK_MESSAGES=y
  ```

* **Empirical Binary Test:**
  * Test C code compiled: `int main(){return 42;}`
  * Compiler: `arm-linux-gnueabihf-gcc -static /tmp/t.c -o /tmp/t32`
  * `file /tmp/t32` output:
    ```text
    /tmp/t32: ELF 32-bit LSB executable, ARM, EABI5 version 1 (GNU/Linux), statically linked, BuildID[sha1]=3c8a341ad5c393bf88a6456e4a929ca8afdac81c, for GNU/Linux 3.2.0, not stripped
    ```
  * Execution:
    ```bash
    /tmp/t32
    echo "exit=$?"
    ```
  * Output:
    ```text
    exit=42
    ```

### Architectural Conclusion & Decision
The aarch64 kernel has `CONFIG_COMPAT=y` and `CONFIG_COMPAT_BINFMT_ELF=y` enabled. 32-bit ARM userland ELF binaries execute directly with syscall translation.
* **Fall-back in Section 4.5 is NOT needed.**
* Real-world 32-bit ARM malware samples (e.g. Mirai, Bashlite, Gonnacry) can be executed natively without emulation or recompilation.
* Kernel modules (`keysniffer`, `maK_it`) remain excluded as specified in Section 0.

> **Amendment 2026-11-09.** The exclusion is narrowed. `maK_it` stays excluded in all forms.
> `keysniffer` (`kisni`) may be used **only** as an out-of-tree build of its published GPL-2.0
> source for exactly `uname -r`, under the written approval recorded in
> `Keysniffer/analysis_notes/KEYSNIFFER_PHASE0_APPROVAL.md`. The prebuilt foreign-arch `.ko`
> still cannot be loaded and must not be forced. A trace from the rebuilt module describes this
> kernel's code, not the paper's 4.19 code, and must be reported as a same-source
> re-instantiation rather than a replication. See `pi5_setup_instructions.md` §4.5.

---

## 2. Section 3 Verification Table

| Check | Command | Expected | Actual Measured Value | Status |
|---|---|---|---|---|
| Architecture | `uname -m` | `aarch64` | `aarch64` | PASS |
| Kernel Version | `uname -a` | Linux 6.x | `Linux pi5 6.18.34+rpt-rpi-2712 #1 SMP PREEMPT Debian 1:6.18.34-1+rpt1 (2026-06-09) aarch64 GNU/Linux` | PASS |
| Model | `/proc/device-tree/model` | Raspberry Pi 5 Model B | `Raspberry Pi 5 Model B Rev 1.0` | PASS |
| OS Release | `cat /etc/os-release` | Debian bookworm / trixie | `Debian GNU/Linux 13 (trixie)` | PASS |
| Libc Version | `dpkg-query -W libc6` | `2.36` or `2.41` | `libc6:arm64 2.41-12+rpt1+deb13u3` | PASS |
| Throttling | `vcgencmd get_throttled` | `throttled=0x0` | `throttled=0x0` | **PASS (Must be 0x0)** |
| Temperature | `vcgencmd measure_temp` | `< 70°C` at idle | `38.4°C` - `40.6°C` | PASS |
| 64-bit Boot Flag | `grep arm_64bit /boot/firmware/config.txt` | `arm_64bit=1` | `arm_64bit=1` | PASS |

---

## 3. Section 5 Base Tooling & Python Environment

1. **System Packages Installed:**
   * Build & analysis tools: `build-essential`, `git`, `cmake`, `make`, `pkg-config`, `file`, `binutils`, `gdb`, `strace`, `ltrace`.
   * Malware analysis & network utilities: `radare2`, `binwalk`, `upx-ucl`, `yara`, `tcpdump`, `iproute2`, `net-tools`.
   * Cross & emulation tools: `gcc-arm-linux-gnueabihf`, `qemu-user-static`.
2. **Python Environment:**
   * Virtualenv path: `/home/pi5/work/emenv`
   * Python version: `3.13.5`
   * Core data science libraries: `numpy 2.5.3`, `scipy 1.18.1`, `matplotlib 3.11.2`, `scikit-learn 1.9.1`.
   * GPIO library: `RPi.GPIO 0.7.1` (built and verified as fallback for `lgpio`).

---

## 4. Section 6 EM Measurement Preparation

* **Clock & Frequency Tuning:**
  `grep -E "arm_freq|overclock|force_turbo" /boot/firmware/config.txt` returned **no entries**. Default factory clocking preserved.
* **GPIO Pin 17:**
  `gpioinfo` confirms line 17 (`GPIO17`) is free and configured as standard input, available for oscilloscope triggering.
* **RF Kill Status:**
  * Bluetooth: `hci0` is **Soft blocked: yes** (`sudo rfkill block bluetooth`).
  * WiFi: `phy0` is currently unblocked due to active management session over `wlan0` (see Section 6 Deviations below).

---

## 5. Section 7 Network Isolation & Firewall Verification

Outbound containment rules configured via `iptables` and made persistent across reboots via `netfilter-persistent`:

```text
sudo iptables -A OUTPUT -p tcp --dport 23 -j DROP
sudo iptables -A OUTPUT -p tcp --dport 2323 -j DROP
sudo iptables -A OUTPUT -p tcp --dport 80 -j DROP
sudo iptables -A OUTPUT -p udp --dport 53 -j DROP
```

### Verification with Non-Zero Drop Counters (`iptables -L OUTPUT -n -v`):
```text
Chain OUTPUT (policy ACCEPT 48 packets, 9242 bytes)
 pkts bytes target     prot opt in     out     source               destination         
    1    60 DROP       tcp  --  *      *       0.0.0.0/0            0.0.0.0/0            tcp dpt:23
    1    60 DROP       tcp  --  *      *       0.0.0.0/0            0.0.0.0/0            tcp dpt:2323
    1    60 DROP       tcp  --  *      *       0.0.0.0/0            0.0.0.0/0            tcp dpt:80
    1    29 DROP       udp  --  *      *       0.0.0.0/0            0.0.0.0/0            udp dpt:53
```
* Outbound malicious scanning (Telnet/23, alternative/2323), HTTP exfiltration/C2, and DNS lookups are confirmed actively dropped by the kernel netfilter.

---

## 6. Section 8 Environment Fingerprint Files

The environment fingerprint has been recorded on the target at `~/work/environment/` and mirrored to the host machine at `pi5_environment/`:

| File | Content Summary |
|---|---|
| [`kernel.txt`](pi5_environment/kernel.txt) | `Linux pi5 6.18.34+rpt-rpi-2712 #1 SMP PREEMPT Debian 1:6.18.34-1+rpt1 (2026-06-09) aarch64 GNU/Linux` |
| [`libc.txt`](pi5_environment/libc.txt) | `libc6:arm64 2.41-12+rpt1+deb13u3` |
| [`model.txt`](pi5_environment/model.txt) | `Raspberry Pi 5 Model B Rev 1.0` |
| [`os-release.txt`](pi5_environment/os-release.txt) | Debian GNU/Linux 13 (trixie) |
| [`throttle.txt`](pi5_environment/throttle.txt) | `throttled=0x0` |
| [`temperature.txt`](pi5_environment/temperature.txt) | `temp=38.4'C` |
| [`compat.txt`](pi5_environment/compat.txt) | `CONFIG_COMPAT=y` kernel symbols |
| [`services.txt`](pi5_environment/services.txt) | Exact snapshot of 15 running systemd services |
| [`devicetree.txt`](pi5_environment/devicetree.txt) | Full device tree node listing under `/sys/firmware/devicetree/base/` |

---

## 7. Documented Deviations & Critical Operator Notes

1. **Active Interface (WiFi vs. Ethernet):**
   * **Deviation:** Section 6.1 calls for `sudo rfkill block wifi`. Currently, the Pi 5 is accessed via `wlan0` (`192.168.102.36`), while `eth0` is unlinked (`DOWN`). Blocking WiFi at this step would terminate the remote session.
   * **Resolution Required:** Before running physical EM trace captures, the human operator must connect the physical Ethernet cable to `eth0`, verify SSH access via Ethernet, and execute `sudo rfkill block wifi` to prevent RF spikes from contaminating EM captures.
2. **Kernel Config Location:**
   * On Debian 13 (Trixie), the kernel config is placed at `/boot/config-$(uname -r)` rather than `/boot/firmware/config-$(uname -r)`. Both locations were accounted for.
3. **Python GPIO Package:**
   * Python 3.13 on Trixie lacked pre-compiled wheels for `lgpio` (missing build dependency `swig`), so `RPi.GPIO` was compiled and installed in accordance with Section 5 fallback instructions.

---

## 8. Readiness for Next Phase

The Raspberry Pi 5 target is fully verified, secured with netfilter containment, outfitted with the required analysis toolchain, and confirmed capable of natively running 32-bit ARM malware binaries.
