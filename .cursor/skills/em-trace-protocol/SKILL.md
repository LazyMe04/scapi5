---
name: em-trace-protocol
description: Collects and preprocesses electromagnetic traces on the Raspberry Pi 5 for malware vs goodware classification. Use when the user mentions oscilloscope, GPIO trigger, EM trace, spectrogram, STFT, NICV, dataset, goodware_runner, probe placement, or throttling.
---

# EM trace protocol

Paper: Pham et al., ACSAC 2021 (`og_research.txt`). Hardware here is Pi 5, not Pi 2B. Follow `pi5_setup/pi5_setup_instructions.md` and `goodware_runner.py`.

## Pre-capture gates

Stop if any fail:

1. `vcgencmd get_throttled` → `throttled=0x0`. Non-zero (`0x5000` undervoltage, `0x40000` past throttle) invalidates the set.
2. Idle temp under 70°C. Official 27 W PSU and cooling required.
3. No `arm_freq` / `overclock` / `force_turbo` in `/boot/firmware/config.txt`.
4. Same OS image and running services for goodware and malware. Do not disable default services.
5. WiFi/Bluetooth soft-blocked (`rfkill`). Ethernet only. Document as a paper deviation.
6. Probe position logged; do not move the Pi mid-dataset.
7. Environment fingerprint saved (`pi5_setup` §8) before the campaign.

Pi 5 32-bit userland ELFs execute (`CONFIG_COMPAT` gate passed 2026-09-27). Kernel modules still excluded.

## Trigger and runner

`goodware_runner.py` asserts GPIO 17 (or ACT LED) for the workload window, then cooldown (default 0.3 s) so the governor can settle.

```bash
python3 goodware_runner.py --task crypto --count 10 --duration 1.5 --gpio-pin 17
python3 goodware_runner.py --task all --dry-run   # Windows rehearsal only; no EM
```

`--dry-run` is not a dataset. Workloads: `idle`, `crypto`, `compress`, `math`, `network`. Default duration in the runner is 1.5 s; the paper used 2.5 s at 2 MHz (500,000 points). If replicating the paper window, set `--duration 2.5` and match the scope record length. Do not mix durations in one labeled set.

## Paper acquisition (replicate unless hardware forces a change)

| Item | Paper value |
|---|---|
| Scope | PicoScope 6407, 1 GHz |
| Probe | Langer RF-R 0.3-3 H-field, 45° above CPU |
| Amp | Langer PA-303 +30 dB |
| Rate / window | 2 MHz / 2.5 s |

Record the actual scope model if different. Coupling geometry matters more than brand.

## Preprocess (paper)

1. STFT spectrogram: window `M=8192`, overlap `O=4096`.
2. NICV per time-frequency bin vs labels; keep the `epsilon` frequency bands with highest mean NICV over time (paper searched `epsilon` in `{4,8,...,28}`).
3. CNN/MLP on selected bands; LDA then NB/SVM if using classical models. LDA is for NB/SVM, not for CNNs.
4. Split: hold out 20% traces; never train on the test set. Novelty scenario holds out obfuscation variants, not random traces of the same binary.

Store raw traces plus fingerprint (kernel, libc, throttle, temp, `systemctl` running units). A set without fingerprint is not publishable.

## Isolation

Malware capture only after the malware-isolation skill checklist (VLAN or iptables, spoofed C2, restore point). A leaked scan is a legal failure, not a data issue.
