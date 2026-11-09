#!/usr/bin/env bash
# isolation-on.sh - put the Pi 5 into a default-deny network posture for a malware run.
#
# Design
# ------
# The bench link is point-to-point (laptop 192.168.7.1, Pi 192.168.7.2) with no
# uplink. That alone is not enough: this script makes the kernel enforce it, so a
# mistake in the runner cannot leak a scan onto a real network.
#
#   INPUT      default DROP, allow loopback, replies, and SSH from the admin host only
#   FORWARD    default DROP
#   OUTPUT     default DROP, allow loopback, replies, and anything addressed to the
#              lab C2 host (a single address on the bench link)
#   NAT OUTPUT redirects the ports a botnet hardcodes (C2, telnet, http) to the C2
#              host, so the sample keeps working without patching its binary.
#
# Nothing is persisted unless --persist is given. The historical reason is in
# BENCH_OPERATIONS.md section 10: a permanent UDP/53 drop broke apt on this device.
#
# Usage
# -----
#   sudo bash isolation-on.sh                       # defaults: admin + C2 = 192.168.7.1
#   sudo bash isolation-on.sh --c2 192.168.7.1 --admin 192.168.7.1
#   sudo bash isolation-on.sh --no-redirect         # only allow the C2 port
#   sudo bash isolation-on.sh --live-c2 1.2.3.4     # also drop a hardcoded botnet IP
#   sudo bash isolation-on.sh --live-c2 ""          # drop nothing but the policy
#   sudo bash isolation-on.sh --dry-run             # print the ruleset, change nothing
#   sudo bash isolation-on.sh --persist             # also netfilter-persistent save
#   sudo bash isolation-on.sh --status              # show current state, change nothing
#
# Rollback: sudo bash isolation-off.sh

set -euo pipefail

# Rollback lives at the repo root: isolation-off.sh (one level up from this script).

ADMIN_HOST="${ADMIN_HOST:-192.168.7.1}"
C2_HOST="${C2_HOST:-192.168.7.1}"
# 349d2476…b777 hardcodes 181.214.147.11:999, so 999 must be the default C2 port.
C2_PORT="${C2_PORT:-999}"
ADMIN_IFACE="${ADMIN_IFACE:-eth0}"
SSH_PORT="${SSH_PORT:-22}"
# Ports a Bashlite/Mirai-family sample contacts on its own. Redirected to C2_HOST
# so the sample behaves as if the internet existed. 999 is this sample's C2.
REDIRECT_PORTS="${REDIRECT_PORTS:-999 6667 2323 23 80 443}"
# Live botnet endpoint embedded in the sample. Every packet aimed at it is
# either DNAT'd to the lab C2 (the redirected ports above) or dropped here,
# so none can leave. Which counter proves what is spelled out below.
LIVE_C2="181.214.147.11"
REDIRECT=1
PERSIST=0
DRY_RUN=0
STATUS_ONLY=0
ALLOW_DNS=0
OWNER_USER=""

usage() {
    awk 'NR>1 && /^set -euo/ {exit} NR>1 {sub(/^# ?/, ""); print}' "$0"
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --admin)      ADMIN_HOST="$2"; shift 2 ;;
        --c2)         C2_HOST="$2"; shift 2 ;;
        --c2-port)    C2_PORT="$2"; shift 2 ;;
        --iface)      ADMIN_IFACE="$2"; shift 2 ;;
        --ssh-port)   SSH_PORT="$2"; shift 2 ;;
        --redirect-ports) REDIRECT_PORTS="$2"; shift 2 ;;
        --live-c2)    LIVE_C2="$2"; shift 2 ;;
        --owner-user) OWNER_USER="$2"; shift 2 ;;
        --no-redirect) REDIRECT=0; shift ;;
        --allow-dns)  ALLOW_DNS=1; shift ;;
        --persist)    PERSIST=1; shift ;;
        --dry-run)    DRY_RUN=1; shift ;;
        --status)     STATUS_ONLY=1; shift ;;
        -h|--help)    usage 0 ;;
        *) echo "unknown option: $1" >&2; usage 1 ;;
    esac
done

say()  { printf '  %s\n' "$*"; }
head_() { printf '\n=== %s ===\n' "$*"; }

