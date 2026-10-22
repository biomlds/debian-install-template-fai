# KeePassXC schema

Default database: `~/Documents/Secrets/Passwords.kdbx`. Override with `--database`. Default group prefix: `Workstation Bootstrap`; override with `--entry-prefix`.

Create these entries and exact attributes/attachments:

| Entry | Attributes / protected value | Attachments |
|---|---|---|
| `Identity` | `Username`, `FullName`, `Hostname`, optional `Timezone`, `Locale` | — |
| `Login` | Password = permanent login password; optional `Groups` comma-separated (must include `sudo`) | — |
| `Git` | `Name`, `Email` | — |
| `SSH` | — | `id_ed25519`, `id_ed25519.pub`, optional `config` |
| `Chezmoi` | `Repository`, optional `Branch` | — |
| `Borg` | `Repository` | optional `borg_ed25519` |
| `Vorta` | optional `ProfileName`, comma-separated `SourcePaths` | optional `excludes.txt` |
| `Cryptomator` | `VaultPath` | — |
| `GRUB` | optional `Username`; Password = permanent GRUB password | — |
| `LUKS` | Password = permanent LUKS passphrase | — |

The CLI asks for the database master password once per first-boot run and supplies it to `keepassxc-cli` over stdin, never argv. Only requested fields are extracted into root-only `/run` files. The database may be on removable or separately restored media.
