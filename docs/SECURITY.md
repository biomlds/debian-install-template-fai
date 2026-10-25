# Security boundary

Public Git, CI, ISO, archives, logs, and build artifacts contain policy/code only.
KDBX, passwords/hashes, private keys, and populated per-install config are excluded.
No GitHub secrets are required to build. The build scans both ISO contents and
decompressed squashfs roots; repository scans include generic PKCS#8 key payloads.

The installer reads encrypted KDBX from root-owned mode-0600 ext4 removable media.
The master is read without echo and supplied to KeePassXC on stdin. Private
signing keys/LUKS input remain under root-only tmpfs; subprocess errors suppress
captured secret-tool output. Intended SSH identity files persist inside LUKS;
Secure Boot private keys and LUKS keyfiles do not. Cleanup cannot guarantee erasure
of every RAM copy; power off untrusted installation sessions after use.

Signed UKIs bind the kernel, initramfs and command line. Secure Boot does not
authenticate all mutable Btrfs userspace or prevent an already privileged OS from
tampering with snapshots/state. Protected means excluded from automatic cleanup,
not immutable against root or disk damage. Use full-disk encryption, offline
backups, and firmware access controls appropriate to your machine.

Only a recovery entry that has actually booted and been explicitly confirmed is
the pinned known-good baseline. A successful signature alone is not evidence of a
working OS. Automated updates cannot create newly signed recovery UKIs without
the offline key; they retain the existing tested baseline.

Security-only unattended upgrades defer boot-stack packages, never reboot, and
create ordinary pre-transaction snapshots. Check service failures and deferred
security fixes routinely. Run boot-stack upgrades through `workstation-update`.

Read SECURE_BOOT.md for enrollment and VALIDATION.md for outstanding real-machine
acceptance gates. No absolute always-boot guarantee covers hardware/firmware or
shared-disk failure.
