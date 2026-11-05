# Weekly Progress Report — EM Side-Channel IoT Malware Detection

**Project:** Malware Detection on IoT Devices Using Electromagnetic Side-Channel Analysis
**Reporting period:** 19 – 27 September 2026
**Prepared:** 27 September 2026

---

## 1. Executive Summary

This week the project moved from laboratory planning to a verified measurement platform.

Three work packages were completed. First, the malware analysis laboratory was designed,
deployed, and automated through an MCP server interface. Second, a persistent blocker in the
ARM64 virtual machine bring-up was diagnosed at root-cause level and resolved. Third, a
Raspberry Pi 5 was provisioned as the electromagnetic measurement target and passed a
compatibility gate that determines the malware strategy for the remainder of the project.

The most significant result of the week is architectural. The reference paper this work builds
upon used a 32-bit ARM device with 32-bit ARM malware. The available hardware is a 64-bit
Raspberry Pi 5. An empirical test has now confirmed that this device executes 32-bit ARM
binaries natively, via kernel `CONFIG_COMPAT` syscall translation. This removes the single
largest technical risk in the project: had the test failed, the malware class list would have
been reduced from six to four and the experimental design materially altered.

No electromagnetic trace data has been collected yet. Hardware instrumentation and the data
collection script remain outstanding.

---

## 2. Project Objective and Constraints

The project classifies benign and malicious software by analysing the electromagnetic
radiation emitted by a processor during execution, then applying machine learning to the
resulting traces.

Two constraints govern all design decisions, and must be stated explicitly because they
determine what is worth doing and what is not.

**Electromagnetic emissions originate only in physical silicon.** They are produced by CPU
switching activity, power rail transitions, and clocking. No emulator or virtual machine can
produce them. Virtualisation is therefore useful for static analysis, malware triage, and
script development, but it is not a substitute for measurement. The Raspberry Pi 5 is the real
target; everything else is preparation.

**Goodware and malware traces must originate from an identical system state.** If the two
classes are collected under different operating system images, boot states, or service
configurations, a classifier will learn the operating system rather than the malware. This
constraint is not a recommendation; it is a validity requirement, and it is why the operating
system choice made in Section 5 is not negotiable.

---

## 3. Work Package 1 — Malware Analysis Laboratory (Run 1, 19–25 September)

### 3.1 Laboratory design

The initial plan proposed a four-layer nested virtualisation stack: Windows host, VirtualBox,
a Debian x86 guest, and finally QEMU running Debian ARM images. An external review identified
two fundamental errors in this design. The proposed Debian Wheezy images dated from 2013, used
a 3.2 kernel, and targeted ARM32, which cannot execute ARM64 malware and does not match the
Raspberry Pi 5 architecture. Separately, the review correctly identified that electromagnetic
measurement is impossible under emulation, so the nested virtualisation served no measurement
purpose.

The plan was revised to a two-layer architecture. The REMnux distribution was retained as the
analysis environment, since it ships pre-packaged with the required tooling: Ghidra, radare2,
binwalk, UPX, YARA, and Volatility. The separate Debian and Kali images were removed as
redundant. Full-system QEMU ARM64 emulation was retained at user request, for the legitimate
purpose of observing malware network behaviour before execution on physical hardware.

### 3.2 Laboratory deployment

The REMnux virtual machine was deployed and verified. Static analysis tooling, ARM64
emulation, and SSH access were all confirmed operational. A full laboratory plan document was
produced and archived.

### 3.3 ARM64 virtual machine bring-up — initial failure

An ARM64 Ubuntu guest was created and booted under QEMU. Login could not be achieved. The
initial diagnosis, that software emulation was simply slow, was incorrect. Two genuine faults
were present and neither was identified at the time: a port collision on the host, and a
defective boot chain in the guest image itself. This is discussed further in Section 4.

A methodological lesson was recorded. The empty serial console was interpreted as a slow boot
rather than as absence of diagnostic information. Separating "the virtual machine process is
running" from "the guest operating system has booted" from "a service inside the guest is
listening" would have shortened this phase substantially.

---

## 4. Work Package 2 — Root-Cause Resolution and MCP Automation (Run 2, 25–26 September)

### 4.1 Recovery after snapshot reset

The REMnux virtual machine was restored to a clean snapshot, which removed all prior
configuration: SSH host keys, NAT port forwards, working directories, and the ARM64 emulation
virtual machine. This was recovered from the documented setup procedure rather than assumed to
persist.

### 4.2 Root-cause diagnosis of the Run 1 failure

