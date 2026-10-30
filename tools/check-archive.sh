#!/bin/bash
set -Eeuo pipefail
[ $# -eq 1 ] || { echo "Usage: $0 ARCHIVE.zip" >&2; exit 2; }
archive=$1
[ -s "$archive" ] || { echo "Archive missing." >&2; exit 1; }
mapfile -t entries < <(unzip -Z1 "$archive")
((${#entries[@]} > 40)) || { echo "Archive unexpectedly small." >&2; exit 1; }
for entry in "${entries[@]}"; do
  case $entry in
    /*|*'../'*|*'/..') echo "Unsafe archive path: $entry" >&2; exit 1;;
    *config.yaml|*.kdbx|*luks.bootstrap.passphrase|*provision.password.hash|*__pycache__*|*.pyc)
      echo "Private/generated file in archive: $entry" >&2; exit 1;;
  esac
done
root=${entries[0]%%/*}
for required in README.md Makefile fai/config/assets/workstation/kdbx.py fai/config/disk_config/LUKS_BTRFS fai/config/hooks/partition.WORKSTATION.sh fai/config/assets/disk-selection/disk_selector.py tests/test-disk-selector.py tools/validate.sh docs/SECURITY.md docs/VALIDATION.md .github/workflows/build-iso.yml; do
  found=0
  for entry in "${entries[@]}"; do
    if [ "$entry" = "$root/$required" ]; then found=1; break; fi
  done
  [ "$found" -eq 1 ] || { echo "Archive missing $required" >&2; exit 1; }
done
unzip -tq "$archive" >/dev/null
echo "PASS archive inventory and ZIP integrity (${#entries[@]} entries)"
