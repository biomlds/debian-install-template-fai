#!/bin/bash
set -Eeuo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHEZMOI_VERSION=2.73.2
CHEZMOI_GO_VERSION=1.26.0
CHEZMOI_COMMIT_PREFIX=54c760f1c2e9f6612d8615bef2e50abaf8fa5ef7
YAZI_VERSION=26.9.1
YAZI_COMMIT_PREFIX=8dd895c695a5950330c2623eb43debf323b60654
YAZI_RUST_VERSION=1.95.0
RUSTUP_VERSION=1.29.2
RUSTUP_INIT_SHA256=5be191e8c70a5007074254cb74d78dbfdd25cd5a61c27de7b8e5410122ec24f4
GRUB_BTRFS_VERSION=4.14
GRUB_BTRFS_COMMIT_PREFIX=2fcfbe9
mode=${1:-container}
if [ "$mode" != --native ]; then
    runtime=$(command -v podman || command -v docker || true)
    [ -n "$runtime" ] || { echo "Install podman/docker or run --native in an ephemeral Debian build environment." >&2; exit 1; }
    exec "$runtime" run --rm -v "$repo:/src" -w /src debian:trixie bash tools/build-host-tools.sh --native
fi
[ "$EUID" -eq 0 ] || { echo "--native is intended for a disposable root CI/container environment." >&2; exit 1; }
[ "$(uname -m)" = x86_64 ] || { echo "Host tool builds require an x86_64 host." >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends build-essential ca-certificates curl git golang-go make pkg-config libssl-dev
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
git clone --quiet --depth 1 --branch "v$YAZI_VERSION" https://github.com/sxyazi/yazi.git "$tmp/yazi"
yazi_commit=$(git -C "$tmp/yazi" rev-parse HEAD)
case $yazi_commit in
    "$YAZI_COMMIT_PREFIX"*) ;;
    *) echo "Unexpected yazi commit: $yazi_commit" >&2; exit 1 ;;
esac
export RUSTUP_HOME="$tmp/rustup" CARGO_HOME="$tmp/cargo"
rustup_init="$tmp/rustup-init"
curl --proto '=https' --tlsv1.2 -fsSL -o "$rustup_init" \
    "https://static.rust-lang.org/rustup/archive/$RUSTUP_VERSION/x86_64-unknown-linux-gnu/rustup-init"
printf '%s  %s\n' "$RUSTUP_INIT_SHA256" "$rustup_init" | sha256sum -c -
chmod +x "$rustup_init"
"$rustup_init" -y --no-modify-path --profile minimal --default-toolchain "$YAZI_RUST_VERSION"
(
    cd "$tmp/yazi"
    "$CARGO_HOME/bin/cargo" build --release --locked -p yazi-fm -p yazi-cli
)
install -m 0755 "$tmp/yazi/target/release/yazi" "$out/yazi"
install -m 0755 "$tmp/yazi/target/release/ya" "$out/ya"
git clone --quiet --depth 1 --branch "v$GRUB_BTRFS_VERSION" https://github.com/Antynea/grub-btrfs.git "$tmp/grub-btrfs"
grub_btrfs_commit=$(git -C "$tmp/grub-btrfs" rev-parse HEAD)
case $grub_btrfs_commit in "$GRUB_BTRFS_COMMIT_PREFIX"*) ;; *) echo "Unexpected grub-btrfs commit: $grub_btrfs_commit" >&2; exit 1;; esac
rm -rf "$tmp/grub-btrfs/.git"
cp -a "$tmp/grub-btrfs" "$vendor/grub-btrfs"
(cd "$repo" && sha256sum fai/config/assets/bin/* > fai/config/assets/HOST_TOOLS.sha256)
printf 'chezmoi=%s\nyazi=%s\ngrub-btrfs=v%s@%s\n' "$CHEZMOI_VERSION" "$YAZI_VERSION" "$GRUB_BTRFS_VERSION" "$grub_btrfs_commit" > "$repo/fai/config/assets/HOST_TOOLS.versions"