The ARM64 guest failure was traced to a defect in the Ubuntu 24.04 ARM64 cloud image rather
than to emulation speed. The image is a hybrid image containing three relevant partitions. The
EFI system partition contains only the shim and GRUB bootloaders, with no kernel. A separate
`bls_boot` partition contains the actual kernel and initial RAM disk. The root filesystem has
an empty `/boot` and no GRUB configuration directory at all.

The boot chain therefore breaks in the middle. Firmware loads the shim, the shim loads GRUB,
and GRUB reads a configuration that instructs it to locate a volume by filesystem UUID and
chain-load a GRUB configuration from that volume. That file does not exist. GRUB retries the
search indefinitely. The observable symptom is a QEMU process pinned at full CPU with a
minimal disk footprint and a TCP port that completes the handshake but never presents a
service banner, since the host port-forward completes the handshake before the guest operating
system is running at all.

The resolution was to bypass the firmware chain entirely. The kernel and initial RAM disk were
extracted from the `bls_boot` partition and passed directly to QEMU, with an explicit kernel
command line. Three further faults were corrected during this work: the cloud-init seed
required explicit device-tree labelling before the guest would recognise it, the CPU model
setting was replaced with a more permissive value, and virtual CPU count was reduced to one
because software emulation at two cores starved the host and prevented administrative access.

Kernel extraction required a loop-device attachment, because block-device network export is
unavailable inside a guest that is itself virtualised.

### 4.3 Verification

The ARM64 guest reached a verified state: SSH login confirmed, `aarch64` reported by the
kernel, cloud-init completion marker present, outbound network functional, and disk
automatically expanded from 619 MB to 11 GB. A snapshot was recorded to allow fast restoration
between malware test runs, reducing restart time from approximately 35 minutes to under 20.

An architecture enforcement test was performed. A native x86-64 binary transferred to the
guest was rejected with an execution-format error, while a native ARM64 binary executed
successfully. This confirms the guest is a genuine ARM64 kernel rather than a permissive
emulation layer, and therefore that any malware test result from this environment is
architecturally valid.

### 4.4 Analysis automation

A malware analysis MCP server was deployed inside the REMnux guest and registered with the
development environment, making approximately 78 analysis tools directly callable. Following a
snapshot reset, all configuration was restored and verified: token authentication, transport
configuration, sandboxing constraints, and the two required port forwards.

Two security properties are worth recording. The server runs inside the disposable analysis
environment rather than on the host, so the security boundary is the virtual machine itself.
Upload operations are confined to a designated sample directory, so tool calls cannot write
outside it.

### 4.5 Validation of the file transfer path

A generated test image was transferred to the analysis environment and its checksum verified
identical on both sides, confirming the transfer path is lossless. A separate finding, that
graphical applications require display environment variables lifted from a live session, is
recorded because it affects any future visual inspection of sample behaviour.

---

---

## 5. Work Package 3 — Reference Paper Analysis (26–27 September)

