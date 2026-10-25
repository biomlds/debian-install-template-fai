# Storage

The interactive selector chooses one physical disk for both OS and bootloader.
It excludes installation/mounted media and revalidates disk identity immediately
before setup-storage. The exact `ERASE` confirmation destroys the selected disk.

```text
GPT
├─ ESP 2 GiB FAT32 → /boot
└─ LUKS2 Argon2id → cryptroot → Btrfs
   ├─ @root → /
   ├─ @home → /home
   └─ @snapshots → /.snapshots
```

Mount options remain `noatime,compress=zstd:3`; no swapfile or separate Incus
subvolume is introduced. The ESP uses `umask=0077`. UKIs and package kernel
artifacts occupy the ESP; measured capacity is checked before maintenance.

Protected snapshots have no Snapper cleanup algorithm. The separate root registry
retains three entries including the pinned boot-tested baseline and the currently
booted recovery entry. Signing temporarily needs room for a fourth candidate and
normal/previous UKIs. Cleanup never silently replaces the pinned baseline.

Snapper ordinary timeline/pre-security snapshots use separate bounded cleanup.
The ESP is not part of a root snapshot: recovery requires its paired signed UKI.
`/home` is shared, including when booted into recovery; root rollback does not undo
personal-data changes. Keep external backups and recovery media.

Changing ESP size after installation is a partition migration, not an automatic
upgrade; existing installations are not converted by this config space.
