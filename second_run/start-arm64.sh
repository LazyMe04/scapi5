#!/bin/bash
# start-arm64.sh - Boot Ubuntu 24.04 ARM64 malware test VM under TCG emulation.
# Run 2, direct-kernel mode.
#
# WHY DIRECT KERNEL BOOT:
# The noble cloud image uses a hybrid layout: partition 15 is a 104MB fat32 ESP holding only
# shim/grub (no kernel), partition 16 "bls_boot" holds the real vmlinuz+initrd, and the ext4
# root (partition 1) has an EMPTY /boot and no /grub/grub.cfg. Firmware boots shim, shim boots
# grub, grub searches root for $prefix/grub/grub.cfg, finds nothing, and retries forever at
# 100% CPU. That is what stalled run 1 and the first run-2 attempt. Bypassing firmware
# entirely with -kernel/-initrd sidesteps the broken chain and gives us a kernel cmdline.
#
# The kernel/initrd are extracted copies of the base image's own files. Re-extract with
# extract-kernel.sh if the base image is ever replaced.

set -u
BASE="$HOME/arm64-vm"
IMG_DIR="$BASE/images"
KERNEL_DIR="$BASE/kernel"
DISK="${IMG_DIR}/ubuntu-arm64-malware-test.qcow2"
SEED="${BASE}/seed/cloud-init-seed.iso"
KERNEL="${KERNEL_DIR}/vmlinuz"
INITRD="${KERNEL_DIR}/initrd.img"
LOG="${BASE}/logs/console.log"
PIDFILE="${BASE}/qemu.pid"

# Single instance guard
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Already running (PID $(cat "$PIDFILE")). Use stop-arm64.sh first."
  exit 1
fi

for f in "$DISK" "$SEED" "$KERNEL" "$INITRD"; do
  if [ ! -f "$f" ]; then
    echo "Missing required file: $f"
    exit 1
  fi
done

# Host port for the guest SSH forward. Bound on REMnux loopback only.
GUEST_SSH_PORT="${GUEST_SSH_PORT:-2222}"

# Console on ttyAMA0 (the virt machine PL011 UART) so boot output is visible.
# smp 1 by default: under TCG, smp 2 on a 2-vCPU guest starves REMnux sshd completely.
GUEST_SMP="${GUEST_SMP:-1}"

: > "$LOG"
echo "Starting ARM64 VM (direct kernel). Console log: $LOG"
echo "Guest SSH: REMnux localhost:${GUEST_SSH_PORT}  (user: ubuntu)"
echo "From Windows: ssh -N -f -L 2232:127.0.0.1:${GUEST_SSH_PORT} remnux"
echo "             ssh -p 2232 ubuntu@127.0.0.1"
echo "TCG software emulation, smp=${GUEST_SMP}. Expect 5-20 min to first login."
echo

qemu-system-aarch64 \
  -M virt \
  -cpu max \
  -smp "${GUEST_SMP}" \
  -m 2048 \
  -kernel "${KERNEL}" \
  -initrd "${INITRD}" \
  -append "root=LABEL=cloudimg-rootfs rw console=ttyAMA0,115200 earlycon=pl011,0x9000000 net.ifnames=0" \
  -drive if=none,id=disk0,file="${DISK}",format=qcow2,cache=writeback \
  -device virtio-blk-pci,drive=disk0,serial=rootdisk \
  -drive if=none,id=seed0,file="${SEED}",format=raw,readonly=on \
  -device virtio-blk-pci,drive=seed0,serial=cidata \
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:${GUEST_SSH_PORT}-:22 \
  -device virtio-net-pci,netdev=net0 \
  -display none \
  -serial file:"${LOG}" \
  -pidfile "${PIDFILE}" \
  -no-reboot &

QEMU_PID=$!
sleep 3
if kill -0 "$QEMU_PID" 2>/dev/null; then
  echo "QEMU running, PID $QEMU_PID"
else
  echo "QEMU exited immediately. Tail of console log:"
  tail -30 "$LOG"
  exit 1
fi
