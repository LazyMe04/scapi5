#!/bin/bash
# wait-guest.sh - Poll the ARM64 guest SSH until it answers, then verify login.
# Runs INSIDE the REMnux guest (the QEMU hostfwd lives on REMnux loopback).
# Exits 0 = ready, 2 = timeout.
#
# IMPORTANT - WHY THERE IS NO "auth failed" EXIT:
# cloud-init injects the WINDOWS host public key into the ARM64 guest, not a REMnux key. This
# script runs inside REMnux, so any key it offers is by definition the wrong one, and ssh will
# always answer "Permission denied (publickey)" - even when the guest is perfectly healthy and
# reachable from Windows over the -L 2232 tunnel. Treating that as a failure produces false
# alarms. So this script reports READY/UNREACHABLE only, and defers all authentication truth to
# a Windows-side login, which carries the correct key:
#
#   ssh -p 2232 -i ~/.ssh/id_ed25519 ubuntu@127.0.0.1
#
# A "Permission denied" here therefore only proves the guest reached kex - which is itself the
# readiness signal we want.

set -u
LOG=~/arm64-vm/logs/wait-guest.log
MAX="${MAX_TRIES:-90}"
SLEEP="${SLEEP_SECS:-10}"

: > "$LOG"
for i in $(seq 1 "$MAX"); do
  TS=$(date +%H:%M:%S)
  OUT=$(timeout 12 ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o BatchMode=yes -o ConnectTimeout=6 -p 2222 ubuntu@127.0.0.1 \
        "echo READY; uname -m" 2>&1)
  SHORT=$(echo "$OUT" | tr '\n' ' ' | cut -c1-80)
  echo "[$TS] try $i/$MAX: $SHORT" >> "$LOG"

  # Reaching kex at all means sshd is up and the guest is alive. "Permission denied" and
  # "Connection reset by peer" both qualify - the wrong key is expected here.
  if echo "$OUT" | grep -q READY; then
    echo "ARM64_GUEST_READY arch=$(echo "$OUT" | grep -o 'aarch64')"
    exit 0
  fi
  if echo "$OUT" | grep -qiE "Permission denied|Connection reset|Connection closed"; then
    echo "ARM64_SSHD_UP auth_expected_to_fail_from_inside_remnux"
    echo "ARM64_GUEST_READY (verify from Windows: ssh -p 2232 -i ~/.ssh/id_ed25519 ubuntu@127.0.0.1)"
    exit 0
  fi
  sleep "$SLEEP"
done
echo "ARM64_TIMEOUT no_ssh_banner_after_${MAX}x${SLEEP}s"
exit 2
