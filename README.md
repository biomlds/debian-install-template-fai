# Debian FAI workstation

A ready-to-use FAI config space for a reproducible **Debian 13 Stable**, amd64/UEFI, encrypted Sway workstation. Public machine policy is separated from private first-boot identity and credentials.

## Architecture

- GPT with a 1 GiB EFI System Partition and one LUKS2/Btrfs system partition.
- Exactly `@root`, `@home`, and `@snapshots`; Snapper manages `/` only.
- `/boot` is inside encrypted `@root`, allowing snapshots to retain matching kernels/initramfs.
- FAI creates only the temporary `provision` account and a temporary LUKS credential from removable `FAI-BOOTSTRAP` media.
- First boot creates a separate permanent user from **KeePassXC by default** or `config.yaml`, configures GRUB and rotates LUKS safely, then requires a verified permanent-user login before `provision` can be removed.
- Project runtimes stay in Incus VMs; the host has no mise or project language stacks.

## Quick start

1. **Validate without touching disks**

   ```bash
   make validate
   ```

2. **Build host tools and ISO**

   ```bash
   ./tools/build-host-tools.sh          # isolated Podman/Docker build
   sudo ./tools/build-iso.sh
   ```

   GitHub Actions validates every change. ISO building runs only on explicit dispatch or `v*` tags and uses no repository secrets.

3. **Create temporary install credentials**

   ```bash
   sudo ./tools/prepare-bootstrap.sh /dev/disk/by-id/REMOVABLE_PARTITION provision.pub
   ```

   Boot FAI normally with an interactive console:

   ```text
   FAI_FLAGS=verbose,sshd,createvt,reboot
   ```

   Immediately before partitioning, FAI lists eligible physical disks with stable
   IDs, model, serial, transport, size, and current layout. Select the OS disk and
   bootloader disk; this single-disk design requires them to be the same. You must
   type `ERASE <selected-identifier>` before setup-storage runs (the stable-ID
   basename when available, otherwise the kernel name). EOF, cancellation,
   mounted disks, installation media, identity changes, and ambiguous boot media
   abort installation.

   From a shell in the booted FAI environment, run
   `python3 "$FAI/assets/disk-selection/disk_selector.py" select --dry-run`.
   `tools/preview-install.sh` is the repository wrapper for the same operation.
   Both use a `PREVIEW` confirmation and perform no writes.

   After installation, remove `FAI-BOOTSTRAP` before first boot. Enter the temporary
   LUKS passphrase and sign in as `provision`.

4. **First boot — KeePassXC default**

   ```bash
   sudo workstation-firstboot validate-input --database /media/secure/Passwords.kdbx
   sudo workstation-firstboot apply --database /media/secure/Passwords.kdbx
   ```

   Or use YAML:

   ```bash
   cp config/config.yaml.example /media/secure/config.yaml
   chmod 600 /media/secure/config.yaml
   sudo workstation-firstboot validate-input --source yaml --config /media/secure/config.yaml
   sudo workstation-firstboot apply --source yaml --config /media/secure/config.yaml
   ```

   The tool creates the permanent user, checks password/PAM and sudo, installs SSH/Git/chezmoi state, records Borg/Vorta and Cryptomator locations, installs a local GRUB PBKDF2 credential, and rotates LUKS. It is resumable: rerun the same command after correcting an error. Borg and Cryptomator passphrases are entered after login, not during first boot.

5. **Verify and finish**

   ```bash
   sudo workstation-firstboot status
   sudo workstation-verify
   # Log out and log in as the permanent user, then:
   sudo workstation-firstboot finalize
   ```

   Flatpak applications install in the background once the first-boot network is
   online. Check progress with `journalctl -u workstation-flatpaks.service`;
   failures retry hourly.

6. **Restore and initialize services**

   - Apply/inspect dotfiles: `chezmoi diff && chezmoi apply`.
   - In Vorta, add the Borg repository recorded in `~/.config/borg/bootstrap.env`, restore personal files if needed, then configure backup of all personal files, the KeePassXC database, and local Cryptomator vault ciphertext.
   - Initialize Incus: `sudo incus-init-workstation`; create a VM with `/usr/local/share/workstation-bootstrap/incus/scripts/create.sh devbox dev`.

Read [FAI.md](docs/FAI.md), [VALIDATION.md](docs/VALIDATION.md),
[SECURITY.md](docs/SECURITY.md), and [RECOVERY.md](docs/RECOVERY.md) before installation.
