#!/bin/bash
set -Eeuo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
selector=$repo/fai/config/assets/disk-selection/disk_selector.py
cat <<'NOTICE'
This is the same interactive disk discovery and safety filter used by FAI.
It is intended to run inside the booted FAI environment. It will ask for an OS
and bootloader disk, display existing layout, and require a PREVIEW token.
No selection is persisted, setup-storage is not invoked, and no disk is written.
NOTICE
exec python3 "$selector" select --dry-run "${@}"
