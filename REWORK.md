# Workstation rework plan: signed UKIs and protected recovery snapshots

Status: implementation present, repository validation passing; ISO build and real
UEFI/Secure Boot recovery acceptance tests remain pending. This document records
the agreed design. See README.md and docs/VALIDATION.md for deployment status.

## Goals and agreed choices

- Keep Debian 13, FAI, amd64/UEFI, Sway, Incus VMs, the Flatpak timer,
  Borg/Vorta, Cryptomator, KeePassXC, and chezmoi for dotfiles.
- Keep the public repository, CI, and ISO free of per-install credentials,
  password hashes, private keys, KDBX databases, and populated secret configs.
- Use systemd-boot with signed Unified Kernel Images (UKIs), custom Secure Boot
  keys, LUKS2 Argon2id, and passphrase-only disk unlock. No TPM auto-unlock.
- Provide selectable protected recovery snapshots in the systemd-boot menu.
  GRUB and grub-btrfs are unnecessary for this target boot design.
- Use a **2 GiB FAT32 ESP mounted at `/boot`**.
- Retain **three protected recovery snapshots**, including the last boot-tested
  known-good snapshot, with a matching signed UKI for each.
- Enable **unattended security-only upgrades**, with no automatic reboot and no
  unattended changes to the kernel, initramfs, bootloader, or signing toolchain.
- Keep Secure Boot private keys offline in KDBX. Signing requires an explicit
  database unlock; private signing keys never persist on the installed disk.

## What NFSROOT does

Keep `server/NFSROOT` and `fai-make-nfsroot`. NFSROOT is FAI's installation
environment and is packed into the ISO by `fai-cd`; an offline installation does
not require an NFS server.

The installed target uses systemd-boot. The installer ISO may still use FAI's
GRUB/shim boot machinery. Audit those build/installer dependencies before
removing packages; target GRUB removal does not imply removing ISO boot tools.

## Storage and recovery model

```text
GPT
├── ESP       2 GiB FAT32, /boot: systemd-boot and signed UKIs
└── LUKS2     remaining space, Argon2id
    └── Btrfs
        ├── @root       /
        ├── @home       /home
        └── @snapshots  /.snapshots
```

Keep existing Btrfs compression policy and root-only Snapper snapshots. The ESP
is outside root snapshots; each protected snapshot therefore needs an explicitly
paired UKI containing its matching kernel, initramfs, and kernel command line.
Its kernel modules and early-boot configuration must match the saved root.

Boot entries:

- Normal: `debian.efi`, booting writable `@root`.
- Recovery: `ws-protected-<id>.efi`, booting the corresponding saved root.
- Show an accessible systemd-boot menu with descriptive snapshot identifiers;
  disable command-line editing under the intended Secure Boot policy.

Protected snapshots remain read-only. Prototype a writable ephemeral root using
`systemd.volatile=overlay` and explicitly enable the required dracut/systemd
initrd support. Verify that root selection is not overridden by the snapshot's
fstab, that `/home` and `/.snapshots` mount correctly, and that normal userspace
can start. This is a release-blocking integration test, not an assumed feature.
If it fails, revise the recovery-root design before shipping.

Root recovery preserves the separate `/home` subvolume, but cannot undo changes
already made to home files, external databases, firmware, or other disks.
Snapshots share the underlying disk and are not a substitute for Borg backups
and external recovery media. Hardware failure cannot be covered by a boot entry.

## KDBX preflight and key lifecycle

- Mount exactly one ext4 filesystem labelled `WORKSTATION-KDBX`, containing
  `Workstation.kdbx`, read-only with `nosuid,nodev,noexec`.
- Validate media, file type, ownership/permissions, and symlink safety.
- Run the unlock and schema validation at the start of
  `hooks/partition.WORKSTATION.sh`, before disk selection or `setup-storage`.
  Independently recheck UEFI and all prerequisites: FAI class-script errors
  alone are not a sufficient destructive-operation guard.
- Prompt without echo on the console. Pass the master password to
  `keepassxc-cli` on stdin; never place secret values in argv, shell tracing,
  exported environment variables, FAI logs, or the config space.
- Extract to root-only tmpfs under `/run/fai/workstation-secrets`. Provide a
  dedicated temporary mount inside the target for chroot signing.
- Pre-generate PK/KEK/db keys offline with pinned sbctl 0.18. Store key/cert pairs
  and GUID as KDBX attachments. Keep a second offline KDBX backup.
