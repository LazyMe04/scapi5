# Run 3 — Gonnacry Ransomware Build on Raspberry Pi 5

**Date:** 2026-10-03
**Project:** Malware Detection on IoT Devices Using Electromagnetic Side-Channel Analysis
**Target device:** Raspberry Pi 5 Model B Rev 1.0, `pi5@172.16.16.49`, Debian 13 (trixie), kernel `6.18.50+rpt-rpi-2712`
**Malware family:** GonnaCry (tarcisio-marinho/GonnaCry)
**Status:** BUILD SUCCESSFUL — ransomware executes and encrypts on aarch64

---

## 1. Objective

Produce a working, natively-compiled aarch64 build of the GonnaCry ransomware on the Pi 5,
capable of serving as one malware family in the electromagnetic side-channel dataset.

This is the first of the four planned families (mirai, bashlite, gonnacry, benign). Gonnacry was
selected first because its source is public, which removes the reverse-engineering step and makes
it the cheapest family to establish end to end.

---

## 2. Preconditions Verified Before Starting

| Check | Result |
|---|---|
| SSH connectivity to Pi 5 | Established, `172.16.16.49` |
| Device user | `pi5`, member of `sudo` group |
| Key-based authentication | Installed from Windows host `id_ed25519` |
| Kernel architecture | `aarch64` |
| Kernel version | `6.18.50+rpt-rpi-2712` |
| Thermal throttling flag | `throttled=0x0` |
| Idle temperature | 49.9 °C |
| `CONFIG_COMPAT` in kernel | Present |
| 32-bit ARM execution test | `ELF 32-bit LSB executable, ARM, EABI5` — exit code 42 |

The 32-bit compatibility test was re-run on this device and passed again, confirming the result
recorded in the previous run's report remains valid after the kernel update from `6.18.34` to
`6.18.50`.

Note that the kernel configuration path differs from what the provisioning document specifies.
The document states `/boot/firmware/config-$(uname -r)`. On this Debian 13 installation the
configuration is at `/boot/config-$(uname -r)`. This discrepancy should be corrected in the
provisioning document.

---

## 3. Malware Source Analysis

### 3.1 Project nature

GonnaCry is described by its author as academic ransomware, released under GPL-2.0 for study of
malware and applied cryptography. The repository carries an explicit disclaimer against use
against third-party systems. It is a functional, research-grade implementation rather than a
commodity crimeware sample.

This is appropriate for the present purpose. The project requires malware whose behaviour is
known and whose execution is reproducible, not a sample representative of current threat
landscape. The reference paper uses GonnaCry for exactly the same reason.

### 3.2 Cryptographic design

| Property | Implementation |
|---|---|
| File encryption | AES-256-CBC |
| Per-file key and IV | Random, unique per file |
| Key wrapping | AES key encrypted with client public key, RSA-2048 |
| Private key protection | Client private key encrypted with server public key, RSA-2048 |
| Offline operation | Supported; functions without network connectivity |

### 3.3 Component structure

| Component | Role |
|---|---|
| `main.py` | Orchestrator; generates RSA keys, walks files, encrypts, drops payload |
| `daemon.py` | File encryption engine and key persistence |
| `decryptor.py` | Recovery tool; contacts key server to retrieve material |
| `asymmetric.py` | RSA key generation and wrapping |
| `symmetric.py` | AES-256-CBC implementation |
| `generate_keys.py` | Random byte generation |
| `get_files.py` | Filesystem traversal and extension filtering |
| `utils.py` | File shredding and wallpaper manipulation |

### 3.4 Network behaviour

Code inspection confirms that the encryption path (`daemon.py`, invoked from `main.py`) performs
no network operations. The sample walks the filesystem, encrypts in place, writes the encrypted
key manifest, and terminates.

Only `decryptor.py` communicates with a server, and only to retrieve the client private key for
recovery. That component is the attacker's tool, not the victim-side payload, and is never
executed on the device under test.

**Consequence for containment.** The network restrictions required for Mirai-family samples are
not required for GonnaCry. It has no scanner, no brute-force module, no command-and-control
channel, and no propagation mechanism. This was confirmed by reading the source rather than
assumed, and it substantially simplifies the experimental procedure.

