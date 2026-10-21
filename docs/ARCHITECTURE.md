# Architecture

FAI owns generic hardware/OS policy. First boot owns permanent identity. This boundary prevents a public repository, workflow log, or ISO from containing personal credentials.

FAI installs Debian Stable, storage, packages, the `provision` account, security tooling, starter chezmoi data, Incus VM templates, and the first-boot engine. It consumes only temporary values from removable `FAI-BOOTSTRAP` media. Immediately before the destructive partition task, an interactive hook discovers physical disks, excludes mounted and installation-media devices, selects OS and bootloader targets, persists a stable identity fingerprint, revalidates it, and calls setup-storage. The bootloader target defaults to and must equal the OS target for this single-disk architecture.

First boot normalizes KeePassXC or YAML into one in-memory model, validates every mandatory field, and performs journaled stages: account, identity/SSH, chezmoi, backup locations, GRUB, LUKS rotation, and verification. State contains stage names and non-secret fingerprints only. Secrets remain in memory or root-only `/run` files and are cleaned on exit.

The permanent account is created, never produced by renaming `provision`. Final removal of `provision` is a separate command that must be run through sudo from the verified permanent account.
