#!/bin/bash
set -Eeuo pipefail
[ $# -eq 1 ] || { echo "Usage: $0 NAME" >&2; exit 2; }
read -r -p "Type instance name '$1' to destroy it: " answer
[ "$answer" = "$1" ] || { echo "Aborted."; exit 1; }
incus delete "$1" --force
