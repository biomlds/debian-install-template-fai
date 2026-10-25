# Validation

```bash
make validate test manifest-check
sha256sum -c MANIFEST.sha256
```

Validation checks shell/Python/YAML syntax, FAI package/disk consistency,
destructive-hook ordering, unattended package regexes, snapshot retention and
signature-failure publication behavior, private database permissions, public
payload scanning, mocked disk discovery, and regular-file Argon2id key rotation.
The cryptsetup test skips when cryptsetup is unavailable; CI installs it.
No automated test writes a real block device.

Current local results: shell syntax, ShellCheck, YAML/Python compilation, FAI
disk syntax, 8 configuration-contract tests, 18 recovery/input/scanner tests, 12 mocked
disk-selector tests, and the regular-file Argon2id transition pass. The actual
GitHub ISO build and the manual acceptance gates below are not yet verified.

ISO workflow dispatch/tag builds pinned host tools (including sbctl), FAI NFSROOT,
ISO/checksums, and scans extracted ISO plus nested filesystem contents. FAI 6.4
may place `LiveOS/ext3fs.img` inside `squashfs.img`; the scanner detects both by
filesystem magic, extracts squashfs and mounts ext read-only with journal replay
disabled. It scans allocated files rather than raw filesystem/free-space bytes.
Mount/extraction failures fail the build; mounts are removed even after a secret
match. Diagnostics name the image, contained file and matching rule without
printing secret contents. NFSROOT CLI smoke
checks validate KeePassXC and sbctl runtime compatibility. Build logs are uploaded
even when the workflow fails.

GnuTLS embeds private-key fixtures for its upstream self-tests. The ISO scan
permits only `usr/lib/x86_64-linux-gnu/libgnutls.so.30.*.*` with an exact SHA-256
match to the original NFSROOT library, after verifying that library against its
Debian dpkg package checksum. This uses the original package metadata because
FAI strips dpkg info from the ISO runtime. Modified libraries and all other
private-key files still fail; there is no blanket binary or directory exclusion.

## Release-blocking manual acceptance tests

Use a disposable Proxmox q35/OVMF VM with EFI disk, a target disk, and separate
ext4 KDBX media. Run real tests on the Dell 5490 before relying on recovery:

1. Missing/wrong database, bad password/keys, foreign firmware keys, BIOS mode,
   cancelled disk selection: no target disk writes.
2. Full install: permanent login, Argon2id-only active slot, no temporary key or
   provision account, signed systemd-boot/fallback/UKIs and firmware trust.
3. Boot initial recovery UKI: correct snapshot/kernel/modules, writable overlay,
   correct shared home/snapshot/ESP mounts, desktop/network; confirm baseline.
4. Boot normal UKI; run verify. Kernel/systemd-boot update with KDBX; old signed
   recovery remains available during failed builds/APT/signing/promotion.
5. Deliberately break root, boot recovery, roll back; verify home unchanged and
   broken root preserved. Test low space/interrupted rollback from live media.
6. Create more than three recovery candidates; pinned baseline survives. Test
   cleanup and ESP reserve with actual UKI sizes and kernel package artifacts.
7. Unattended security run: allowed security userspace only, pre-snapshot, shared
   locking, no reboot, no unsigned boot writes; deferred boot updates visible.
8. Firmware capsule update, reinstall with matching keys, key rotation/reset,
   external recovery boot and ESP repair on real Dell hardware.
9. Select Workstation Sway at LightDM login; verify `SSH_AUTH_SOCK` is inherited
   by terminals and KeePassXC. Enable agent integration for a protected key and
   verify unlock adds it, lock removes it, and logout stops the session agent.
   Mount the backup USB and test encrypted local Vorta backup/restore without SSH.

These gates are not replaced by passing static/unit tests. Record VM/hardware
results before describing the design as proven for daily use.
