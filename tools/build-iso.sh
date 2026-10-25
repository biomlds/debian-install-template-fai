#!/bin/bash
set -Eeuo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
out=${1:-$repo/build/debian-fai-workstation.iso}
[ "$EUID" -eq 0 ] || { echo "Run in a disposable Debian trixie root environment." >&2; exit 1; }
for tool in "$repo/fai/config/assets/bin/chezmoi" "$repo/fai/config/assets/bin/yazi" "$repo/fai/config/assets/bin/ya" "$repo/fai/config/assets/bin/sbctl"; do
    [ -x "$tool" ] || { echo "Missing built host tool: $tool; run tools/build-host-tools.sh first." >&2; exit 1; }
done
python3 "$repo/tools/scan-public.py" "$repo/fai/config"
(cd "$repo" && sha256sum -c fai/config/assets/HOST_TOOLS.sha256)
install -d /etc/fai/apt /srv/fai "$repo/build" "$(dirname "$out")"
install -m 0644 "$repo/server/NFSROOT" /etc/fai/NFSROOT
install -m 0644 "$repo/server/sources.list" /etc/fai/apt/sources.list
install -m 0644 "$repo/server/nfsroot.conf.example" /etc/fai/nfsroot.conf
install -m 0644 "$repo/server/fai.conf.example" /etc/fai/fai.conf
rsync -a --delete --exclude __pycache__ --exclude '*.pyc' "$repo/fai/config/" /srv/fai/config/
# Use a fresh NFSROOT by default; reuse must be explicit and is not used by CI.
if [ "${FAI_REUSE_NFSROOT:-0}" = 1 ]; then
    fai-make-nfsroot -v -k
else
    fai-make-nfsroot -v -f
fi
chroot /srv/fai/nfsroot keepassxc-cli --version
# Verify shared-library compatibility of the vendored signer inside NFSROOT.
install -m 0755 "$repo/fai/config/assets/bin/sbctl" /srv/fai/nfsroot/usr/local/bin/sbctl
chroot /srv/fai/nfsroot /usr/local/bin/sbctl version
# SSH host identity is generated on each installer boot, never shared by ISOs.
rm -f /srv/fai/nfsroot/etc/ssh/ssh_host_*
install -d -m 0755 /srv/fai/nfsroot/etc/systemd/system/fai.service.d
cat > /srv/fai/nfsroot/etc/systemd/system/fai.service.d/10-ssh-host-keys.conf <<'UNIT'
[Service]
ExecStartPre=/usr/bin/ssh-keygen -A
UNIT
fai-cd -M "$out"
(cd "$(dirname "$out")" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256")
# Public ISO policy: no input values, private keys, password hashes, or bootstrap media payloads.
scan=$(mktemp -d); trap 'rm -rf "$scan"' EXIT
xorriso -osirrox on -indev "$out" -extract / "$scan/root" >/dev/null 2>&1
# FAI 6.4 can nest LiveOS/ext3fs.img inside squashfs.img. Inspect both layers
# by filesystem magic, including direct-root squashfs layouts, and fail closed.
python3 "$repo/tools/scan-public.py" --images "$scan/root"
