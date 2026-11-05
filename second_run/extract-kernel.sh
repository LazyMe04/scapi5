#!/bin/bash
# extract-kernel.sh - Pull vmlinuz + initrd out of the ARM64 base cloud image.
#
# WHY THIS EXISTS:
# The noble ARM64 cloud image is a hybrid image. Partitions:
#   p15  104MB  fat32  ESP  - shim + grub ONLY, no kernel
#   p16  968MB  ext4   bls_boot - the real vmlinuz + initrd
#   p1   2683MB ext4   root - /boot is EMPTY, no /grub/grub.cfg
# The firmware boots shim, shim boots grub, grub searches root for $prefix/grub/grub.cfg,
# finds nothing, and spins at 100% CPU forever. start-arm64.sh bypasses this with
# -kernel/-initrd, which is why it needs the kernel extracted first.
#
# qemu-nbd does not work inside the REMnux VM (no /dev/nbd*, the nbd module is not loaded
# and this is already a nested guest), so the image is converted to raw and loop-mounted.

set -eu
BASE="$HOME/arm64-vm"
IMG="${BASE}/images/ubuntu-24.04-server-cloudimg-arm64.img"
RAW="/tmp/base-arm64-extract.raw"
MNT="/tmp/mnt-bls"
KERNEL_OUT="${BASE}/kernel"

if [ ! -f "$IMG" ]; then
  echo "Base image not found: $IMG"
  exit 1
fi

echo "Converting to raw (takes a minute)..."
rm -f "$RAW"
sudo qemu-img convert -O raw -S 4k "$IMG" "$RAW"

LOOP="$(sudo losetup -fP --show "$RAW")"
echo "Loop device: $LOOP"

cleanup() {
  sudo umount "$MNT" 2>/dev/null || true
  sudo losetup -d "$LOOP" 2>/dev/null || true
  sudo rm -f "$RAW"
  rmdir "$MNT" 2>/dev/null || true
}
trap cleanup EXIT

sudo mkdir -p "$MNT"
sudo mount "${LOOP}p16" "$MNT"
echo "Mounted bls_boot. Contents:"
sudo ls -la "$MNT" | head -12

KVER="$(sudo ls "$MNT" | grep -o 'vmlinuz-[0-9].*' | head -1)"
if [ -z "$KVER" ]; then
  echo "Could not determine kernel version from bls_boot"
  exit 1
fi
echo "Kernel version: $KVER"

sudo mkdir -p "$KERNEL_OUT"
sudo cp "${MNT}/vmlinuz-${KVER#vmlinuz-}" "$KERNEL_OUT/vmlinuz"
sudo cp "${MNT}/initrd.img-${KVER#vmlinuz-}" "$KERNEL_OUT/initrd.img"
sudo chown "$(id -u):$(id -g)" "$KERNEL_OUT/vmlinuz" "$KERNEL_OUT/initrd.img"
chmod 644 "$KERNEL_OUT/vmlinuz" "$KERNEL_OUT/initrd.img"

echo "Extracted to $KERNEL_OUT:"
ls -la "$KERNEL_OUT"
echo "Done."
