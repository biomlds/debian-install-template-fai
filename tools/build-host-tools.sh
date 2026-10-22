#!/bin/bash
set -Eeuo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHEZMOI_VERSION=2.73.2
CHEZMOI_GO_VERSION=1.26.0
CHEZMOI_COMMIT_PREFIX=54c760f1c2e9f6612d8615bef2e50abaf8fa5ef7
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
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git clone --quiet --depth 1 --branch "v$CHEZMOI_VERSION" https://github.com/twpayne/chezmoi.git "$tmp/chezmoi"
chezmoi_commit=$(git -C "$tmp/chezmoi" rev-parse HEAD)
case $chezmoi_commit in
    "$CHEZMOI_COMMIT_PREFIX"*) ;;
    *) echo "Unexpected chezmoi commit: $chezmoi_commit" >&2; exit 1 ;;
esac
(
    cd "$tmp/chezmoi"
    GOTOOLCHAIN="go$CHEZMOI_GO_VERSION" CGO_ENABLED=0 go build \
        -trimpath -buildvcs=false \
        -ldflags "-s -w -X main.version=$CHEZMOI_VERSION -X main.commit=$chezmoi_commit -X main.builtBy=source" \
        -o "$out/chezmoi" .
)
cargo install --locked --root "$tmp/yazi" --version "$YAZI_VERSION" yazi-fm yazi-cli
install -m 0755 "$tmp/yazi/bin/yazi" "$out/yazi"
install -m 0755 "$tmp/yazi/bin/ya" "$out/ya"
git clone --quiet --depth 1 --branch "v$GRUB_BTRFS_VERSION" https://github.com/Antynea/grub-btrfs.git "$tmp/grub-btrfs"
grub_btrfs_commit=$(git -C "$tmp/grub-btrfs" rev-parse HEAD)
case $grub_btrfs_commit in "$GRUB_BTRFS_COMMIT_PREFIX"*) ;; *) echo "Unexpected grub-btrfs commit: $grub_btrfs_commit" >&2; exit 1;; esac
rm -rf "$tmp/grub-btrfs/.git"
cp -a "$tmp/grub-btrfs" "$vendor/grub-btrfs"
(cd "$repo" && sha256sum fai/config/assets/bin/* > fai/config/assets/HOST_TOOLS.sha256)
printf 'chezmoi=%s\nyazi=%s\ngrub-btrfs=v%s@%s\n' "$CHEZMOI_VERSION" "$YAZI_VERSION" "$GRUB_BTRFS_VERSION" "$grub_btrfs_commit" > "$repo/fai/config/assets/HOST_TOOLS.versions"
