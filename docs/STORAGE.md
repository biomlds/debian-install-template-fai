# Storage

```text
GPT
├── ESP       1 GiB FAT32, /boot/efi
└── LUKS2     remaining space, PBKDF2 keyslots for GRUB compatibility
    └── Btrfs
        ├── @root       /  (contains /boot)
        ├── @home       /home
        └── @snapshots  /.snapshots
```

Mount options are `noatime,compress=zstd:3` for all Btrfs mounts. There is no Btrfs swapfile and no `@var_log`, `@var_cache`, `@var_tmp`, `@incus`, or `@swap`. Incus uses its `dir` storage driver inside root. Stop/export important VMs before major snapshots.

FAI's `setup-storage` deliberately does not create Btrfs on encrypted (`luks`) volumes. `hooks/mountdisks.LUKS_BTRFS` therefore formats a freshly opened, empty mapper with `mkfs.btrfs -L debian-root`, rejects a mapper containing another filesystem, and only then creates the subvolumes. The Btrfs label is not applied by `setup-storage`.

The OS disk is selected interactively in the FAI partition hook. The display includes kernel path, preferred stable ID, model, serial, transport, size, and existing child filesystem/mount summary. The bootloader disk is selected independently but must equal the OS disk for this single-disk UEFI layout. The selection and identity fingerprint are saved in FAI logs and copied to `/var/log/fai/disk-selection.json` on the installed host.

Snapper has one root configuration. `@home` and `@snapshots` are separate and therefore excluded from root snapshots. Personal data is protected by Borg/Vorta, not Snapper.

Keeping `/boot` in `@root` lets a snapshot contain matching kernels and initramfs. It requires GRUB to unlock LUKS2 and therefore requires PBKDF2-compatible LUKS keyslots. This is a documented compatibility tradeoff; use a strong passphrase.
