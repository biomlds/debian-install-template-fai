# GitHub Actions

`validate.yml` runs public-policy, syntax, package/storage, recovery-failure, disk
selector, Argon2id, and manifest checks in Debian trixie on pushes/PRs/dispatch.

`build-iso.yml` runs only on workflow dispatch or `v*` tags in a privileged Debian
trixie container. It installs FAI plus GRUB/ISO tools, validates the repository and
manifest, builds pinned chezmoi/yazi/ya/sbctl, builds a fresh NFSROOT and ISO,
checks SHA-256 files, and scans public content including decompressed squashfs.
It uploads the ISO, ISO checksum, host-tool checksums/versions, and FAI logs.

No signing database or GitHub secret is used: target signing happens during the
installation using external KDBX media. GitHub does not produce a machine-specific
Secure Boot-signed target image. Build artifacts expire after 14 days.

Static CI cannot establish real firmware enrollment or snapshot-overlay recovery.
Use the acceptance tests in VALIDATION.md before deployment.
