# Debian FAI workstation

Credential-free FAI installer for an encrypted **Debian 13 amd64/UEFI Sway
workstation**. Permanent identity and secrets come from external KeePassXC media
during installation. The installed system uses custom-key Secure Boot,
systemd-boot, signed Unified Kernel Images (UKIs), and selectable protected Btrfs
recovery snapshots.

**Status: experimental.** Repository checks pass, but the ISO build and end-to-end
installation, Secure Boot enrollment, recovery-overlay boot, and rollback still
need the acceptance tests in [Validation](docs/VALIDATION.md). Use disposable
target disks for initial testing. This design replaces the earlier
FAI-BOOTSTRAP and first-boot credential model.

## Design

| Area | Behaviour |
| --- | --- |
| Storage | GPT; **2 GiB FAT32 ESP at `/boot`**; remaining space encrypted with LUKS2 Argon2id |
| Filesystem | Btrfs `@root`, `@home`, and `@snapshots`; Snapper manages root snapshots |
| Boot | Firmware → signed systemd-boot → signed UKI → dracut → LUKS passphrase unlock |
| Recovery | Up to three protected snapshot entries, each with a matching signed UKI |
| Known-good baseline | A recovery snapshot must actually boot and be explicitly confirmed before it becomes the pinned baseline |
| Signing keys | Stored offline in KDBX; boot-stack updates require an explicit database unlock |
| Automatic updates | Daily Debian security-only userspace upgrades with pre-upgrade snapshots; boot-stack packages are deferred; no automatic reboot |

A recovery entry boots a saved root with a writable RAM overlay. Root changes are
discarded on reboot; **`/home` remains shared and writable**. Root snapshots do not
protect against disk failure or undo personal-data changes. Keep external backups.

The workstation includes Incus **VMs**, a retrying Flatpak application-installation
timer, Borg/Vorta, Cryptomator, KeePassXC, and manual chezmoi dotfile setup. There
is no temporary provisioning account or first-boot credential rotation. Target
GRUB and grub-btrfs are replaced by systemd-boot recovery entries; FAI's installer
ISO still has its own bootloader.

## Requirements

SSH identities must be **passphrase-protected OpenSSH keys**. The Workstation
Sway session starts an OpenSSH agent; KeePassXC loads/removes keys on database
unlock/lock after the one-time entry setup in [KeePassXC inputs](docs/KEEPASSXC.md).
Borg backups use a **local USB repository with a passphrase**, without SSH.

- An amd64 UEFI machine. For Proxmox, use **q35 + OVMF + an EFI disk**;
  BIOS/SeaBIOS/CSM is unsupported.
- A target disk that may be erased. OS and bootloader must use the same disk.
- A separate removable device or virtual disk with an **existing ext4 partition**
  for KDBX media.
- A private KeePassXC database populated according to
  [KeePassXC inputs](docs/KEEPASSXC.md), including pre-generated PK/KEK/db keys
  described in [Secure Boot](docs/SECURE_BOOT.md).
- Firmware Setup Mode for first enrollment, or already enrolled keys matching the
  database. Know how to restore firmware keys before changing them.
- Two offline KDBX copies and external backups of important data. After
  installation, also keep a private LUKS-header backup.

## Build or download the ISO

### GitHub Actions

Run **build-fai-iso** from the repository's **Actions** tab, or push a `v*` tag.
The [ISO workflow](.github/workflows/build-iso.yml) validates the repository,
builds pinned host tools and FAI NFSROOT, builds/scans the ISO, and uploads:

- `debian-fai-workstation.iso` and its SHA-256 checksum;
- host-tool checksums and version metadata;
- FAI build logs in a separate artifact, including on build failure.

No repository secrets or machine-specific signing keys are used. Verify the
downloaded ISO before writing it to installation media:

```bash
sha256sum -c debian-fai-workstation.iso.sha256
```

### Local build

Install the validation and FAI/ISO build dependencies listed in the
[workflow](.github/workflows/build-iso.yml). Run the ISO builder in a disposable,
privileged **Debian 13** environment; it configures `/etc/fai` and `/srv/fai`.
The host-tool builder uses Docker or Podman by default.

```bash
make validate test manifest-check
./tools/build-host-tools.sh
sudo ./tools/build-iso.sh
```

The output is `build/debian-fai-workstation.iso` with a companion checksum.
**NFSROOT is required:** it is FAI's installer runtime embedded in the ISO, not a
requirement for an NFS server. The current `fai-cd -M` build omits a package mirror,
so installation needs network access to the configured Debian repositories.

