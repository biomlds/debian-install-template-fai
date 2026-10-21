#!/bin/bash
set -Eeuo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHEZMOI_VERSION=2.73.2
YAZI_VERSION=26.9.1
GRUB_BTRFS_VERSION=4.14
GRUB_BTRFS_COMMIT_PREFIX=2fcfbe9
mode=${1:-container}
if [ "$mode" != --native ]; then
    runtime=$(command -v podman || command -v docker || true)
    [ -n "$runtime" ] || { echo "Install podman/docker or run --native in an ephemeral Debian build environment." >&2; exit 1; }
    exec "$runtime" run --rm -v "$repo:/src" -w /src debian:trixie bash tools/build-host-tools.sh --native
fi
[ "$EUID" -eq 0 ] || { echo "--native is intended for a disposable root CI/container environment." >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates cargo git golang-go make pkg-config libssl-dev
out=$repo/fai/config/assets/bin
vendor=$repo/fai/config/assets/vendor
rm -rf "$out" "$vendor/grub-btrfs"
mkdir -p "$out" "$vendor"
GOBIN="$out" go install "github.com/twpayne/chezmoi/v2@v$CHEZMOI_VERSION"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cargo install --locked --root "$tmp/yazi" --version "$YAZI_VERSION" yazi-fm yazi-cli
install -m 0755 "$tmp/yazi/bin/yazi" "$out/yazi"
install -m 0755 "$tmp/yazi/bin/ya" "$out/ya"
git clone --quiet --depth 1 --branch "v$GRUB_BTRFS_VERSION" https://github.com/Antynea/grub-btrfs.git "$tmp/grub-btrfs"
commit=$(git -C "$tmp/grub-btrfs" rev-parse HEAD)
case $commit in "$GRUB_BTRFS_COMMIT_PREFIX"*) ;; *) echo "Unexpected grub-btrfs commit: $commit" >&2; exit 1;; esac
rm -rf "$tmp/grub-btrfs/.git"
cp -a "$tmp/grub-btrfs" "$vendor/grub-btrfs"
sha256sum "$out"/* > "$repo/fai/config/assets/HOST_TOOLS.sha256"
printf 'chezmoi=%s\nyazi=%s\ngrub-btrfs=v%s@%s\n' "$CHEZMOI_VERSION" "$YAZI_VERSION" "$GRUB_BTRFS_VERSION" "$commit" > "$repo/fai/config/assets/HOST_TOOLS.versions"
