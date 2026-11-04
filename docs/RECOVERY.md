# Recovery

## Broken normal OS after an update

Choose a numbered **Recovery snapshot** entry in the visible systemd-boot menu.
It boots the saved root with its matching kernel/initramfs and a writable tmpfs
overlay. Changes to root are discarded at reboot; `/home` remains shared and
writable. RAM limits apply, so avoid large installs while in recovery.

To keep a recovered root permanently:

```bash
sudo workstation-secureboot status
sudo workstation-rollback NUMBER --database /private/Workstation.kdbx
```

Rollback must run from recovery, refuses a mounted active `@root`, clones the
selected protected snapshot, preserves the broken root as `@root-broken-*`, and
publishes a signed normal UKI and both signed bootloader copies from the restored
root. Reboot manually. Do not delete the broken root until
you have checked the restored system and recovered any required root data.

An interrupted rollback can leave `@root-rollback-candidate` or a renamed broken
root. Use live media, unlock LUKS, mount Btrfs `subvolid=5`, and inspect before
renaming or deleting anything. If no `@root` exists, restore the saved broken-root
name or clone a protected snapshot to `@root`; do not overwrite existing roots.
The recovery UKI still selects its snapshot independently of the `@root` name.

## Lost/broken ESP or firmware entry

Boot external UEFI recovery media (temporarily disable Secure Boot if necessary),
unlock LUKS, mount `@root`, `@home`, `@snapshots` and ESP at their usual locations,
bind proc/sys/dev/run, and chroot. Restore systemd-boot/UKIs with offline KDBX and
`workstation-secureboot repair --database /private/Workstation.kdbx`.
Repair uses the kernel/initramfs archives on the encrypted root, so it also works
with an empty ESP. It restores both signed bootloader copies, the normal UKI,
registered recovery UKIs and loader configuration, and updates `/etc/fstab` for
the mounted ESP UUID. Rebuilt recovery images whose bytes change lose their
boot-tested status: boot and confirm a recovery entry again before unattended
updates can resume. Repair preserves any pending boot-stack-change marker;
finish pending updates with `workstation-update` after restoring a baseline.
Register the EFI entry with efibootmgr as needed.
Do not run an unsigned bootctl update over working signed files.

The `workstation-recover` helper selects only a FAT GPT EFI System Partition on
the same physical disk as the selected LUKS device. If multiple ESPs exist there,
it prompts for a choice and validates it before mounting. A label alone is never
used to select an ESP.

## Missing signing keys or changed firmware keys

Existing signed UKIs can boot while their certificate is trusted. Without private
keys you cannot sign replacements. Recover the offline KDBX backup or generate a
new hierarchy, reset firmware to Setup Mode, and re-sign/re-enroll from trusted
media. Factory-key reset may stop trusting the existing workstation UKIs.
Record/test the Dell 5490 factory-key restore procedure before enrolling.

## Space and backups

The tool refuses maintenance when the ESP/root reserve is low. Retain the pinned
known-good entry; remove only reviewed unneeded candidates or restore from live
media. Snapper ordinary snapshots are not signed menu entries. A lost disk, LUKS
header/passphrase, firmware failure, or corrupted shared home cannot be fixed by
an on-disk root snapshot. Keep Borg backups, a private LUKS-header backup, two
offline KDBX copies, and tested external recovery media.
