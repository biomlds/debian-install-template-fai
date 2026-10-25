#!/bin/bash
set +x
set -Eeuo pipefail
command -v cryptsetup >/dev/null || { echo "SKIP cryptsetup unavailable"; exit 0; }
base=/dev/shm
[ -d "$base" ] && [ -w "$base" ] || base=${TMPDIR:-/tmp}
tmp=$(mktemp -d "$base/luks-rotation-test.XXXXXX")
cleanup(){ rm -rf "$tmp"; }
trap cleanup EXIT INT TERM HUP
umask 077
image=$tmp/luks.img
temp=$tmp/temporary.key
perm=$tmp/permanent.key
truncate -s 64M "$image"
printf '%s' 'temporary-test-credential-not-for-production' > "$temp"
printf '%s' 'permanent-test-credential-not-for-production' > "$perm"
cryptsetup luksFormat --type luks2 --pbkdf argon2id --pbkdf-memory 32768 --iter-time 10 --batch-mode --key-file "$temp" "$image" >/dev/null
cryptsetup open --test-passphrase --key-file "$temp" "$image" >/dev/null
slots(){ cryptsetup luksDump --dump-json-metadata "$image" | python3 -c 'import json,sys; print(" ".join(sorted(json.load(sys.stdin)["keyslots"],key=int)))'; }
old=$(slots)
cryptsetup luksAddKey --pbkdf argon2id --pbkdf-memory 32768 --iter-time 10 --key-file "$temp" --new-key-slot 1 "$image" "$perm" >/dev/null
cryptsetup open --test-passphrase --key-slot 1 --key-file "$perm" "$image" >/dev/null
[ "$(set -- $(slots); echo $#)" -ge 2 ]
cryptsetup luksKillSlot --key-file "$perm" "$image" "$old" >/dev/null
if cryptsetup open --test-passphrase --key-file "$temp" "$image" >/dev/null 2>&1; then
    echo "Temporary key still unlocks the LUKS image after slot removal." >&2
    exit 1
fi
cryptsetup open --test-passphrase --key-file "$perm" "$image" >/dev/null
[ "$(set -- $(slots); echo $#)" -ge 1 ]
cryptsetup luksDump --dump-json-metadata "$image" | python3 -c 'import json,sys; assert all(s["kdf"]["type"] == "argon2id" for s in json.load(sys.stdin)["keyslots"].values())'
echo "PASS regular-file LUKS2 rotation; no block device was opened or modified"
