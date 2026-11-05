#!/usr/bin/env bash
# isolation-off.sh - restore permissive networking after a malware run.
#
# Removes every rule isolation-on.sh adds, flushes its NAT table, restores the
# ACCEPT policies, and re-enables IPv6. Does NOT touch rules owned by something
# else: it only flushes the OUTPUT nat chain and the filter table that the lab
# scripts manage.
#
# Usage:
#   sudo bash isolation-off.sh            # restore
#   sudo bash isolation-off.sh --dry-run  # print what would change
#   sudo bash isolation-off.sh --wipe     # full flush of all filter chains (last resort)

set -euo pipefail

DRY_RUN=0
WIPE=0

usage() {
    awk 'NR>1 && /^set -euo/ {exit} NR>1 {sub(/^# ?/, ""); print}' "$0"
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --wipe)    WIPE=1; shift ;;
        -h|--help) usage 0 ;;
        *) echo "unknown option: $1" >&2; usage 1 ;;
    esac
done

say() { printf '  %s\n' "$*"; }
head_() { printf '\n=== %s ===\n' "$*"; }

if [[ "$(id -u)" -ne 0 ]] && [[ "$DRY_RUN" == 0 ]]; then
    echo "ERROR: run as root (sudo bash $0); --dry-run needs no root" >&2
    exit 1
fi

run() {
    if [[ "$DRY_RUN" == 1 ]]; then
        printf '    %s\n' "$*"
    else
        "$@"
    fi
}

head_ "restoring policies"
run iptables -P INPUT   ACCEPT
run iptables -P FORWARD ACCEPT
run iptables -P OUTPUT  ACCEPT

head_ "clearing lab rules"
if [[ "$WIPE" == 1 ]]; then
    say "wipe mode: flushing every filter chain and the nat table"
    run iptables -F
    run iptables -t nat -F
    run iptables -X
else
    # Target only the chains this lab writes to. Order matters: remove the DROP
    # counters for the sample ports first, then the bench-scoped ACCEPT rules.
    for port in 23 2323 80; do
        run iptables -D OUTPUT -p tcp --dport "$port" -j DROP 2>/dev/null || true
    done
    run iptables -D OUTPUT -p udp --dport 53 -j DROP 2>/dev/null || true
    run iptables -t nat -F OUTPUT
fi

head_ "re-enabling IPv6"
if [[ -d /proc/sys/net/ipv6 ]]; then
    run sysctl -q -w net.ipv6.conf.all.disable_ipv6=0
    run sysctl -q -w net.ipv6.conf.default.disable_ipv6=0
else
    say "IPv6 not present, nothing to do"
fi

if [[ "$DRY_RUN" == 0 ]]; then
    head_ "state after rollback"
    iptables -S
    echo
    iptables -t nat -S OUTPUT

    head_ "connectivity re-check"
    say "Outbound traffic is no longer filtered. If a check fails now, the cause"
    say "is the network or the uplink, not the firewall."

    if command -v netfilter-persistent >/dev/null; then
        say ""
        say "NOTE: if isolation-on.sh was run with --persist, the restrictive ruleset"
        say "is still saved on disk and will return at reboot. Refresh it now with:"
        say "    sudo netfilter-persistent save"
    fi
fi

cat <<'EOF'
Isolation is OFF.
  - Remember to delete the sample from the device:
        rm -f /home/victim/work/samples/bashlite.bin
  - If this device holds data you care about, restore the SD image instead of
    trusting the filesystem to be unchanged.
EOF
