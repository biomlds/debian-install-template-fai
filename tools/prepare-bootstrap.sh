#!/bin/bash
set +x
set -Eeuo pipefail
umask 077
usage(){ echo "Usage: sudo $0 /dev/disk/by-id/REMOVABLE_PARTITION [provision.pub]" >&2; }
[ $# -ge 1 ] && [ $# -le 2 ] || { usage; exit 2; }
[ "$EUID" -eq 0 ] || { echo "Run as root." >&2; exit 1; }
device=$(readlink -f "$1")
[ -b "$device" ] || { echo "Not a block device." >&2; exit 1; }
findmnt -rn -S "$device" >/dev/null && { echo "Device is mounted; unmount it first." >&2; exit 1; }
[ "$(blkid -s TYPE -o value "$device")" = ext4 ] || { echo "Use an existing ext4 filesystem." >&2; exit 1; }
e2label "$device" FAI-BOOTSTRAP
mnt=$(mktemp -d)
cleanup(){ unset account1 account2 luks1 luks2; umount "$mnt" 2>/dev/null || true; rmdir "$mnt" 2>/dev/null || true; }
trap cleanup EXIT INT TERM HUP
mount -o rw,nosuid,nodev,noexec "$device" "$mnt"
read -rsp 'Temporary provisioning-account password: ' account1; echo
read -rsp 'Repeat temporary account password: ' account2; echo
[ "$account1" = "$account2" ] || { echo "Account passwords differ." >&2; exit 1; }
[ ${#account1} -ge 12 ] || { echo "Use at least 12 characters." >&2; exit 1; }
printf '%s' "$account1" | openssl passwd -6 -stdin > "$mnt/provision.password.hash"
unset account1 account2
read -rsp 'Temporary LUKS bootstrap passphrase: ' luks1; echo
read -rsp 'Repeat temporary LUKS passphrase: ' luks2; echo
[ "$luks1" = "$luks2" ] || { echo "LUKS passphrases differ." >&2; exit 1; }
[ ${#luks1} -ge 16 ] || { echo "Use at least 16 characters." >&2; exit 1; }
printf '%s' "$luks1" > "$mnt/luks.bootstrap.passphrase"
unset luks1 luks2
if [ $# -eq 2 ]; then
    [ -s "$2" ] || { echo "Public key not found." >&2; exit 1; }
    install -m 0600 "$2" "$mnt/provision.authorized_keys"
fi
chmod 0600 "$mnt"/*
sync
umount "$mnt"; rmdir "$mnt"; trap - EXIT INT TERM HUP
echo "FAI-BOOTSTRAP prepared. Keep it offline, attach only during FAI, and remove before first boot."
