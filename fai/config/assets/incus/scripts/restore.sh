#!/bin/bash
set -Eeuo pipefail
[ $# -eq 2 ] || { echo "Usage: $0 NAME SNAPSHOT" >&2; exit 2; }
incus stop "$1" --force 2>/dev/null || true
incus restore "$1" "$2"
incus start "$1"
