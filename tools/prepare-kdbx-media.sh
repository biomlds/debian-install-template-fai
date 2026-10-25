#!/bin/bash
set +x
set -Eeuo pipefail
umask 077
if [ "$EUID" -ne 0 ] || [ "$#" -ne 2 ]; then echo "Usage: sudo $0 EXISTING_EXT4_PARTITION PRIVATE_DATABASE.kdbx" >&2; exit 2; fi
device=$(readlink -f "$1")
if [ ! -b "$device" ] || [ "$(blkid -s TYPE -o value "$device")" != ext4 ]; then
    echo 'Require an existing ext4 partition; this helper never formats.' >&2; exit 1;
fi
if [ ! -f "$2" ] || [ -L "$2" ]; then echo 'Unsafe/missing database.' >&2; exit 1; fi
if findmnt -rn -S "$device" >/dev/null; then echo 'Unmount the partition first.' >&2; exit 1; fi
mnt=$(mktemp -d)
mounted=0
cleanup(){
    if [ "$mounted" = 1 ]; then umount "$mnt"; fi
    rmdir "$mnt"
}
trap cleanup EXIT
mount -o rw,nosuid,nodev,noexec "$device" "$mnt"
mounted=1
if [ -e "$mnt/Workstation.kdbx" ] || [ -L "$mnt/Workstation.kdbx" ]; then
    echo 'Database already exists; manage/replace it explicitly.' >&2; exit 1;
fi
install -m 0600 -o root -g root "$2" "$mnt/Workstation.kdbx"
sync -f "$mnt/Workstation.kdbx"
e2label "$device" WORKSTATION-KDBX
echo 'KDBX media prepared. Keep a second offline copy; attach only when needed.'
