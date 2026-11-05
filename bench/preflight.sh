#!/usr/bin/env bash
# preflight.sh - Raspberry Pi 5 bench readiness check
# Run this on the Pi before every electromagnetic capture session.
# Exit 0 = ready. Exit 1 = at least one blocker.

PASS=0; FAIL=0; WARN=0
ok()   { printf '  [ OK ] %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }
warn() { printf '  [WARN] %s\n' "$1"; WARN=$((WARN+1)); }
hdr()  { printf '\n=== %s ===\n' "$1"; }

# sudo without hanging on a password prompt
if ! sudo -n true 2>/dev/null; then
    printf 'Caching sudo credentials...\n'
    sudo -v || true
fi

printf '\n=========================================\n'
printf ' Raspberry Pi 5 - Bench Preflight Check\n'
printf ' %s\n' "$(date -Is)"
printf '=========================================\n'

# ---------------------------------------------------------------- system
hdr 'SYSTEM'

ARCH=$(uname -m)
if [ "$ARCH" = 'aarch64' ]; then
    ok "architecture aarch64"
else
    bad "architecture is $ARCH, expected aarch64"
fi

KVER=$(uname -r)
printf '  [info] kernel %s\n' "$KVER"

THROTTLE=$(vcgencmd get_throttled 2>/dev/null | grep -o '0x[0-9a-f]*')
if [ "$THROTTLE" = '0x0' ]; then
    ok "no thermal or power throttling"
else
    bad "THROTTLED state is $THROTTLE - dataset will be invalid"
    printf '         0x5000 under-voltage, 0x40000 throttled since boot\n'
fi

TEMP=$(vcgencmd measure_temp 2>/dev/null | grep -o '[0-9.]*')
if [ -n "$TEMP" ]; then
    if awk "BEGIN{exit !($TEMP < 70)}"; then
        ok "temperature ${TEMP}C under 70C"
    else
        bad "temperature ${TEMP}C is too high - fit the active cooler"
    fi
else
    warn "could not read temperature"
fi

# ---------------------------------------------------------------- network
hdr 'NETWORK'

IFACE=$(ip -br addr show eth0 2>/dev/null | awk '{print $1}')
IPADDR=$(ip -br addr show eth0 2>/dev/null | awk '{print $3}' | cut -d/ -f1)
printf '  [info] eth0 %s at %s\n' "${IFACE:-absent}" "${IPADDR:-none}"

if printf '%s' "$IPADDR" | grep -q '^192\.168\.7\.'; then
    ok "bench static link active (192.168.7.x)"
else
    warn "not on bench static IP - run: nmcli con up bench-static"
fi

if ip -br link show wlan0 2>/dev/null | grep -q DOWN; then
    ok "wlan0 is DOWN"
else
    bad "wlan0 is UP - radio bursts will contaminate every trace"
    printf '         fix: sudo rfkill block wifi\n'
fi

if rfkill list 2>/dev/null | grep -q 'Soft blocked: yes'; then
    ok "radio soft-blocked"
else
    warn "no radio soft-block recorded - check rfkill list"
fi

RULE53=$(sudo iptables -n -L OUTPUT 2>/dev/null | grep -c 'dpt:53')
if [ "$RULE53" -ge 1 ]; then
    bad "DNS drop rule present - package installs and updates will fail"
    printf '         fix: sudo iptables -D OUTPUT <line>\n'
else
    ok "DNS reachable (Gonnacry needs no DNS drop)"
fi

# ---------------------------------------------------------------- em prep
hdr 'EM PREPARATION'

if [ -e /sys/class/gpio/gpio17 ]; then
    ok "GPIO17 exported"
elif command -v gpioinfo >/dev/null 2>&1 && gpioinfo 2>/dev/null | grep -q 'line 17'; then
    ok "GPIO17 present and free"
else
    warn "GPIO17 not exported yet - runner will do it at runtime"
fi

TUNING=$(grep -E '^\s*(arm_freq|overclock|force_turbo|overclock_min|overclock_max)' /boot/firmware/config.txt 2>/dev/null | grep -v '^\s*#')
if [ -z "$TUNING" ]; then
    ok "no clock tuning or overclocking"
else
    bad "clock tuning present in config.txt - dataset not comparable"
    printf '         %s\n' "$TUNING"
fi

ARM64FLAG=$(grep -E '^arm_64bit=1' /boot/firmware/config.txt 2>/dev/null)
if [ -n "$ARM64FLAG" ]; then
    ok "arm_64bit=1 confirmed"
else
    warn "arm_64bit flag not found in config.txt"
fi

SERVICES=$(systemctl list-units --type=service --state=running 2>/dev/null | grep -c running)
printf '  [info] %s services running (keep default per paper)\n' "$SERVICES"

# ---------------------------------------------------------------- malware
hdr 'MALWARE - GONNACRY'

BIN=/home/victim/gonnacry.bin
if sudo test -x "$BIN" 2>/dev/null; then
    FILEOUT=$(sudo file -b "$BIN" 2>/dev/null)
    if printf '%s' "$FILEOUT" | grep -q 'ARM aarch64'; then
        ok "gonnacry.bin present, native aarch64"
    else
        bad "gonnacry.bin is not aarch64: $FILEOUT"
    fi
else
    bad "gonnacry.bin missing at $BIN"
fi

if id victim >/dev/null 2>&1; then
    ok "victim account exists"
else
    bad "victim account missing - sudo useradd -m -d /home/victim victim"
fi

PLAIN=$(sudo find /home/victim -type f ! -name '*.GNNCRY' ! -name '.*' ! -name 'gonnacry.bin' ! -path '*/gonnacry/*' 2>/dev/null | wc -l)
ENC=$(sudo find /home/victim -name '*.GNNCRY' 2>/dev/null | wc -l)
printf '  [info] plaintext files %s, encrypted files %s\n' "$PLAIN" "$ENC"

if [ "$PLAIN" -eq 0 ] && [ "$ENC" -gt 0 ]; then
    bad "honeypot is exhausted - regenerate before running"
    printf '         every plaintext file is already encrypted\n'
elif [ "$PLAIN" -lt 50 ]; then
    warn "only $PLAIN plaintext files - trace needs a real workload"
    printf '         suggest 200 or more files for a 2.5s window\n'
else
    ok "honeypot has $PLAIN plaintext files ready"
fi

RESIDUE=$(sudo find /home/victim -maxdepth 1 -name 'keys' -o -maxdepth 1 -name 'gonnacry' 2>/dev/null | wc -l)
if [ "$RESIDUE" -gt 0 ]; then
    warn "leftover keys/ and gonnacry/ dirs from previous run"
fi

# ---------------------------------------------------------------- tooling
hdr 'TOOLING'

for t in python3 file rfkill nmcli gpioinfo vcgencmd; do
    if command -v "$t" >/dev/null 2>&1; then
        ok "$t available"
    else
        bad "$t missing"
    fi
done

PYV=$(python3 --version 2>&1 | awk '{print $2}')
printf '  [info] python %s\n' "$PYV"

if python3 -c 'import Crypto' 2>/dev/null; then
    ok "PyCryptodome importable"
else
    bad "PyCryptodome missing - sudo apt install python3-pycryptodome"
fi

if python3 -c 'import RPi.GPIO' 2>/dev/null; then
    ok "RPi.GPIO importable for the trigger"
else
    warn "RPi.GPIO missing - needed for GPIO17 trigger"
fi

PICO=$(lsusb 2>/dev/null | grep -ci pico)
if [ "$PICO" -gt 0 ]; then
    ok "Pico device visible on USB"
else
    warn "no Pico device on this USB bus"
    printf '         scope is usually on the laptop, not the Pi - that is fine\n'
fi

# ---------------------------------------------------------------- disk
hdr 'STORAGE'

FREE=$(df -h / | awk 'NR==2{print $4}')
printf '  [info] %s free on root\n' "$FREE"
FREEGB=$(df -BG / | awk 'NR==2{gsub("G","",$4); print $4}')
if [ "${FREEGB:-0}" -lt 2 ]; then
    bad "less than 2 GB free - traces will not fit"
else
    ok "sufficient space for trace storage"
fi

# ---------------------------------------------------------------- verdict
printf '\n=========================================\n'
printf ' RESULT: %s pass, %s warn, %s fail\n' "$PASS" "$WARN" "$FAIL"
printf '=========================================\n'

if [ "$FAIL" -gt 0 ]; then
    printf '\n NOT READY. Fix the FAIL items above before capturing.\n\n'
    exit 1
fi
if [ "$WARN" -gt 0 ]; then
    printf '\n READY WITH WARNINGS. Check the WARN items first.\n\n'
    exit 0
fi
printf '\n READY. Safe to begin capture.\n\n'
exit 0