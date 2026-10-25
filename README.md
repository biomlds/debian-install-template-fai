# Debian FAI workstation

Credential-free Debian 13 amd64/UEFI installer for an encrypted Sway workstation.
FAI injects permanent identity from external KeePassXC media before partitioning.
The target uses custom-key Secure Boot, systemd-boot, signed UKIs, and selectable
protected Btrfs recovery snapshots.

**Integration status:** repository tests cover policy and failure handling. Actual
OVMF/Dell Secure Boot installation, recovery-overlay boot, and rollback still need
the acceptance tests in [VALIDATION.md](docs/VALIDATION.md). Use disposable disks
until those tests pass; this branch changes the installation/credential model.

## Architecture

- GPT: **2 GiB FAT32 ESP at `/boot`**, remaining space LUKS2 **Argon2id**.
- Btrfs `@root`, `@home`, `@snapshots`; root-only Snapper.
- Signed normal UKI plus three protected recovery snapshots/UKIs. A recovery boot
  has a writable RAM overlay; changes to root disappear on reboot.
- Pin the last **boot-tested** recovery snapshot until explicitly replaced.
- Signing keys stay offline in KDBX; manual boot-stack updates require an unlock.
- Daily unattended **Debian security-only userspace** upgrades, with pre-upgrade
  snapshots, a boot-stack blacklist, and no automatic reboot.
- Incus **VMs**, existing Flatpak application timer, Borg/Vorta, Cryptomator,
  KeePassXC, and manual chezmoi dotfile setup remain available.
- No temporary provision account, first-boot credential rotation, YAML secret
  input, target GRUB, or grub-btrfs. FAI's ISO bootloader remains separate.

## Build

```bash
make validate manifest-check
./tools/build-host-tools.sh       # isolated Debian 13 Docker/Podman build
sudo ./tools/build-iso.sh          # disposable Debian 13 root build environment
```

The [GitHub ISO workflow](.github/workflows/build-iso.yml) builds the pinned host
tools, FAI NFSROOT, ISO, SHA-256 files, and artifacts on manual dispatch or `v*`
tags. It uses no repository secrets. NFSROOT is the installer runtime embedded in
the ISO; offline installation does **not** need an NFS server.

## Install

1. Prepare KDBX entries and offline PK/KEK/db keys using
   [KEEPASSXC.md](docs/KEEPASSXC.md) and [SECURE_BOOT.md](docs/SECURE_BOOT.md).
2. Copy the database to an existing ext4 removable partition:

   ```bash
   sudo ./tools/prepare-kdbx-media.sh /dev/disk/by-id/REMOVABLE_PARTITION /private/Workstation.kdbx
   ```

3. Boot FAI in **UEFI** mode (Proxmox: q35 + OVMF + EFI disk). New custom-key
   enrollment requires firmware Setup Mode; an unsigned ISO may require Secure
   Boot disabled. Have firmware recovery instructions available.
4. The console prompts for the KDBX master before disk selection. Missing inputs
   abort before partitioning. Select the same OS/boot disk and type the exact
   `ERASE <identifier>` token. This erases the selected disk.
5. FAI installs the permanent account, replaces the temporary setup-storage LUKS
   slot, builds/signs boot artifacts, enrolls keys, and removes transient secrets.
6. Remove KDBX media. Enable Secure Boot if required by firmware. Boot the recovery
   entry first, verify the desktop/network and your data, then pin it:

   ```bash
   sudo workstation-secureboot confirm
   ```

7. Reboot into the normal Debian entry and run `sudo workstation-verify`.
   Initialize Incus with `sudo incus-init-workstation`; configure Vorta using
   `~/.config/borg/VORTA-FIRST-LOGIN.txt`; apply your chezmoi repository manually.
   Flatpak applications install in the background and retry hourly.

## Updates and recovery

```bash
sudo workstation-update --database /private/Workstation.kdbx
sudo workstation-secureboot snapshot --database /private/Workstation.kdbx
sudo workstation-secureboot status
sudo workstation-secureboot check
```

The update command signs a pre-update recovery entry before APT runs, then signs
the new normal UKI. It never reboots automatically. Recovery entries are labelled
with snapshot numbers in systemd-boot. To permanently roll back, boot a recovery
entry and use `workstation-rollback <number> --database /private/Workstation.kdbx`.
See [RECOVERY.md](docs/RECOVERY.md) for interruption handling and limitations.

Read [FAI.md](docs/FAI.md), [SECURITY.md](docs/SECURITY.md), and
[VALIDATION.md](docs/VALIDATION.md) before building or installing.
