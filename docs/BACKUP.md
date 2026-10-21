# Backups and secret bootstrap

Borg, normally managed by Vorta, backs up all personal files: the KeePassXC database, SSH public/private material, documents, dotfiles, and local Cryptomator vault ciphertext. Cryptomator is cold local storage for sensitive, rarely accessed data; Borg still protects its encrypted vault folders. borgmatic is intentionally absent.

First boot validates the supplied Borg and Cryptomator credentials, writes repository and optional Borg SSH-key information to `~/.config/borg/bootstrap.env`, but does not duplicate either passphrase on disk. Vorta imports the repository after graphical login and stores its normal state in the user's session/keyring; Cryptomator receives its credential directly from the selected source when the vault is opened.

There is an unavoidable bootstrap dependency: the Borg passphrase/key may be in KeePassXC, while the KeePassXC database may itself need restoring from Borg. Keep a separately encrypted/removable copy of the KeePassXC database, Borg repository location, Borg key/passphrase, and LUKS recovery information. The first-boot database or YAML can be supplied from removable or separately restored media.

Test restores regularly into a new directory. A successful backup job without a tested restore is not a verified backup.
