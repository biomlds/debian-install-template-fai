#!/usr/bin/env python3
"""Integration contracts for the FAI config space and credential-free CI."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "fai/config"


class Configuration(unittest.TestCase):
    def test_keepassxc_uses_session_agent_and_borg_is_local(self):
        session = self.text("files/usr/local/bin/workstation-sway/SWAY")
        self.assertIn("exec ssh-agent /usr/local/libexec/workstation-sway-session", session)
        inner = self.text("files/usr/local/libexec/workstation-sway-session/SWAY")
        self.assertIn("dbus-update-activation-environment --systemd SSH_AUTH_SOCK SSH_AGENT_PID", inner)
        self.assertIn("exec sway", inner)
        self.assertIn("exec keepassxc", self.text("files/etc/sway/config.d/90-workstation-keepassxc.conf/SWAY"))
        inputs = self.text("assets/workstation/kdbx.py")
        self.assertNotIn("borg_ed25519", inputs)
        self.assertNotIn("BORG_RSH", inputs)

    def text(self, path):
        return (CFG / path).read_text()

    def test_preflight_before_destruction(self):
        hook = self.text("hooks/partition.WORKSTATION.sh")
        self.assertLess(hook.index('kdbx.py" preflight'), hook.index('"$selector" select'))
        self.assertLess(hook.index('"$selector" revalidate'), hook.index("setup-storage -X"))
        self.assertIn("/sys/firmware/efi", hook)
        # FAI treats hook failures as log-only and then runs default
        # partitioning, so every failure must suppress task_partition.
        self.assertIn("trap abort_partition EXIT", hook)
        self.assertIn('touch "$LOGDIR/skip.partition" "$LOGDIR/workstation-partition-failed"', hook)
        self.assertIn('workstation-partition-failed', self.text("class/20-bootstrap"))
        # A checkout without the executable bit must not skip the prompt.
        self.assertIn('python3 "$selector" select', hook)
        self.assertIn("-s \"$WORKSTATION_SECRETS/identity.json\"", hook)
        # .sh hooks are sourced, so die() can stop FAI instead of falling through.
        self.assertIn("die \"Workstation preflight", hook)
        self.assertIn("if ! ( partition_workstation )", hook)
        self.assertIn("mounted KDBX media", hook)
        # Retrying in the same live session leaves /target mounted and makes a
        # second setup-storage regenerate keys under an open mapper.
        self.assertIn('mountpoint -q "$target"', hook)
        self.assertIn("Reboot the installer before retrying", hook)
        self.assertIn("STOP_ON_ERROR=0", self.text("class/WORKSTATION.var"))

    def test_luks_setup_key_survives_crypttab_rewrite(self):
        hook = self.text("hooks/partition.WORKSTATION.sh")
        # Persist the key bytes, not the path text, or cryptsetup treats the
        # path as a passphrase and the bootstrap slot can never unlock.
        self.assertIn('install -m 0600 "$setup_key_path" "$LOGDIR/luks-setup-key"', hook)
        self.assertNotIn('> "$LOGDIR/luks-setup-key"', hook)
        luks = self.text("scripts/LUKS_BTRFS/10-luks-key")
        self.assertIn('setup_key=$LOGDIR/luks-setup-key', luks)
        self.assertLess(luks.index("luks-setup-key"), luks.index("[ -s \"$setup_key\" ]"))
        self.assertIn("cryptroot UUID=%s none luks", luks)

    def test_storage_contract(self):
        disk = self.text("disk_config/LUKS_BTRFS")
        self.assertRegex(disk, r"p=efi\s+/boot\s+2G\s+vfat")
        self.assertIn("--pbkdf=argon2id", disk)
        hook = self.text("hooks/partition.WORKSTATION.sh")
        self.assertIn('disklist=${disklist#/dev/}', hook)
        self.assertIn('setup-storage -X -f "$config" -D "$disklist"', hook)
        mount = self.text("hooks/mountdisks.LUKS_BTRFS")
        for name in ("@root", "@home", "@snapshots"):
            self.assertIn(name, mount)
        self.assertNotIn("/boot/efi", mount)
        # FAI's task_mountdisks runs mount2dir on our fstab. Mounting the same
        # entries in the hook overmounts them and duplicates every findmnt line.
        self.assertNotIn('mount -o noatime,compress=zstd:3,subvol=@root "$mapper" "$target"', mount)
        self.assertNotIn('mount -o umask=0077 "$efi_device" "$target/boot"', mount)
        self.assertIn("UUID=$efi_uuid  /boot", mount)
        luks = self.text("scripts/LUKS_BTRFS/10-luks-key")
        self.assertIn("luksAddKey --pbkdf argon2id", luks)
        self.assertIn("fewer than two active slots", luks)
        self.assertNotIn("state_dir=", luks)

    def test_selected_esp_guard(self):
        setup = self.text("scripts/SYSTEMD_BOOT/10-setup")
        for token in ("FAI_SELECTED_BOOT_STABLE", "BOOT_DEVICE", "efi_disk", "Mounted ESP is not on selected"):
            self.assertIn(token, setup)
        # A stale /dev path made lsblk exit 32 and abort configure; resolve the
        # parent disk from the mounted device's sysfs MAJ:MIN instead.
        self.assertIn('findmnt -rn -o MAJ:MIN', setup)
        self.assertIn("awk '{print $1}'", setup)
        self.assertIn("sort -u", setup)
        self.assertIn("efi_majmin=${efi_majmins%%", setup)
        self.assertNotIn("efi_majmins=$(printf", setup)
        self.assertIn("ESP is mounted from multiple devices", setup)
        self.assertIn('readlink "/sys/dev/block/$efi_majmin"', setup)
        self.assertIn("is absent from sysfs", setup)
        self.assertIn("Cannot resolve the mounted ESP device", setup)
        self.assertNotIn('lsblk -sno PATH,TYPE "$efi_source"', setup)
        # These guards previously exited silently, hiding the failing comparison.
        for message in ("requires a single disk", "boot stable path does not resolve", "does not match the selected bootloader disk"):
            self.assertIn(message, setup)

    def test_target_no_grub_or_firstboot(self):
        self.assertFalse((CFG / "package_config/GRUB_EFI").exists())
        self.assertFalse((CFG / "scripts/WORKSTATION/10-provision-user").exists())
        self.assertIn("SYSTEMD_BOOT FINAL", self.text("class/50-host-classes"))
        final = self.text("scripts/FINAL/99-finalize")
        self.assertNotIn("update-grub", final)
        self.assertIn("workstation-security-upgrade.timer", final)
        self.assertIn('"$FAI/assets/workstation/kdbx.py" cleanup', final)
        self.assertLess(final.index("mkramdisk -au"), final.index("workstation-secureboot install"))
        self.assertLess(final.index("fai-divert -R"), final.index("workstation-secureboot install"))
        self.assertIn("dpkg-divert --list fai", final)
        self.assertIn("dpkg-divert --local", self.text("scripts/SYSTEMD_BOOT/10-setup"))
        self.assertLess(final.index("systemctl enable ssh.service"), final.index("workstation-secureboot install"))

    def test_unattended_policy(self):
        policy = self.text("files/etc/apt/apt.conf.d/52workstation-security/SYSTEMD_BOOT")
        self.assertIn("#clear Unattended-Upgrade::Allowed-Origins;", policy)
        self.assertIn("label=Debian-Security,codename=trixie-security", policy)
        patterns = re.findall(r'"(\^[^"]+)";', policy)
        for package in ("linux-image-amd64", "linux-image-6.12.0-amd64", "systemd-boot-efi", "systemd-ukify", "dracut-core", "cryptsetup-bin", "libcryptsetup12", "fwupd", "intel-microcode"):
            self.assertTrue(any(re.search(pattern, package) for pattern in patterns), package)
        self.assertFalse(any(re.search(pattern, "systemd") for pattern in patterns))
        self.assertIn('Automatic-Reboot "false"', policy)

    def test_apt_snapshot_hook_and_recovery_helper_layout(self):
        for path in (
            "files/usr/local/sbin/workstation-recover/SYSTEMD_BOOT",
            "files/usr/local/sbin/workstation-apt-snapshot/SYSTEMD_BOOT",
            "files/etc/apt/apt.conf.d/70workstation-hooks/SYSTEMD_BOOT",
            "files/usr/local/share/workstation/recovery/README.md/SYSTEMD_BOOT",
        ):
            self.assertTrue((CFG / path).is_file(), path)
        setup = self.text("scripts/SYSTEMD_BOOT/10-setup")
        self.assertIn("fcopy -riM /usr/local/sbin", setup)
        self.assertIn("fcopy -riM /usr/local/share/workstation", setup)
        self.assertNotIn("install -m 755 /usr/local/sbin/workstation-recover", setup)
        self.assertNotIn("apt-snapshot.service", setup)
        hook = self.text("files/usr/local/sbin/workstation-apt-snapshot/SYSTEMD_BOOT")
        self.assertIn("/run/workstation-maintenance.lock", hook)
        self.assertIn("flock -n 9", hook)
        self.assertIn("set +e", hook)
        self.assertNotIn("set -e", hook.replace("set +e", ""))
        apt = self.text("files/etc/apt/apt.conf.d/70workstation-hooks/SYSTEMD_BOOT")
        self.assertEqual(apt.count("DPkg::Pre-Invoke"), 1)
        self.assertNotIn("Post-Invoke", apt)
        # task_repository copies /etc/apt before instsoft, while the helper is
        # only installed at configure time; the call must no-op when missing.
        self.assertIn("-x /usr/local/sbin/workstation-apt-snapshot", apt)
        self.assertIn("then /usr/local/sbin/workstation-apt-snapshot", apt)

    def test_stub_sources_list_prevents_duplicates(self):
        stub = self.text("files/etc/apt/sources.list/TRIXIE")
        self.assertFalse(any(re.match(r"\s*(deb|Types:)", line) for line in stub.splitlines()))
        sources = self.text("files/etc/apt/sources.list.d/debian.sources/TRIXIE")
        self.assertIn("URIs: https://deb.debian.org/debian", sources)

    def test_vm_and_flatpak_retained(self):
        incus = self.text("assets/incus/scripts/create.sh")
        self.assertIn(" --vm ", incus)
        self.assertLess(incus.index("incus init"), incus.index('incus start "$name"'))
        flatpak = self.text("files/usr/local/sbin/workstation-flatpaks/FLATPAK_APPS")
        self.assertIn("flatpak install --system --noninteractive --or-update", flatpak)

    def test_iso_workflow(self):
        workflow = (ROOT / ".github/workflows/build-iso.yml").read_text()
        self.assertIn("./tools/build-host-tools.sh --native", workflow)
        self.assertIn("./tools/build-iso.sh", workflow)
        self.assertIn("make validate manifest-check", workflow)
        self.assertNotRegex(workflow, r"\$\{\{\s*secrets\.")
        build = (ROOT / "tools/build-iso.sh").read_text()
        self.assertIn("/sbctl", build)
        self.assertIn('scan-public.py" --images', build)
        self.assertIn("chroot /srv/fai/nfsroot keepassxc-cli", build)
        self.assertIn("fai-make-nfsroot -v -f", build)
        self.assertIn("file:///var/lib/fai/config", (ROOT / "server/fai.conf.example").read_text())


if __name__ == "__main__":
    unittest.main()