---

## 4. Build Procedure

### 4.1 Toolchain

| Component | Version | Installation route |
|---|---|---|
| Python | 3.13.5 | Pre-installed |
| PyCryptodome | 3.20.0 | Distribution package |
| PyInstaller | 6.22.3 | User package via pip |
| Cross compiler | `gcc-arm-linux-gnueabihf` 4:14.2.0 | Pre-installed |

Two installation obstacles arose and were resolved.

**Externally-managed environment.** Debian 13 enforces PEP 668, blocking direct system-wide pip
installation. Resolved by installing to the user site with `--user --break-system-packages`.

**DNS resolution failure.** The initial PyInstaller installation failed with no matching
distribution found. The cause was not a missing wheel, a Python version incompatibility, or an
index problem. The Pi's own DNS resolution was blocked by an outbound firewall rule installed
during the provisioning phase, which dropped all UDP traffic to port 53. Package installation
depended on hostname resolution and therefore failed, while raw IP connectivity remained intact.

The DNS rule was removed. Rules for TCP ports 23, 2323 and 80 were retained. Since GonnaCry
performs no network operations, no outbound restriction is required for this family, and the
DNS rule will be reinstated before any Mirai-family execution.

### 4.2 Source acquisition

The repository was cloned and transferred to the Pi at `~/GonnaCry`. The distribution includes
prebuilt binaries under `src/GonnaCry/bin/`. Those are x86-64 artefacts produced on the author's
machine and are unusable on the Pi 5. All components were rebuilt natively.

### 4.3 Compatibility modifications

The upstream code predates current Python 3 and PyCryptodome releases. Four classes of defect
prevented execution. All modifications are behavioural no-ops with respect to the malware's
cryptographic function; none alters the encryption scheme or its security properties.

**PyCryptodome random source removed.** `generate_keys.py` instantiated
`Crypto.Random.OSRNG.posix.DevURandomRNG()`, an internal class absent from PyCryptodome 3.20.
Replaced with the public `get_random_bytes()` interface, which draws from the same operating
system entropy source.

**AES padding block size.** `symmetric.py` used a 32-byte padding block. AES operates on 16-byte
blocks; the original value happened to produce valid output only because the padding routine
appended a multiple of the block size by coincidence of the sample's data lengths. Corrected to
`AES.block_size`.

**Bytes and string handling.** Several call sites passed Python strings into interfaces expecting
bytes, and vice versa. Python 3 distinguishes the two strictly, where Python 2 did not.
Corrections applied at four sites: encryption input coerced to bytes, base64 output decoded to
text before writing, key manifest file handle corrected from binary to text mode, and manifest
line construction reworked to decode the assembled bytes before writing.

**Third-party module discovery.** PyInstaller did not statically detect the PyCryptodome import.
Resolved with an explicit hidden-import directive.

### 4.4 Resulting artefacts

| Artefact | Size | Format |
|---|---|---|
| `gonnacry` | 28 MB | ELF 64-bit LSB, ARM aarch64, stripped, statically analysed bundle |
| `daemon` | 4.0 MB | ELF 64-bit LSB, ARM aarch64, stripped |
| `decryptor` | 16.7 MB | ELF 64-bit LSB, ARM aarch64, stripped |

All three are genuine aarch64 executables produced by the Pi's own toolchain. None is a
translated or emulated artefact.

---

## 5. Containment Design

### 5.1 Dedicated victim account

GonnaCry determines its target from the executing user's home directory. Running it as the
administrative account would encrypt the working environment, including SSH configuration and
the collected fingerprint files.

A dedicated unprivileged account was created:

```
useradd -m -d /home/victim -s /bin/bash victim
```

This account has no administrative privileges, no SSH access, and no data of value. It serves as
the execution context for all malware runs.

### 5.2 Why this removes the need for full-device snapshots

Because encryption is confined to the victim account's home directory, recovery between runs
requires only regenerating that directory. This replaces whole-device image restoration, which
on this hardware would cost minutes per run and would not be reproducible across thousands of
runs.

