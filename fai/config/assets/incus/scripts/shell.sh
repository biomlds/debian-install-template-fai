#!/bin/sh
set -eu
[ $# -eq 1 ] || { echo "Usage: $0 NAME" >&2; exit 2; }
exec incus exec "$1" -- su - dev
