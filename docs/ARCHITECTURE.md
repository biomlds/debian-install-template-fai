# Architecture

FAI NFSROOT is embedded in the ISO. The installer remains amd64/UEFI-only; the
target boot chain is firmware → locally signed systemd-boot → signed UKI → dracut
→ passphrase-unlocked LUKS2 Argon2id → Btrfs.

External ext4 `WORKSTATION-KDBX` media supplies permanent identity, LUKS passphrase,
SSH keys, and offline PK/KEK/db signing keys. The partition hook independently
validates all inputs before invoking disk selection or setup-storage. Secrets
live on tmpfs; only intended installed identity files and public certificates
persist. The permanent LUKS passphrase never becomes a target keyfile.

The 2 GiB ESP is mounted at `/boot`. Normal kernels installed by Debian remain
there as package artifacts, but only signed UKIs are systemd-boot entries.
Matching kernel/initrd archives inside root are captured with protected snapshots.
Recovery UKIs select their snapshot explicitly and request a RAM overlay. Snapshot
fstab is disabled for recovery and explicit signed mount arguments select home,
snapshots, and ESP without remounting the wrong root.

`boot.py` owns signature verification, publication, snapshot registry, retention,
update coordination, and rollback. The last boot-tested baseline survives pruning.
APT hooks only mark boot-stack changes pending; diverted Debian loader hooks and
masked bootloader updater prevent unsigned ESP publication.

Security-only unattended userspace upgrades run through a shared maintenance
lock, create ordinary cleanup-managed snapshots, and never reboot. Boot-stack
security updates require KDBX and `workstation-update`. Incus remains VM-only;
Flatpak applications retain their existing independent installation timer.

See [REWORK.md](../REWORK.md) for design decisions and [VALIDATION.md](VALIDATION.md)
for the still-required real boot acceptance gates.
