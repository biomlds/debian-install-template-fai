# FAI build and installation

Install `server/NFSROOT`, `server/sources.list`, and reviewed values from `server/nfsroot.conf.example` under `/etc/fai`; copy `fai/config` to `/srv/fai/config`. Build pinned host binaries in an isolated container before the ISO.

Validation is non-destructive:

```bash
make validate
setup-storage -s -f fai/config/disk_config/LUKS_BTRFS
python3 tests/test-disk-selector.py
```

Actual installation requires mounted `FAI-BOOTSTRAP` media and an interactive console. The selector prompts on `/dev/console`; if that path fails it retries the active kernel console and `/dev/tty`. No production disk is supplied on the kernel command line. `hooks/partition.WORKSTATION` replaces FAI's standard partition task: it discovers physical disks, identifies and excludes the local FAI medium (or verifies network boot), prompts for OS and bootloader targets, requires a disk-specific `ERASE` token, persists stable identity, revalidates, and then calls `setup-storage -X -D <selected-kernel-device>`.

The selector rejects loop, RAM/zram, optical, device-mapper, read-only, mounted, too-small, and installation-media disks. A local live boot must resolve to exactly one backing medium; an unknown or ambiguous source aborts. Stable `/dev/disk/by-id` paths are preferred and the resolved kernel path is supplied as FAI `disklist`/`-D`.

The bootloader selector defaults to the OS disk. Choosing a different disk is rejected because this repository creates the ESP and encrypted system on one disk. The persisted `BOOT_DEVICE` and `PHYSICAL_BOOT_DEVICES` are checked again by the GRUB script against the disk backing `/boot/efi`.

From a shell in the booted FAI environment, run `python3 "$FAI/assets/disk-selection/disk_selector.py" select --dry-run`. `tools/preview-install.sh` is the repository wrapper. Both run the same interactive selection with a `PREVIEW` token, do not persist selection, do not invoke setup-storage, and write nothing.

Useful FAI logs are retained by FAI, but scripts never print credential contents. setup-storage's transient key is removed during installation after the bootstrap passphrase is verified.