The regeneration procedure must produce a deterministic total encrypted byte count while varying
the file count, extension distribution and individual file sizes. Holding total bytes constant
keeps the cryptographic workload comparable between runs; varying the distribution prevents a
classifier from keying on file count or file size rather than on encryption behaviour. The
reference paper motivates the same randomisation requirement for the same reason.

### 5.3 Backup state

`netfilter-persistent` retains the firewall rules across reboots. The DNS rule deletion applies
only to the live ruleset until persistence is refreshed. Before rebooting the device, the saved
ruleset must be updated, or the deleted rule returns.

---

## 6. Execution Verification

### 6.1 Observed behaviour

Execution as the victim account completed successfully. The output contained only expected
non-fatal warnings concerning desktop environment manipulation, which is absent on a headless
installation.

Artefacts produced:

| Artefact | Present |
|---|---|
| `secret.txt.GNNCRY` | Yes |
| `testdata/file1.txt.GNNCRY` | Yes |
| `testdata/file2.txt.GNNCRY` | Yes |
| `gonnacry/AES_encrypted_keys.txt` | Yes, populated |
| `gonnacry/client_public_key.PEM.GNNCRY` | Yes |
| `gonnacry/encrypted_client_private_key.key.GNNCRY` | Yes |
| `gonnacry/daemon` | Yes, dropped |
| `gonnacry/decryptor` | Yes, dropped |

Nine encrypted files total. Every plaintext original was removed by the shredding routine. The
key manifest contains a base64-encoded record per encrypted file, confirming the per-file key
and path bookkeeping completed correctly.

### 6.2 Cryptographic round-trip

An independent round-trip test of the AES-256-CBC implementation was performed to confirm the
padding and key-derivation modifications did not corrupt the cipher. Encryption followed by
manual decryption returned the original plaintext. Output length was consistent with the
expected base64-encoded IV-plus-ciphertext structure.

### 6.3 Recovery path

The decryptor component was not exercised. It requires the RSA server private key material to
unwrap the client private key, which is held by the operator-side key server. Full recovery
verification requires standing up the bundled Python webserver to act as that key escrow
service.

For the side-channel study this is not blocking. Recovery capability affects the realism of the
threat model, not the electromagnetic signature of the encryption workload. It is recorded as an
open item rather than a defect.

---

## 7. Findings and Issues

### 7.1 Defects corrected

| Defect | Cause | Resolution |
|---|---|---|
| PyInstaller install failed, no distribution found | DNS blocked by own firewall rule | Removed UDP 53 rule; install succeeded |
| System-wide pip refused | PEP 668 externally-managed environment | Installed to user site with override |
| `Crypto.Random.OSRNG` attribute error | PyCryptodome internal API removed | Migrated to public `get_random_bytes()` |
| `str` passed to C code, AES failure | Python 3 bytes/str strictness | Coerced at four call sites |
| `b64encode` rejected `str` argument | Same cause | Encoded to bytes first |
| `write()` received bytes in text mode | File handle mode mismatch | Corrected to text mode, decode before write |
| Manifest line assembly failed | Byte and text concatenation | Decoded assembled bytes before write |
| Payload directory not created | Sample expects directory to pre-exist | Created in victim home before run |
| PyCryptodome not bundled | Import not statically detected | Added explicit hidden-import |

### 7.2 Environmental observations

**Kernel configuration path.** The provisioning document specifies
`/boot/firmware/config-$(uname -r)`. On Debian 13 the path is `/boot/config-$(uname -r)`. Both
were checked; the document requires correction.

**Kernel version drift.** The device now reports `6.18.50+rpt-rpi-2712`, upgraded from
`6.18.34` recorded in the previous report. The 32-bit compatibility result was re-verified and
still holds. The environment fingerprint should be regenerated to match.

**Firewall self-interference.** A containment rule intended to protect against malware caused a
self-inflicted outage by blocking the host's own package management. The lesson generalises:
containment rules must be validated against the administrative workflows that share the same
host. Rules added to defend against one threat can disable the capability needed to detect the
next.

**Credential strength.** The device uses a three-to-one repeating numeric sequence as the
administrative password, and it was required repeatedly during this run. Any device holding
research data or with network access to institutional infrastructure should have a unique
credential. This is recorded as an operational risk, not a research finding.

---

## 8. State After This Run

