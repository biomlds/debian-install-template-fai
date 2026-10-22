#!/bin/bash
set +x
set -Eeuo pipefail
umask 077
usage(){ echo "Usage: sudo $0 /dev/disk/by-id/REMOVABLE_PARTITION [provision.pub]" >&2; }
if [ $# -lt 1 ] || [ $# -gt 2 ]; then usage; exit 2; fi
[ "$EUID" -eq 0 ] || { echo "Run as root." >&2; exit 1; }
device=$(readlink -f "$1")
[ -b "$device" ] || { echo "Not a block device." >&2; exit 1; }
findmnt -rn -S "$device" >/dev/null && { echo "Device is mounted; unmount it first." >&2; exit 1; }
[ "$(blkid -s TYPE -o value "$device")" = ext4 ] || { echo "Use an existing ext4 filesystem." >&2; exit 1; }

mnt=$(mktemp -d)
mounted=0
prepared=0
cleanup(){
    status=$?
    set +e
    if [ "$mounted" -eq 1 ]; then
        if [ "$prepared" -ne 1 ]; then
            rm -f "$mnt/provision.password.hash" "$mnt/luks.bootstrap.passphrase" "$mnt/provision.authorized_keys"
        fi
        sync
        umount "$mnt" 2>/dev/null
    fi
    rmdir "$mnt" 2>/dev/null
    unset account1 account2 luks1 luks2
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

mount -o rw,nosuid,nodev,noexec "$device" "$mnt"
mounted=1
link=$(find "$mnt" -xdev -type l -print -quit)
[ -z "$link" ] || { echo "Refusing symlink on bootstrap media: $link" >&2; exit 1; }

write_file(){
    local dest=$1 temporary
    temporary=$(mktemp "$mnt/.fai-bootstrap.XXXXXX")
    chmod 0600 "$temporary"
    cat > "$temporary"
    chmod 0600 "$temporary"
    mv -f "$temporary" "$dest"
}

read -rsp 'Temporary provisioning-account password: ' account1; echo
read -rsp 'Repeat temporary account password: ' account2; echo
[ "$account1" = "$account2" ] || { echo "Account passwords differ." >&2; exit 1; }
[ ${#account1} -ge 12 ] || { echo "Use at least 12 characters." >&2; exit 1; }
account_hash=$(printf '%s' "$account1" | openssl passwd -6 -stdin)
unset account1 account2
printf '%s' "$account_hash" | write_file "$mnt/provision.password.hash"
unset account_hash

read -rsp 'Temporary LUKS bootstrap passphrase: ' luks1; echo
read -rsp 'Repeat temporary LUKS passphrase: ' luks2; echo
[ "$luks1" = "$luks2" ] || { echo "LUKS passphrases differ." >&2; exit 1; }
[ ${#luks1} -ge 16 ] || { echo "Use at least 16 characters." >&2; exit 1; }
printf '%s' "$luks1" | write_file "$mnt/luks.bootstrap.passphrase"
unset luks1 luks2

if [ $# -eq 2 ]; then
    if [ ! -f "$2" ] || [ ! -s "$2" ]; then echo "Public key not found." >&2; exit 1; fi
    write_file "$mnt/provision.authorized_keys" < "$2"
fi

chmod 0600 "$mnt/provision.password.hash" "$mnt/luks.bootstrap.passphrase"
[ $# -ne 2 ] || chmod 0600 "$mnt/provision.authorized_keys"
sync
e2label "$device" FAI-BOOTSTRAP
prepared=1
umount "$mnt"
mounted=0
rmdir "$mnt"
trap - EXIT INT TERM HUP
echo "FAI-BOOTSTRAP prepared. Keep it offline, attach only during FAI, and remove before first boot."
