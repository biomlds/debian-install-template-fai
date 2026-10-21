#!/bin/bash
set -Eeuo pipefail
[ $# -ge 1 ] && [ $# -le 2 ] || { echo "Usage: $0 NAME [SNAPSHOT]" >&2; exit 2; }
snapshot=${2:-manual-$(date -u +%Y%m%dT%H%M%SZ)}
incus snapshot create "$1" "$snapshot"
printf '%s\n' "$1/$snapshot"