## Install

1. Prepare the database and offline signing keys using
   [KeePassXC inputs](docs/KEEPASSXC.md) and [Secure Boot](docs/SECURE_BOOT.md).
2. Copy the database to an existing ext4 removable partition:

   ```bash
   sudo ./tools/prepare-kdbx-media.sh \
     /dev/disk/by-id/REMOVABLE_PARTITION /private/Workstation.kdbx
   ```

   The helper labels it `WORKSTATION-KDBX` and installs a private,
   root-owned `Workstation.kdbx`. It does not format the partition and refuses to
   overwrite an existing database.
3. Boot the ISO in **UEFI mode** with KDBX media attached. The installer ISO may
   require Secure Boot temporarily disabled; disabling Secure Boot alone does
   not put firmware into Setup Mode.
4. Enter the KDBX master password at the console. Input and firmware-key validation
   run **before disk selection and partitioning**. Select the same disk for OS
   and bootloader, then type `ERASE <identifier>` exactly.
   **The selected disk will be erased.**
   If an attempt fails after partitioning, **reboot the installer before retrying**.
   FAI leaves `/target` mounted and a second run would regenerate the LUKS key
   while the old mapper stays open; the hook now refuses that state.
5. FAI installs the permanent account, replaces the temporary setup-storage LUKS
   slot with the permanent Argon2id credential, signs boot artifacts, enrolls keys
   when needed, and removes transient secrets.
6. Remove KDBX media and enable Secure Boot if firmware requires it. Select the
   numbered **Recovery snapshot** entry in systemd-boot. Log in as the permanent
   user, check the desktop, network, and shared data, then pin the baseline:

   ```bash
   sudo workstation-secureboot confirm
   ```

   Confirmation requires **Secure Boot enabled** and an actual recovery-overlay
   boot. A signed snapshot alone is not yet a boot-tested baseline.
7. Reboot into the normal Debian entry and run:

   ```bash
   sudo workstation-verify
   ```

   Do routine setup in the normal system, since root changes made in recovery
   disappear on reboot. Initialize Incus with `sudo incus-init-workstation`,
   configure Vorta from `~/.config/borg/VORTA-FIRST-LOGIN.txt`, and initialize your
   chezmoi repository manually. Review `chezmoi diff` before applying dotfiles.
   Flatpak applications install in the background and retry hourly.

## Updates and recovery

### Manual boot-stack updates

Attach or mount your private KDBX media, then run:

```bash
sudo workstation-update --database /private/Workstation.kdbx
```

This publishes a signed pre-update recovery entry before upgrading packages, then
builds and signs the new normal UKI and bootloader. It never reboots automatically.
The previously confirmed recovery baseline stays pinned until you explicitly
replace it by booting and confirming another recovery entry.

To create an additional recovery candidate or inspect protection status:

```bash
sudo workstation-secureboot snapshot --database /private/Workstation.kdbx
sudo workstation-secureboot status
sudo workstation-secureboot check
```

### Automatic security updates

Security-only unattended userspace upgrades start after a known-good recovery
baseline has been confirmed. They create ordinary pre-upgrade snapshots, but
**cannot create signed recovery entries without your offline key**. Boot-affecting
packages wait for `workstation-update`; review deferred updates regularly:

```bash
apt list --upgradable
journalctl -u workstation-security-upgrade.service
journalctl -u workstation-uki-check.service
```

### Roll back a broken system

Choose a numbered recovery entry from the systemd-boot menu. To make a saved root
the normal working system, run this **from the recovery boot**:

```bash
sudo workstation-rollback NUMBER --database /private/Workstation.kdbx
```

Rollback preserves the broken root and leaves `/home` unchanged. Reboot manually
after it succeeds. See [Recovery](docs/RECOVERY.md) for interruption handling,
external-media repair, key loss, and limitations.

## Documentation

- [Portable Sway desktop integration](docs/SWAY.md)

- [Architecture](docs/ARCHITECTURE.md) and [FAI installer](docs/FAI.md)
- [Storage](docs/STORAGE.md) and [LUKS](docs/LUKS.md)
- [KeePassXC inputs](docs/KEEPASSXC.md) and [Secure Boot](docs/SECURE_BOOT.md)
- [Security](docs/SECURITY.md), [Recovery](docs/RECOVERY.md), and
  [Validation](docs/VALIDATION.md)
- [Backups](docs/BACKUP.md), [Incus](docs/INCUS.md), and
  [GitHub Actions](docs/GITHUB_ACTIONS.md)