if [[ "$STATUS_ONLY" == 1 ]]; then
    head_ "current OUTPUT state"
    iptables  -S OUTPUT
    echo
    iptables  -t nat -S OUTPUT
    echo
    head_ "verdict helper"
    echo "  The runner classifies this as 'full' when the OUTPUT policy is DROP and"
    echo "  no rule accepts traffic to a non-private address."
    exit 0
fi

if [[ "$(id -u)" -ne 0 ]] && [[ "$DRY_RUN" == 0 ]]; then
    echo "ERROR: run as root (sudo bash $0 ...); --dry-run and --status need no root" >&2
    exit 1
fi

command -v iptables >/dev/null || { echo "ERROR: iptables not found" >&2; exit 1; }

# Resolve the uid to scope the NAT redirect to the sample's account, when asked.
OWNER_MATCH=()
if [[ -n "$OWNER_USER" ]]; then
    if ! id "$OWNER_USER" >/dev/null 2>&1; then
        echo "ERROR: --owner-user '$OWNER_USER' does not exist" >&2
        exit 1
    fi
    OWNER_MATCH=(-m owner --uid-owner "$OWNER_USER")
fi

run() {
    if [[ "$DRY_RUN" == 1 ]]; then
        printf '    %s\n' "$*"
    else
        "$@"
    fi
}

head_ "plan"
say "admin host      : $ADMIN_HOST (SSH $SSH_PORT on $ADMIN_IFACE)"
say "C2 host         : $C2_HOST port $C2_PORT"
say "redirect        : $([[ $REDIRECT == 1 ]] && echo "ports [$REDIRECT_PORTS] -> $C2_HOST" || echo 'disabled')"
say "live C2 dropped : ${LIVE_C2:-<none>} (every protocol, every port)"
say "allow DNS       : $([[ $ALLOW_DNS == 1 ]] && echo yes || echo 'no (dropped)')"
say "owner scope     : ${OWNER_USER:-<any uid>}"
say "persist         : $([[ $PERSIST == 1 ]] && echo yes || echo 'no (session only)')"
say "dry run         : $([[ $DRY_RUN == 1 ]] && echo yes || echo no)"

# Roll back a half-applied ruleset if any command fails mid-way.
APPLIED=0
rollback_partial() {
    if [[ "$APPLIED" == 1 ]]; then
        echo "  [rollback] a rule failed; restoring permissive defaults" >&2
        iptables -P INPUT ACCEPT 2>/dev/null || true
        iptables -P FORWARD ACCEPT 2>/dev/null || true
        iptables -P OUTPUT ACCEPT 2>/dev/null || true
        iptables -t nat -F OUTPUT 2>/dev/null || true
    fi
}

if [[ "$DRY_RUN" == 0 ]]; then
    trap rollback_partial ERR
fi
APPLIED=1

# ------------------------------------------------------------------ NAT (before filter)
if [[ "$REDIRECT" == 1 ]]; then
    head_ "redirecting botnet ports to the lab C2"
    for port in $REDIRECT_PORTS; do
        run iptables -t nat -C OUTPUT -p tcp "${OWNER_MATCH[@]}" --dport "$port" \
            -j DNAT --to-destination "$C2_HOST" 2>/dev/null || \
        run iptables -t nat -A OUTPUT -p tcp "${OWNER_MATCH[@]}" --dport "$port" \
            -j DNAT --to-destination "$C2_HOST"
    done
fi

# ------------------------------------------------------------------ policies
head_ "applying default-deny policies"
run iptables -P INPUT   DROP
run iptables -P FORWARD DROP
run iptables -P OUTPUT  DROP

# ------------------------------------------------------------------ INPUT
head_ "allowing loopback, replies, and admin SSH"
run iptables -A INPUT -i lo -j ACCEPT
run iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
run iptables -A INPUT -i "$ADMIN_IFACE" -s "$ADMIN_HOST" -p tcp --dport "$SSH_PORT" -j ACCEPT
# ICMP from the admin host only, for diagnostics (ping / path MTU).
run iptables -A INPUT -i "$ADMIN_IFACE" -s "$ADMIN_HOST" -p icmp -j ACCEPT

# ------------------------------------------------------------------ OUTPUT
head_ "allowing loopback, replies, and the C2 host only"
run iptables -A OUTPUT -o lo -j ACCEPT
run iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
if [[ "$ALLOW_DNS" == 1 ]]; then
    run iptables -A OUTPUT -d "$C2_HOST" -p udp --dport 53 -j ACCEPT
