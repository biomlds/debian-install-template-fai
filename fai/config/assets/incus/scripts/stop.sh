#!/bin/sh
set -eu
[ $# -eq 1 ] || { echo "Usage: $0 NAME" >&2; exit 2; }
exec incus stop "$1" --timeout 60
