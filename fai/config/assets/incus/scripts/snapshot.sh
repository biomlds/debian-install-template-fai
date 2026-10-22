#!/bin/bash
set -Eeuo pipefail
if [ $# -lt 1 ] || [ $# -gt 2 ]; then echo "Usage: $0 NAME [SNAPSHOT]" >&2; exit 2; fi
snapshot=${2:-manual-$(date -u +%Y%m%dT%H%M%SZ)}
incus snapshot create "$1" "$snapshot"
printf '%s\n' "$1/$snapshot"
