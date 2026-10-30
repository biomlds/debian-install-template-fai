#!/bin/bash
# shellcheck disable=SC2317  # abort_partition runs from the EXIT trap.
# The .sh suffix makes FAI source this hook, so die() is available and a failed
# preflight/selection stops the installer. A plain hook's exit status is only
# logged by FAI, which then runs its own default setup-storage and can partition
# the wrong disk (for example the KDBX USB).
partition_workstation() {
    set -Eeuo pipefail
    umask 077
    : "${FAI:?FAI config-space path is required}"
    : "${LOGDIR:=/tmp/fai}"
    : "${WORKSTATION_SECRETS:=/run/fai/workstation-secrets}"
    selector=$FAI/assets/disk-selection/disk_selector.py
    selection=$LOGDIR/disk-selection.json
    selection_env=$LOGDIR/disk-selection.env
    config=$FAI/disk_config/LUKS_BTRFS
    install -d -m 0700 "$LOGDIR"
    : "${target:=/target}"

    # A previous aborted run leaves /target (and its subvolumes) mounted. A new
    # setup-storage then regenerates the LUKS key while the old mapper stays
    # open, so no key unlocks and findmnt/lsblk see inconsistent state. Require
    # a fresh boot instead of installing over stale mounts.
    if mountpoint -q "$target" || mountpoint -q "$target/boot"; then
        echo "Target is already mounted from an earlier attempt. Reboot the installer before retrying." >&2
        exit 1
    fi

    # Even though the sourced hook stops FAI explicitly, keep the task suppressed
    # and leave a marker so class/20-bootstrap can reset state after an abort.
    abort_partition(){
        status=$?
        if [ "$status" -ne 0 ]; then
            touch "$LOGDIR/skip.partition" "$LOGDIR/workstation-partition-failed"
            python3 "$FAI/assets/workstation/kdbx.py" cleanup || true
            echo "Partitioning aborted; FAI default partitioning suppressed." >&2
        fi
    }
    trap abort_partition EXIT

    # The selector is executed explicitly through python3 so a checkout that lost
    # the executable bit cannot silently skip the password prompt and selection.
    [ -r "$selector" ] || { echo "Disk selector is missing: $selector" >&2; exit 1; }
    [ -r "$config" ] || { echo "Disk configuration is missing: $config" >&2; exit 1; }

    # Never permit a failed class script to fall through to destructive selection.
    if [ "$(uname -m)" != x86_64 ] || [ ! -d /sys/firmware/efi ]; then
        echo "amd64 UEFI is required." >&2; exit 1;
    fi
    python3 "$FAI/assets/workstation/kdbx.py" preflight
    if [ ! -s "$WORKSTATION_SECRETS/identity.json" ] || [ ! -s "$WORKSTATION_SECRETS/luks" ]; then
        echo "Workstation secrets were not extracted; aborting before partitioning." >&2; exit 1;
    fi

    # This hook replaces FAI's standard partition task so selection can happen before
    # setup-storage. It fails closed on missing TTY, cancellation, EOF, or any check.
    python3 "$selector" select --tty /dev/console --output "$selection" --env-output "$selection_env" \
        2>&1 | tee "$LOGDIR/disk-selection.log"

    # The selector already revalidates once after persistence. Repeat it as the last
    # operation before setup-storage to minimize the selection-to-destruction race.
    python3 "$selector" revalidate --selection "$selection" \
        2>&1 | tee -a "$LOGDIR/disk-selection.log"

    # shellcheck disable=SC1090
    source "$selection_env"
    # setup-storage's disklist/-D contract uses bare kernel names (sdb, nvme0n1),
    # while bootloader variables intentionally retain absolute /dev paths.
    # Accept one legacy /dev/ prefix defensively, then fail closed on any path.
    disklist=${disklist#/dev/}
    case "$disklist" in
        ""|*/*) echo "Invalid setup-storage disk name: $disklist" >&2; exit 1 ;;
    esac
    case "${BOOT_DEVICE:-}:${PHYSICAL_BOOT_DEVICES:-}:${FAI_SELECTED_BOOT_KERNEL:-}" in
        /dev/*:/dev/*:/dev/*) ;;
        *) echo "Invalid selected boot-device path." >&2; exit 1 ;;
    esac
    export disklist BOOT_DEVICE PHYSICAL_BOOT_DEVICES FAI_SELECTED_BOOT_KERNEL

    device=/dev/$disklist
    [ -b "$device" ] || { echo "Selected disk does not exist: $device" >&2; exit 1; }

    # Belt and braces: never partition the filesystem this installer unlocked.
    media_source=$(findmnt -rn -o SOURCE --target /run/fai/kdbx 2>/dev/null || true)
    if [ -n "$media_source" ] && [ "$(readlink -f "$device")" = "$(readlink -f "$media_source")" ]; then
        echo "Selected disk is the mounted KDBX media; refusing to partition it." >&2; exit 1
    fi

    # LUKS_BTRFS needs a 2G ESP plus an 8G (growable) root. Refuse a disk that
    # cannot hold the layout before setup-storage starts writing.
    size=$(blockdev --getsize64 "$device")
    minimum=$((11 * 1024 * 1024 * 1024))
    [ "$size" -ge "$minimum" ] || {
        echo "Selected disk $device is $size bytes; at least 11 GiB is required (2 GiB ESP + 8 GiB root); 16 GiB or more is recommended." >&2
        exit 1
    }

    setup-storage -X -f "$config" -D "$disklist" -L "$LOGDIR"
    [ -s "$LOGDIR/disk_var.sh" ] || { echo "setup-storage did not create disk_var.sh" >&2; exit 1; }

    # 10-luks-key rewrites crypttab to its final "none" form, so a retried or
    # re-run configure would lose setup-storage's temporary key path. Copy the
    # key BYTES; storing the path text here makes cryptsetup use that text as
    # the passphrase and no slot ever unlocks.
    setup_key_path=$(awk 'NR==1 {print $3}' "$LOGDIR/crypttab")
    if [ -z "$setup_key_path" ] || [ "$setup_key_path" = "none" ]; then
        echo "crypttab does not reference a setup-storage LUKS key." >&2
        exit 1
    fi
    [ -s "$setup_key_path" ] || {
        echo "setup-storage LUKS key file is missing: $setup_key_path" >&2
        exit 1
    }
    install -m 0600 "$setup_key_path" "$LOGDIR/luks-setup-key"

    # setup-storage derives these values from disk1; make the independently selected
    # bootloader target explicit for every later script. Split disks are rejected.
    sed -i '/^BOOT_DEVICE=/d;/^PHYSICAL_BOOT_DEVICES=/d' "$LOGDIR/disk_var.sh"
    printf 'BOOT_DEVICE=%q\nPHYSICAL_BOOT_DEVICES=%q\n' \
        "$FAI_SELECTED_BOOT_KERNEL" "$FAI_SELECTED_BOOT_KERNEL" >> "$LOGDIR/disk_var.sh"
    # The standard task must source these variables into FAI's parent shell.
    rm -f "$LOGDIR/skip.partition" "$LOGDIR/workstation-partition-failed"
}

if ! ( partition_workstation ); then
    die "Workstation preflight or disk selection failed; installation stopped."
fi
