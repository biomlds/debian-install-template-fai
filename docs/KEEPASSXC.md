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
| SSH | encrypted OpenSSH id_ed25519 and matching id_ed25519.pub attachments; optional config |
| Chezmoi | Repository; optional Branch (main) |
| Borg | Repository: absolute local USB path, e.g. /media/alex/Backup/borg-repo |
| Vorta | optional ProfileName, SourcePaths (comma-separated), excludes.txt attachment |
| Cryptomator | VaultPath relative to user's home, e.g. ~/Vaults/Personal |
| LUKS | Password (16+ characters, no newline) |
| SecureBoot | PK.key, PK.pem, KEK.key, KEK.pem, db.key, db.pem, GUID attachments |

Timezone defaults to America/Edmonton and locale to en_CA.UTF-8. The Login and
LUKS secrets are different credentials; the KDBX master is prompted separately.
Use the built-in **Username** field for Identity.Username and the built-in
**Password** fields for Login.Password and LUKS.Password. These names are reserved;
do not create custom attributes with those names. Other attributes in the table
are custom fields under Advanced. Entry titles and group paths must match
exactly, e.g. `Workstation Bootstrap/Identity` directly below the database root.

## Protected SSH keys and automatic agent loading

Generate an encrypted OpenSSH key on a trusted machine, entering a strong
passphrase when prompted:

```bash
ssh-keygen -t ed25519 -a 100 -f ~/.ssh/id_ed25519 -C 'alex@example.com'
```

Attach the encrypted private key and matching public key to the SSH entry. The
installer checks the OpenSSH encryption envelope and public-key match without
decrypting the private key or reading its passphrase. Unencrypted keys and
mismatched/corrupt envelopes are rejected; actual decryption is tested by
KeePassXC after login. Installed private keys remain encrypted and mode 0600.

In the **daily-use** KeePassXC database, keep that encrypted private-key attachment
and set the entry's built-in Password field to its SSH passphrase. This may be a
separate entry/database from the installer input. The installer ignores SSH.Password.
Keep Secure Boot keys offline rather than routinely unlocking them in the desktop.

Configure KeePassXC once in the GUI:

1. Enable SSH Agent integration under Tools → Settings → SSH Agent.
2. Edit the SSH entry's SSH Agent settings and select the private-key attachment.
3. Enable adding the identity on database open/unlock and removing it on
   database close/lock. Save the database.
4. Select **Workstation Sway** at LightDM login. This session starts OpenSSH's
   `ssh-agent` and exports its socket to Sway applications and user services.
   KeePassXC starts via the system Sway config; the supplied chezmoi config
   includes that fragment too. Custom Sway configs must include
   `/etc/sway/config.d/90-workstation-keepassxc.conf` or start KeePassXC themselves.
5. Open the daily database. KeePassXC decrypts the attachment using the entry's
   Password and loads it into the existing agent. It is an agent client, not an
   SSH-agent server; do not configure a separate KeePassXC socket or start an
   additional agent from shell startup files.

Verify `ssh-add -l` lists the identity after unlock and no longer lists it after
locking KeePassXC. Test authentication with your actual SSH/Git remote. Existing
SSH connections are not disconnected when the database locks. The session-scoped
agent stops when Sway exits. These GUI preferences belong to the daily database;
the installer does not inject the SSH passphrase into environment/config files.

## Local USB Borg backup

Borg uses a local USB repository with its own encryption passphrase, not SSH.
There is no `borg_ed25519` attachment or `BORG_RSH` setting. The installer reads
only Borg.Repository, never its Password field. Store the Borg passphrase in
daily KeePassXC or enter it when using Vorta; it is not needed during installation.
See [BACKUP.md](BACKUP.md) for mounting and repository encryption.

Generate Secure Boot keys offline using [SECURE_BOOT.md](SECURE_BOOT.md). The old
GRUB entry is obsolete. YAML is no longer accepted. Missing/invalid required
inputs abort before disk selection; there is no interactive plaintext fallback.

The master goes through stdin to KeePassXC CLI. Extracted private files are
root-only tmpfs files, and captured tool output is suppressed on failure. After
installation only intended account SSH keys remain on disk (inside LUKS);
Secure Boot private keys do not.