- Enroll only in firmware Setup Mode. For reinstalls, allow matching already
  enrolled keys without re-enrollment; reject unexpected firmware trust state.
- Sign and verify systemd-boot, its fallback path, UKIs, and firmware-update EFI
  executables as needed. Enroll Microsoft certificates where required using
  sbctl's supported workflow; never automatically bypass OptionROM checks.
- Remove secret files, terminate secret-bearing processes, and unmount temporary
  mounts on success and failure. File removal or shredding is not a guarantee of
  erasing all RAM copies; the design relies on avoiding persistent secret writes.
- Public certificates/fingerprints may remain on the target; private signing
  keys and the database master password must not.

Preserve the existing `Workstation Bootstrap` entries for Identity, Login, Git,
SSH, Chezmoi, Borg, Vorta, Cryptomator, and LUKS; remove GRUB and add SecureBoot
attachments `PK.key`, `PK.pem`, `KEK.key`, `KEK.pem`, `db.key`, `db.pem`, `GUID`.
Use KDBX as the install-time source and retire the YAML/first-boot path.

## Protected snapshot lifecycle

Track separate states: created, signed/verified, boot-tested known-good, and
retired. A valid signature does not establish that the OS boots successfully.

- Establish the first recovery baseline after successful target boot validation.
- Pin the last boot-tested known-good snapshot until another recovery snapshot
  has actually booted and passed the health checks. A running normal system alone
  does not prove its protected recovery entry works.
- Retain three protected snapshots at steady state, reserving a slot for that
  pinned baseline rather than blindly retaining the newest three.
- Exclude protected snapshots from ordinary Snapper cleanup using explicit
  protected-state tracking and no automatic cleanup assignment. Do not assume
  `important=yes` makes a snapshot undeletable; it is only a retention hint.
- Preserve the last signed normal UKI separately during promotion of a new one.
  It protects against kernel regressions but is not a replacement for a matched
  root snapshot when userspace has changed.
- Check Btrfs and ESP capacity before starting. Allow temporary space for a
  candidate fourth protected entry, normal/previous UKIs, and atomic replacement
  files. Measure actual sizes; refuse safely if 2 GiB is insufficient.
- Prune only after publishing and verifying the replacement. Never prune the
  pinned baseline, the currently booted recovery snapshot, or the sole usable
  recovery path. Remove the old UKI before removing its snapshot.
- Use explicit administrator confirmation for replacing the known-good baseline;
  retention pressure must not silently replace it with an untested candidate.

## Controlled manual update workflow

`workstation-update` orchestrates boot-affecting upgrades:

1. Acquire a common maintenance lock and coordinate with APT/dpkg locks and
   unattended-upgrades. Unlock KDBX; validate keys, storage, and recovery state.
2. Create a pre-update root snapshot. Build or reuse validated matching boot
   artifacts, sign its recovery UKI, verify it, and publish it before upgrading.
3. Run the requested APT upgrade. Keep existing recovery artifacts untouched on
   package/configuration failure; record a clear resumable failure state.
4. Build the new normal UKI into `/var/lib/workstation-uki`, sign and verify it,
   then publish using a staged replacement. Flush writes and preserve rollback
   artifacts; FAT updates are not a multi-file atomic transaction.
5. Verify boot files, signatures, LUKS configuration, and space. Clean temporary
   secrets on every exit. Request a manual reboot; mark the new system healthy
   only after post-boot checks and explicit recovery-baseline confirmation.

Suppress automatic writes of unsigned boot artifacts to the ESP, including
`systemd-boot-update.service` and relevant package hooks. Audit Debian maintainer
scripts and kernel-install plugins rather than assuming that masking one service
or holding one package covers every writer. Prefer controlled update hooks over
indefinite package holds; any necessary temporary hold is lifted and restored by
the maintenance workflow and surfaced in status output.

## Unattended security-only upgrades

- Allow only Debian 13's official security origin, verified against actual APT
  release metadata. Exclude proposed-updates, testing, and third-party origins.
- Allow security fixes to ordinary userspace, including systemd core where
  dependency resolution permits. A systemd core update must not trigger unsigned
  ESP writes; integration-test the hook controls above.
- Blacklist boot-affecting package families: kernel images and metapackages,
  headers, dracut/initramfs tools, systemd-boot/UKI generation tools, cryptsetup,
  shim/GRUB if present, and firmware packages/tools that require coordinated boot
  validation. Derive exact regexes from Debian package names and test them.
