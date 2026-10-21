#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Shell syntax checks"

find "${REPO_ROOT}" \
  -type f \
  \( -name "*.sh" -o -path "*/scripts/*" \) \
  -print0 |
while IFS= read -r -d '' file; do
    bash -n "$file"
done

echo "==> Shellcheck"

find "${REPO_ROOT}" \
  -type f \
  \( -name "*.sh" -o -path "*/scripts/*" \) \
  -print0 |
xargs -0 -r shellcheck

echo "==> YAML validation"

python3 <<'PY'
import pathlib
import yaml

for f in pathlib.Path(".").rglob("*.yml"):
    yaml.safe_load(f.read_text())

for f in pathlib.Path(".").rglob("*.yaml"):
    yaml.safe_load(f.read_text())

print("YAML OK")
PY

echo "==> FAI setup-storage validation"

TMPDIR="$(mktemp -d)"
IMG="${TMPDIR}/disk.img"

cleanup() {
    set +e

    if [[ -n "${LOOPDEV:-}" ]]; then
        losetup -d "$LOOPDEV" 2>/dev/null || true
    fi

    rm -rf "$TMPDIR"
}
trap cleanup EXIT

truncate -s 20G "$IMG"

LOOPDEV="$(losetup --show -fP "$IMG")"

echo "Using loop device: $LOOPDEV"

export disklist="$LOOPDEV"

setup-storage \
    -p \
    -D "$LOOPDEV" \
    -f fai/disk_config/WORKSTATION >/dev/null

echo "FAI storage validation OK"

echo "==> Repository validation successful"