The reference paper (Pham and Marion, ACSAC 2021, "Obfuscation Revealed: Leveraging
Electromagnetic Signals for Obfuscated Malware Classification") was retrieved and analysed in
full. This analysis changed the project's experimental plan in three material ways.

### 5.1 The paper does not build malware; it collects malware

The paper obtained 4,790 32-bit ELF ARM samples from an existing malware repository, derived
labels from VirusTotal reports, and normalised them using AVClass plurality voting, yielding 19
families. Mirai accounted for 43.5 per cent and Bashlite for 35.8 per cent.

Only one malware family was derived from source. Gonnacry is open-source, and the authors
extended it with additional cipher suites. Mirai and Bashlite were used as original,
unmodified binaries from the collected corpus.

The variants the authors did generate are obfuscation variants, not new malware. These were
produced with established packers and obfuscators, applying opaque predicates, bogus control
flow, instruction substitution, control-flow flattening, and code virtualisation.

**Implication for this project.** Malware compilation is not required. Existing 32-bit ARM
samples can be used directly. This removes a work package that had been assumed necessary.

### 5.2 The paper's target hardware differs from ours

The paper used a Raspberry Pi 2B, Cortex-A7, 1 GB, running Raspbian Buster with kernel
4.19.57-v7+ armv7l. That is a 32-bit platform. This project has a Raspberry Pi 5, Cortex-A76,
running a 64-bit operating system. The malware architecture question was therefore not
academic: the paper's entire corpus is 32-bit, and the target device is 64-bit.

### 5.3 Two of the six malware classes are architecturally excluded

The paper classifies six families: Bashlite, Mirai, Gonnacry, Keysniffer, MaK_It, and benign.
Of these, Keysniffer and MaK_It are Linux kernel modules. A kernel module must match kernel
version, kernel configuration, and CPU architecture exactly, and cannot be made to load on a
different architecture by any means.

**These two classes are permanently excluded from this project.** This is a hardware
limitation, not a configuration problem, and must be documented as a deviation in the thesis.
The remaining four classes are unaffected.

### 5.4 Acquisition parameters for replication

| Parameter | Reference paper |
|---|---|
| Oscilloscope | Picoscope 6407, 1 GHz bandwidth |
| Probe | Langer RF-R 0.3-3 H-field probe |
| Amplifier | Langer PA-303, +30 dB |
| Probe placement | 45 degrees above the processor |
| Sample rate | 2 MHz |
| Capture window | 2.5 s, 500,000 points, approximately 8 MB per trace |
| Volume | 3,000 traces per binary across 30 binaries, plus 10,000 benign traces |
| Feature extraction | Short-time Fourier transform, window 8192, overlap 4096 |
| Feature selection | Normalised Inter-Class Variance, 20 retained frequency bands |
| Model | Convolutional and multilayer perceptron networks, 50 epochs |
| Train/validation/test split | 80 / 20 |
| Reported accuracy | 99.89 per cent |

Two methodological details warrant adoption. The 2.5 second window was selected empirically
partly because of the idle period in the malware's own sleep cycle, which means a trace window
must be chosen to contain observable activity rather than to capture a process merely existing.
Separately, the paper retained all default background services, with more than 100 running
processes, on the grounds that malware executes alongside genuine device activity; a classifier
trained against a stripped environment would not generalise.

The paper also states that its source code, dataset, and classification materials are published
online. This has not yet been verified as available, and is an outstanding action.

---

## 6. Work Package 4 — Raspberry Pi 5 Provisioning and Compatibility Gate (27 September)

A detailed provisioning procedure was written for execution on a separate machine, covering
imaging, first-boot verification, tooling, electromagnetic preparation, network containment,
and environment fingerprinting. It was then executed against physical Pi 5 hardware and the
results recorded in a separate verification report.

### 6.1 The compatibility gate

This was the decisive test of the week. A 32-bit ARM test program was compiled statically with
the ARM cross-compiler and executed on the 64-bit target.

| Check | Result |
|---|---|
| Kernel `CONFIG_COMPAT` | Present |
| Kernel `CONFIG_COMPAT_BINFMT_ELF` | Present |
| Binary identification | ELF 32-bit LSB executable, ARM, EABI5, statically linked |
| Execution result | Exit code 42, as expected |

**Conclusion.** 32-bit ARM binaries execute natively on this 64-bit device, with the kernel
translating system calls. The fallback plan, which would have reduced the study from six
malware classes to four through a different route, is not required for this reason. Existing
32-bit ARM samples can be used unmodified, and the full malware corpus of the reference paper
is accessible.

### 6.2 Baseline environment

| Property | Value |
|---|---|
| Model | Raspberry Pi 5 Model B Rev 1.0 |
| Kernel | 6.18.34+rpt-rpi-2712 |
| Operating system | Debian GNU/Linux 13 (trixie) |
| C library | 2.41 |
| Architecture reported | aarch64 |
| Thermal throttling flag | 0x0, no throttling |
| Idle temperature | 38.4 to 40.6 degrees Celsius |
| Boot configuration | 64-bit flag confirmed |
| Python | 3.13.5 |
| Clock tuning applied | None, factory default retained |
| Running services | 15, recorded to file |

The throttling flag is the item of greatest significance for data quality. A throttling
processor changes clock frequency mid-capture, which would render traces mutually
incomparable. A zero value at baseline confirms the power supply and cooling are adequate.

### 6.3 Analysis tooling

Build toolchain, disassembly and binary analysis utilities, network capture, and the
scientific Python stack were installed into an isolated environment. GPIO control was
configured and verified on the designated trigger pin.

### 6.4 Network containment

Outbound rules were installed to block Telnet scanning, alternative Telnet scanning, HTTP, and
DNS resolution, and were made persistent across reboots. Each rule was verified to have
accumulated non-zero drop counters, confirming the rules match traffic rather than being
present but inert. This containment must be verified again after the first genuine malware
execution, since the present counters derive from administrative test traffic rather than
scanner behaviour.

A restore point was created before any malware execution, so that a compromised filesystem can
be returned to a known clean state.

---

## 7. Documented Deviations from the Reference Paper

Deviations are recorded explicitly, as the reference paper's own reasoning indicates they
should be.

| Item | Paper | This project | Reason |
|---|---|---|---|
| Device | Raspberry Pi 2B, Cortex-A7 | Raspberry Pi 5, Cortex-A76 | Available hardware |
| Architecture | 32-bit ARM | 64-bit kernel, 32-bit execution confirmed | Available hardware |
| Operating system | Raspbian Buster, kernel 4.19 | Debian 13, kernel 6.18 | Available hardware |
| Malware classes | Six | Four | Two classes are kernel modules and cannot load on a 64-bit platform |
| Wireless radios | Retained as default services | To be blocked before capture | Radio transmission bursts are unbounded external stimulus and would contaminate the measurement |

The fourth deviation in this table is permanent and must be presented as a scope reduction in
the thesis. The fifth is a deliberate departure from the paper's instruction to retain all
default services, and the reasoning differs: retained services constitute background workload,
whereas wireless transmission constitutes external interference of far greater magnitude.

---

---

## 8. Current System State

| Component | State |
|---|---|
| Analysis environment (REMnux) | Operational, 78 analysis tools available |
| ARM64 emulation guest | Operational, verified aarch64, snapshot available |
| Cross-architecture malware execution | Operational, 32-bit confirmed on 64-bit target |
| Raspberry Pi 5 target | Provisioned, all verification checks passed |
| Network containment | Installed and verified, pending re-check after first malware run |
| Environment fingerprint | Recorded on the target, not yet mirrored to the host machine |
| Data collection script | Not yet written |
| Electromagnetic instrumentation | Not yet acquired |
| Dataset | Not yet collected |

---

## 9. Outstanding Risks

**Wireless interface remains active.** The target is currently administered over wireless
networking, so the radio could not be blocked without terminating the session. The wireless
interface must be disabled and access re-established over wired networking before any
electromagnetic capture. This is the highest-priority outstanding item; traces captured before
it is resolved will be contaminated and unusable.

**No measurement hardware confirmed.** The oscilloscope, probe, and amplifier specified by the
reference paper are not yet on hand. This is the principal schedule risk, as procurement lead
time is outside project control.

**Malware corpus not yet sourced.** Confirmation that the reference authors' published dataset
and sample materials remain available is outstanding. If they are, this becomes a
replication study rather than a from-scratch dataset build, which is a substantial saving.

**Trigger mechanism unvalidated on hardware.** The existing benign workload runner provides a
GPIO trigger intended to synchronise capture with execution. This has not been verified against
a real oscilloscope. Since trigger misalignment renders a dataset unusable after the fact, this
should be confirmed with the simplest possible measurement before large-scale capture begins.

**Virtualisation performance.** Software emulation of the ARM64 guest takes approximately 35
minutes to reach a usable state from cold, reduced to under 20 minutes from snapshot. Analysis
workflows depending on this environment will be slow, and the guest should be used for triage
rather than iterative work.

---

## 10. Planned Work for the Following Week

1. Resolve the wireless interface and complete the electromagnetic preparation checklist.
2. Verify whether the reference authors' published dataset and samples are retrievable.
3. Source the 32-bit ARM malware corpus, beginning with Mirai as the dominant family at
   43.5 per cent of the reference corpus.
4. Write the malware workload runner, aligned with the existing benign runner in trigger
   primitive, process topology, measurement window, and duration, so that paired traces are
   comparable. The runner must force observable activity rather than permitting an idle
   process, since an idle bot produces a trace indistinguishable from benign activity.
5. Establish a synthetic command server to deliver reproducible attack instructions, as the
   reference paper did, together with the local network targets required to absorb attack
   traffic.
6. Validate the trigger mechanism against real instrumentation with a minimal capture.
7. Correct two minor errors in the provisioning procedure, which specify a kernel
   configuration path superseded in the current operating system release, and which state the
   expected system version as a choice rather than a fixed value.
8. Verify network containment counters against genuine malware behaviour.

---

## Appendix A — Artefact Inventory

| Artefact | Description |
|---|---|
| `first_run/main_summary.md` | Laboratory design and initial ARM64 bring-up record |
| `first_run/IoT_Malware_EM_Lab_Setup_Plan.docx` | Full laboratory plan document |
| `second_run/main_summary_run2.md` | Analysis automation and root-cause resolution record |
| `pi5_setup/pi5_setup_instructions.md` | Raspberry Pi 5 provisioning procedure |
| `pi5_setup/pi5_setup_report.md` | Raspberry Pi 5 verification report |
| `~/work/environment/` (on target) | Environment fingerprint files, not yet mirrored to the host machine |
| `og_research.pdf` | Reference paper |
| `og_research.txt` | Extracted reference paper text |
| `goodware_runner.py` | Existing benign workload runner with GPIO trigger |

## Appendix B — Reference

Pham, D. P., and Marion, D. "Obfuscation Revealed: Leveraging Electromagnetic Signals for
Obfuscated Malware Classification." Proceedings of the Annual Computer Security Applications
Conference (ACSAC), 2021.
