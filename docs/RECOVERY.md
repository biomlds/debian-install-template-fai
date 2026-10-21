# Recovery

## Installation disk selection

Disk selection does not change disks until the exact `ERASE <selected-identifier>` phrase is accepted and final identity revalidation passes. If selection aborts, correct the ambiguity or mount state and restart the FAI partition task; do not bypass the filter. Review `disk-selection.log` in FAI logs. After a successful installation, the public selection record is retained at `/var/log/fai/disk-selection.json` and can help correlate the installed system with the original model, serial, WWN, and stable path.

If the local FAI medium cannot be distinguished, use known-good installation media or verified PXE/NFS/HTTP boot. Do not use the test-only VM override on physical hardware.

## First-boot interruption

Run `sudo workstation-firstboot status`. Correct the reported source or system issue and rerun the same `apply` command. Do not manually delete LUKS slots based only on numbers; slot identity is verified by test-passphrase.

If status says the temporary key is missing while no permanent slot matches, stop and boot trusted rescue media. Use an independently stored LUKS recovery credential. Do not reboot after a post-removal verification failure until a known credential is tested.

## Btrfs root rollback

Boot trusted rescue media, identify the encrypted partition by stable ID, and use a known recovery credential:

```bash
sudo cryptsetup open /dev/disk/by-id/REPLACE_LUKS_PARTITION cryptroot
sudo mount -o subvolid=5 /dev/mapper/cryptroot /mnt
sudo mv /mnt/@root /mnt/@root.failed.$(date -u +%Y%m%dT%H%M%SZ)
sudo btrfs subvolume snapshot /mnt/@snapshots/NUMBER/snapshot /mnt/@root
root_id=$(sudo btrfs subvolume show /mnt/@root | awk -F': *' '/Subvolume ID:/ {print $2; exit}')
sudo btrfs subvolume set-default "$root_id" /mnt
sudo umount /mnt
sudo cryptsetup close cryptroot
```

Keep the old root until boot and application checks pass. `@home` is not rolled back. After initial setup, back up the LUKS2 header to separate encrypted/removable storage with `cryptsetup luksHeaderBackup`; a header backup is sensitive and must not live only on the protected disk.

## GRUB

If authenticated entries are malformed, boot trusted rescue media, unlock/mount root and ESP, chroot, inspect `/etc/grub.d/01_workstation_users`, then run `update-grub` followed by `/usr/local/sbin/update-grub-secure`. Never replace the hash with plaintext.

## Lost KeePassXC/Borg access

Use the separately stored database/Borg recovery package described in BACKUP.md. Both first-boot sources support removable media; YAML is the fallback when KeePassXC is unavailable.