| Component | State |
|---|---|
| Pi 5 SSH access | Key-based authentication working |
| Gonnacry source | Cloned, patched, version-controlled |
| GonnaCry aarch64 build | Three binaries built and verified |
| Victim account | Created, populated, encryption confirmed |
| Honeypot regeneration | Not yet scripted |
| Malware workload runner | Not yet written |
| Separation test against benign crypto profile | Not yet performed |
| Electromagnetic capture | Not started |
| Key escrow server | Not stood up |

---

## 9. Outstanding Work

1. Script deterministic honeypot regeneration. Fix total encrypted byte count; randomise file
   count, extension mix and per-file sizes.
2. Confirm the regenerated environment is reproducible across runs by measuring encrypted
   output size.
3. Write the malware workload runner, aligned with the existing benign runner on trigger pin,
   pre-trigger and post-trigger delay, measurement window, and process topology.
4. Verify that the malware runner and the benign runner produce traces separable in the
   frequency domain. The benign runner includes a cryptographic profile; GonnaCry performs
   AES-256-CBC. Confirm these are distinguishable before scaling to a full dataset, since a
   malware class sitting inside a benign class is expensive to discover late.
5. Stand up the key escrow webserver if recovery verification is required.
6. Regenerate the environment fingerprint to match the current kernel.
7. Confirm the trigger mechanism against real instrumentation with a minimal capture before
   committing to large-scale acquisition.
8. Reinstate the DNS rule before any Mirai-family execution.

---

## 10. Methodological Notes

**Source modification is unavoidable and must be recorded.** Four compatibility defects required
source changes. All are API migrations with no effect on the encryption scheme, key sizes, or
file selection logic. Any dataset generated from this build must state the exact source revision
and patch set used, otherwise the results are not reproducible. The modifications are recorded
in the repository as version-controlled diffs.

**Containment appropriate to the family.** GonnaCry requires no network containment, which is
the opposite of the Mirai case. Applying unnecessary restrictions risks the self-interference
observed in Section 7.2. The rule is that containment is derived from observed behaviour of the
specific sample, not applied uniformly.

**The benchmark must be matched to the malware.** The existing benign runner includes a
cryptographic profile using SHA-256 and PBKDF2. GonnaCry performs AES-256-CBC, which uses
substitution tables and finite field multiplication. These are expected to differ observably in
the electromagnetic domain, but the expectation must be tested rather than assumed, and tested
before rather than after a full dataset is acquired.

---

## Appendix A — Reproduction Commands

```bash
# Toolchain
sudo apt install -y python3-pycryptodome python3-pip python3-venv
pip3 install --user --break-system-packages pyinstaller

# Source
git clone https://github.com/tarcisio-marinho/GonnaCry.git ~/GonnaCry

# Apply the four compatibility patches documented in Section 4.3

# Build
cd ~/GonnaCry/src
export PATH=$HOME/.local/bin:$PATH
pyinstaller -F --clean --hidden-import=Crypto GonnaCry/main.py     -n gonnacry
pyinstaller -F --clean --hidden-import=Crypto GonnaCry/daemon.py    -n daemon
pyinstaller -F --clean --hidden-import=Crypto GonnaCry/decryptor.py -n decryptor

# Verify
file dist/gonnacry
# expect: ELF 64-bit LSB executable, ARM aarch64

# Containment
sudo useradd -m -d /home/victim -s /bin/bash victim

# Execute
sudo cp ~/GonnaCry/src/dist/gonnacry /home/victim/gonnacry.bin
sudo chmod +x /home/victim/gonnacry.bin
sudo chown victim:victim /home/victim/gonnacry.bin
sudo -u victim bash -c 'cd /tmp && mkdir -p /home/victim/gonnacry && /home/victim/gonnacry.bin'

# Verify encryption
sudo find /home/victim -name '*.GNNCRY' | wc -l
```

## Appendix B — Reference

Marinho, T. "GonnaCry." https://github.com/tarcisio-marinho/GonnaCry. GPL-2.0.

Pham, D. P., and Marion, D. "Obfuscation Revealed: Leveraging Electromagnetic Signals for
Obfuscated Malware Classification." Proceedings of the Annual Computer Security Applications
Conference (ACSAC), 2021.