- Do not force dependency conflicts or partially install a blocked boot-stack
  update. Report deferred security updates through `workstation-verify` and
  maintenance status; apply them promptly through `workstation-update`.
- Disable automatic reboots and automatic removal of fallback kernels.
- Create a root snapshot immediately before each unattended transaction under
  the maintenance lock, with bounded retention separate from protected snapshots.
  If the snapshot cannot be made, defer the transaction and report the failure.
- These unsigned snapshots are live-media/manual recovery points, not new
  systemd-boot entries. Unattended runs cannot sign without the offline key.
  The pinned signed known-good recovery entry remains available throughout.
- Monitor failures and deferrals. Security-only userspace changes can still
  break the running OS; recovery goes back to the last boot-tested baseline,
  not necessarily the state immediately before the unattended transaction.

## Rollback and external recovery

`workstation-rollback <id>` runs only from a validated recovery environment or
live media. It must refuse to replace a currently mounted active `@root`.

- Mount the Btrfs top level, create a writable clone of the selected snapshot,
  and preserve the broken root under a unique name.
- Restore `@root` and its required configuration without changing `/home`.
- Rebuild and sign the normal UKI using KDBX. Verify before selecting it as
  default; keep the signed recovery entry available if signing fails.
- Document rollback interruption handling, low-space recovery, passphrase
  changes, firmware key reset/rotation, ESP restoration, and lost KDBX recovery.
- Maintain external UEFI recovery media: the unsigned installer may require
  temporarily disabling Secure Boot; document that step explicitly.

## Implementation map

1. **Build and installer:** update `tools/build-host-tools.sh` to pin sbctl 0.18
   and drop grub-btrfs. Verify sbctl's CGO/PCSC build/runtime dependencies in
   Debian 13. Update host-tool hashes/versions. Add KeePassXC CLI, console tools,
   and required libraries to `server/NFSROOT`. Fix standalone FAI logging and
   explicit NFSROOT rebuild behavior. Harden ISO/archive secret scanning.
2. **Preflight and storage:** replace `class/20-bootstrap`; add shared KDBX
   validation; update `WORKSTATION.var`, `partition.WORKSTATION`,
   `disk_config/LUKS_BTRFS`, and `mountdisks.LUKS_BTRFS`. Add the permanent
   Argon2id passphrase, verify it, then remove the setup-storage keyslot and file;
   never persist a temporary key for first boot. Add KDBX media preparation.
3. **Identity:** replace `10-provision-user` with install-time permanent identity,
   SSH/Git configuration, backup scaffolding, and manual chezmoi setup. Retain
   Incus VM assets and Flatpak timer. Retire provision/YAML/first-boot assets.
4. **Boot and recovery:** replace target `GRUB_EFI` with `SYSTEMD_BOOT`; install
   unsigned upstream EFI artifacts for local signing. Switch target initramfs
   generation to dracut/ukify. Add staging kernel-install plugin, menu entries,
   signing/enrollment tool, protected-state tracking, update/rollback commands,
   health checks, and fwupd integration. Keep all private keys transient.
5. **Automatic security maintenance:** implement origin restrictions, tested
   package blacklist, pre-transaction snapshot/locking, notifications, and
   disabled automatic reboots/removal of fallback kernels.
6. **Documentation and validation:** rewrite consistency/input/storage tests and
   relevant docs, retire GRUB/first-boot instructions, update Makefile/validation
   tooling, host-tool metadata, and `MANIFEST.sha256` as implementation lands.

## Acceptance gates

- Run repository validation, meaningful KDBX/retention/promotion failure tests,
  regular-file Argon2id keyslot tests, and manifest checks.
- Build and boot the ISO using Proxmox q35/OVMF UEFI with separate KDBX media.
- Verify wrong/missing inputs abort before disk selection or disk writes.
- Prove snapshot recovery boots with matching modules and writable ephemeral
  root; prove rollback preserves `/home` and the broken root.
- Intentionally break a test system after an update and recover through the
  visible menu. Test interrupted signing, full ESP, low Btrfs space, retention,
  failed APT transactions, and interrupted rollback.
- Run multiple unattended security transactions: verify origin/package policy,
  lock coordination, snapshots, no reboot, and no unsigned ESP writes.
- Test real Secure Boot enrollment, recovery entry selection, normal/recovery
  boot, firmware updates, and key reset on the Dell Latitude 5490.
- Do not describe the recovery guarantee as proven until the recovery boot and
  rollback tests pass. Local snapshots cover software regressions, not disk or
  firmware failure; maintain tested external backups and recovery media.
