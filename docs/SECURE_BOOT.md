# Secure Boot and signed recovery

## Offline preparation

Build pinned sbctl 0.18 with `tools/build-host-tools.sh` on a trusted machine.
Use its `create-keys --help` and a private tmpfs-backed workspace to generate the
PK, KEK, and db hierarchy and GUID, for example:

```bash
umask 077
mkdir -m 700 /run/private-sbctl
sbctl create-keys --export /run/private-sbctl/keys --database-path /run/private-sbctl/GUID
```

Attach each key/certificate and GUID to the SecureBoot entry described in
[KEEPASSXC.md](KEEPASSXC.md). Back up the database; remove transient exported
private keys. The installer never generates a permanent signing hierarchy.

For first enrollment, enter firmware Setup Mode using the manufacturer's custom
key controls. Know how to restore factory keys first. The installer signs boot
artifacts before `sbctl enroll-keys -m`, verifies enrollment, and does not use
force/immutable-bypass flags. Microsoft certificates are included for supported
third-party/firmware boot components. Existing matching keys permit reinstall;
foreign keys abort before partitioning.

The FAI ISO itself may not boot with your custom Secure Boot policy. Disable
Secure Boot temporarily when booting external recovery media, then re-enable it
after signed artifacts are restored. Test this procedure on the Dell 5490.

## Installed commands

```bash
sudo workstation-secureboot status
sudo workstation-secureboot check
sudo workstation-secureboot snapshot --database /private/Workstation.kdbx
sudo workstation-update --database /private/Workstation.kdbx
```

`snapshot` publishes an untested signed recovery candidate. Boot its numbered
entry from systemd-boot, exercise the desktop and peripherals, then run:

```bash
sudo workstation-secureboot confirm
```

Confirmation requires the recovery overlay boot, checks its signature/hash and
mounts, and pins that snapshot in the real writable root's registry. Automated
checks do not replace testing the applications you need. Three protected entries
are retained, reserving the last boot-tested baseline; `important=yes` is not used
as a cleanup exemption.

`workstation-update` signs a recovery entry before `apt-get full-upgrade`, then
signs/publishes the new normal UKI and systemd-boot. Debian loader hooks are
diverted, kernel-install ESP writers overridden, and the bootloader update
service masked. Package kernel files can change, but unsigned UKIs are not
published. Normal and previous signed UKIs are separate from snapshot recovery.

Direct APT boot-stack changes are marked pending by kernel hooks. Complete them
with `workstation-update`; use `workstation-secureboot sign --database ...` only
for explicit re-signing with intact recovery artifacts. Use
`workstation-secureboot repair --database ...` to reconstruct a lost/damaged ESP
from saved kernel archives; see [Recovery](RECOVERY.md). Existing installations
without a deployed-loader checksum can establish it through `sign` after updating
the maintenance helper. Checks compare both deployed loader copies against that
checksum as well as verifying their signatures. No signing key is kept in
`/var/lib/sbctl`. UKI building uses dracut and `/usr/lib/systemd/ukify` explicitly;
kernel-install automatic publication is disabled with `layout=other`.

## Automatic security maintenance

`workstation-security-upgrade.timer` invokes unattended-upgrade under the same
maintenance lock after creating a cleanup-managed root snapshot. It allows only
Debian-Security/trixie-security. Kernel, dracut, cryptsetup, bootloader, signing,
microcode, and firmware packages are deferred to the manual signing workflow.
systemd core security fixes remain eligible when dependencies permit. Automatic
reboot and automatic kernel removal are disabled. A missing boot-tested baseline
or failed snapshot defers the transaction rather than running unprotected.

Inspect failures with `systemctl --failed`,
`journalctl -u workstation-security-upgrade.service`, and
`journalctl -u workstation-uki-check.service`. Check deferred security packages
regularly with `apt list --upgradable`; apply them through `workstation-update`.

Actual Secure Boot, firmware-capsule signing, power-loss behavior, and recovery
overlay boot remain hardware/OVMF acceptance tests; see VALIDATION.md.
