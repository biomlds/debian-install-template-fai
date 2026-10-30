# FAI installer

`server/NFSROOT` defines the installer root embedded by `fai-cd`. It is needed even
for an offline ISO. It contains partitioning tools, dracut live support, KeePassXC
CLI, kbd/dbus, and sbctl runtime libraries. GRUB/shim packages here may support the
ISO boot; they are separate from target package classes.

1. Boot amd64 UEFI. `20-bootstrap` locates read-only ext4 KDBX media.
2. `partition.WORKSTATION` repeats UEFI checks, unlocks KDBX, validates identity and
   Secure Boot keys, and checks Setup Mode/matching enrolled keys.
3. Interactive disk selection excludes installation media, checks stable identity,
   requires `ERASE <identifier>`, and revalidates before setup-storage.
4. setup-storage creates GPT/ESP/LUKS. The mount hook creates Btrfs subvolumes.
5. Class scripts install permanent identity, replace the temporary LUKS slot,
   configure Snapper, desktop/backup assets, and systemd-boot controls.
6. FINAL verifies the selected ESP backing disk, signs UKIs/bootloaders, enrolls
   keys, registers Linux Boot Manager, enables timers, and removes tmpfs inputs.

Class-script failure alone does not stop all FAI paths, so the destructive hook
must independently validate prerequisites. No kernel-command-line disk override
is supported. Use `tools/preview-install.sh` for read-only selection testing.

Retry only after rebooting the installer. An aborted run leaves `/target` and its
subvolumes mounted; running FAI again regenerates the temporary LUKS key while the
previous mapper remains open, so neither the setup key nor the permanent credential
unlocks and `findmnt`/`lsblk` report stale paths. The partition hook refuses to
start when `/target` or `/target/boot` is still mounted.

Do not use BIOS/SeaBIOS/CSM: Proxmox needs q35, OVMF, and an EFI disk. Keep KDBX on
a separate small ext4 disk. For console access use FAI's createvt/verbose flags
without inserting credentials in the boot command line.

Build in a disposable privileged Debian trixie environment. The builder refreshes
NFSROOT by default; `FAI_REUSE_NFSROOT=1` explicitly opts into reuse. Local log
collection does not assume an NFS/SSH log server. FAI logs never include secrets.
