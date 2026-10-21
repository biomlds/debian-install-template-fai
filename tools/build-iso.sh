#!/bin/bash
set -Eeuo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
out=${1:-$repo/build/debian-fai-workstation.iso}
[ "$EUID" -eq 0 ] || { echo "Run in a disposable Debian trixie root environment." >&2; exit 1; }
for tool in "$repo/fai/config/assets/bin/chezmoi" "$repo/fai/config/assets/bin/yazi" "$repo/fai/config/assets/bin/ya"; do
    [ -x "$tool" ] || { echo "Missing built host tool: $tool; run tools/build-host-tools.sh first." >&2; exit 1; }
done
[ -f "$repo/fai/config/assets/vendor/grub-btrfs/Makefile" ] || {
    echo "Missing pinned grub-btrfs source; run tools/build-host-tools.sh first." >&2; exit 1;
}
install -d /etc/fai/apt /srv/fai "$repo/build"
install -m 0644 "$repo/server/NFSROOT" /etc/fai/NFSROOT
install -m 0644 "$repo/server/sources.list" /etc/fai/apt/sources.list
install -m 0644 "$repo/server/nfsroot.conf.example" /etc/fai/nfsroot.conf
install -m 0644 "$repo/server/fai.conf.example" /etc/fai/fai.conf
rsync -a --delete "$repo/fai/config/" /srv/fai/config/
fai-make-nfsroot -v
fai-cd -M "$out"
sha256sum "$out" > "$out.sha256"
# Public ISO policy: no input values, private keys, password hashes, or bootstrap media payloads.
scan=$(mktemp -d); trap 'rm -rf "$scan"' EXIT
xorriso -osirrox on -indev "$out" -extract / "$scan/root" >/dev/null 2>&1
if find "$scan/root" -type f \( -name 'luks.bootstrap.passphrase' -o -name 'provision.password.hash' -o -name '*.kdbx' -o -name 'config.yaml' \) -print | grep -q .; then
    echo "Private input file found in ISO." >&2; exit 1
fi
if grep -RIE 'BEGIN (OPENSSH|RSA|EC|DSA) PRIVATE KEY' "$scan/root"; then
    echo "Private key material found in ISO." >&2; exit 1
fi
