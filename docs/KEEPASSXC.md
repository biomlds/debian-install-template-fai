# KeePassXC input

Keep two offline copies of the private database. Neither database nor attachments
belong in Git, GitHub secrets, build artifacts, or the public ISO.

Prepare an existing ext4 partition with `tools/prepare-kdbx-media.sh`. It copies
the database as root-owned mode 0600 `Workstation.kdbx` and applies filesystem
label `WORKSTATION-KDBX`; it does not format. The installer mounts it read-only.
Use a separate removable device or Proxmox disk from the installation target.

Under group **Workstation Bootstrap**, create these entries (case-sensitive):

| Entry | Attributes or attachments |
| --- | --- |
| Identity | Username, FullName, Hostname; optional Timezone, Locale |
| Login | Password (12+ characters, no colon/newline); optional Groups including sudo |
| Git | Name, Email |
| SSH | attachments id_ed25519 and id_ed25519.pub; optional config |
| Chezmoi | Repository; optional Branch (main) |
| Borg | Repository; optional borg_ed25519 attachment |
| Vorta | optional ProfileName, SourcePaths (comma-separated), excludes.txt attachment |
| Cryptomator | VaultPath relative to user's home, e.g. ~/Vaults/Personal |
| LUKS | Password (16+ characters, no newline) |
| SecureBoot | PK.key, PK.pem, KEK.key, KEK.pem, db.key, db.pem, GUID attachments |

Timezone defaults to America/Edmonton and locale to en_CA.UTF-8. The Login and
LUKS secrets are different credentials; the KDBX master is prompted separately.
SSH private keys must be usable without an interactive passphrase during setup;
the permanent user's SSH agent can be configured after login.

Generate Secure Boot keys offline using [SECURE_BOOT.md](SECURE_BOOT.md). The old
GRUB entry is obsolete. YAML is no longer accepted. Missing/invalid required
inputs abort before disk selection; there is no interactive plaintext fallback.

The master goes through stdin to KeePassXC CLI. Extracted private files are
root-only tmpfs files, and captured tool output is suppressed on failure. After
installation only intended account SSH keys remain on disk (inside LUKS);
Secure Boot private keys do not.