fi
# One ACCEPT to a single bench address. The runner treats a private-only
# destination as bench-scoped, not as open egress.
run iptables -A OUTPUT -d "$C2_HOST" -j ACCEPT

# Explicit DROP counters. They are shadows of the policy here, kept because a
# non-zero counter is the operational proof that the sample really tried to leave.
head_ "adding explicit DROP rules for counter evidence"
run iptables -A OUTPUT -p tcp --dport 23   -j DROP
run iptables -A OUTPUT -p tcp --dport 2323 -j DROP
run iptables -A OUTPUT -p tcp --dport 80   -j DROP
run iptables -A OUTPUT -p udp --dport 53   -j DROP

# The sample carries a live botnet endpoint. nat/OUTPUT runs before filter/OUTPUT,
# so a TCP connect to a redirect port (999 here) is already rewritten to the lab
# C2 before these rules are evaluated: the sample keeps working, and nothing is
# sent to the real botnet.
#
# Read the right counter when you audit a run:
#   * nat OUTPUT DNAT rule   - increments once per C2 session. THIS is the proof
#     the sample tried to phone home, because a redirected packet never reaches
#     the DROP rules below.
#   * filter OUTPUT DROP     - increments only for traffic to LIVE_C2 on a port
#     or protocol that was not redirected. Zero here means "it tried nothing
#     else", not "nothing happened".
if [[ -n "$LIVE_C2" ]]; then
    head_ "dropping the sample's live C2 ($LIVE_C2)"
    run iptables -A OUTPUT -d "$LIVE_C2" -p tcp -j DROP
    run iptables -A OUTPUT -d "$LIVE_C2" -p udp -j DROP
    run iptables -A OUTPUT -d "$LIVE_C2" -j DROP
fi

# ------------------------------------------------------------------ IPv6
head_ "disabling IPv6 egress"
if [[ -d /proc/sys/net/ipv6 ]]; then
    run sysctl -q -w net.ipv6.conf.all.disable_ipv6=1
    run sysctl -q -w net.ipv6.conf.default.disable_ipv6=1
else
    say "IPv6 not present, nothing to do"
fi

trap - ERR

if [[ "$DRY_RUN" == 1 ]]; then
    echo
    echo "DRY RUN: nothing was changed."
    exit 0
fi

# ------------------------------------------------------------------ verify
head_ "verifying"
FAILED=0
check_blocked() {
    local label="$1"; shift
    if "$@" >/dev/null 2>&1; then
        say "FAIL: $label succeeded (containment is NOT active)"
        FAILED=1
    else
        say "ok  : $label blocked"
    fi
}

if command -v curl >/dev/null; then
    check_blocked "HTTPS to 1.1.1.1" curl -m 4 -s -o /dev/null https://1.1.1.1
fi
if command -v nc >/dev/null; then
    check_blocked "TCP 80 to 1.1.1.1" nc -z -w 3 1.1.1.1 80
    check_blocked "TCP 23 to 8.8.8.8" nc -z -w 3 8.8.8.8 23
fi

if [[ "$FAILED" == 1 ]]; then
    echo
    echo "VERIFICATION FAILED. Do not run a sample. Run: sudo bash isolation-off.sh     # from the repo root" >&2
    exit 2
fi

if [[ "$PERSIST" == 1 ]]; then
    head_ "persisting"
    if command -v netfilter-persistent >/dev/null; then
        netfilter-persistent save
        say "saved (remember: this survives reboot; run isolation-off.sh afterwards)     # from the repo root"
    else
        say "netfilter-persistent not installed; rules are session-only"
    fi
fi

cat <<EOF

Isolation is ON.
  - SSH from $ADMIN_HOST:$SSH_PORT still works.
  - Everything else outbound is dropped except the C2 host $C2_HOST.
  - Sample ports $REDIRECT_PORTS are redirected to $C2_HOST.

During the run, watch the counters:
  sudo iptables -t nat -L OUTPUT -n -v    # DNAT hits = real C2 sessions, redirected
  sudo iptables -L OUTPUT -n -v           # DROPs = attempts on anything else

When finished:
  sudo bash isolation-off.sh     # lives at the repo root
EOF
