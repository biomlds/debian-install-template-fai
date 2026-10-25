#!/bin/bash
set -Eeuo pipefail
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../fai/config" && pwd)
destination=${1:-/srv/fai/config}
[ "$EUID" -eq 0 ] || { echo "Run as root." >&2; exit 1; }
install -d -m 0755 "$destination"
rsync -a --delete --chown=root:root --exclude __pycache__ --exclude '*.pyc' "$source_dir/" "$destination/"
find "$destination" -type d -exec chmod 0755 {} +
find "$destination/class" "$destination/hooks" "$destination/scripts" -type f -name '[0-9]*' -exec chmod 0755 {} +
echo "Installed FAI config space at $destination"
