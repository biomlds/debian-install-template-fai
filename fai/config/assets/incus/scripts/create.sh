#!/bin/bash
set -Eeuo pipefail
usage(){ echo "Usage: $0 NAME {dev|bio|ai} [--cpu N] [--memory 8GiB] [--disk 40GiB]" >&2; }
[ $# -ge 2 ] || { usage; exit 2; }
name=$1; role=$2; shift 2
case $role in dev|bio|ai) ;; *) usage; exit 2;; esac
cpu=4; memory=8GiB; disk=40GiB
[ "$role" != ai ] || { cpu=8; memory=16GiB; disk=80GiB; }
while [ $# -gt 0 ]; do
  case $1 in
    --cpu) cpu=$2; shift 2;; --memory) memory=$2; shift 2;; --disk) disk=$2; shift 2;; *) usage; exit 2;;
  esac
done
[[ $name =~ ^[a-z][a-z0-9-]{0,30}$ ]] || { echo "Invalid instance name." >&2; exit 1; }
incus info "$name" >/dev/null 2>&1 && { echo "Instance exists: $name" >&2; exit 1; }
base=/usr/local/share/workstation-bootstrap/incus/templates/$role
incus launch images:debian/13/cloud "$name" --vm -p default -c limits.cpu="$cpu" -c limits.memory="$memory"
incus config device override "$name" root size="$disk"
for _ in $(seq 1 120); do incus exec "$name" -- true >/dev/null 2>&1 && break; sleep 2; done
incus exec "$name" -- cloud-init status --wait
incus file push "$base/bootstrap.sh" "$name/root/bootstrap.sh" --mode=0755
incus file push "$base/mise.toml" "$name/root/mise.toml" --mode=0644
incus exec "$name" -- /root/bootstrap.sh /root/mise.toml
printf 'Created VM %s (%s): %s CPU, %s RAM, %s disk.\n' "$name" "$role" "$cpu" "$memory" "$disk"
