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
        self.assertLess(hook.index('touch "$LOGDIR/skip.partition"'), hook.index('kdbx.py" preflight'))
        self.assertIn("STOP_ON_ERROR=0", self.text("class/WORKSTATION.var"))

    def test_storage_contract(self):
        disk = self.text("disk_config/LUKS_BTRFS")
        self.assertRegex(disk, r"p=efi\s+/boot\s+2G\s+vfat")
        self.assertIn("--pbkdf=argon2id", disk)
        mount = self.text("hooks/mountdisks.LUKS_BTRFS")
        for name in ("@root", "@home", "@snapshots"):
            self.assertIn(name, mount)
        self.assertNotIn("/boot/efi", mount)
        luks = self.text("scripts/LUKS_BTRFS/10-luks-key")
        self.assertIn("luksAddKey --pbkdf argon2id", luks)
        self.assertIn("fewer than two active slots", luks)
        self.assertNotIn("state_dir=", luks)

    def test_selected_esp_guard(self):
        setup = self.text("scripts/SYSTEMD_BOOT/10-setup")
        for token in ("FAI_SELECTED_BOOT_STABLE", "BOOT_DEVICE", "efi_disk", "Mounted ESP is not on selected"):
            self.assertIn(token, setup)

    def test_target_no_grub_or_firstboot(self):
        self.assertFalse((CFG / "package_config/GRUB_EFI").exists())
        self.assertFalse((CFG / "scripts/WORKSTATION/10-provision-user").exists())
        self.assertIn("SYSTEMD_BOOT FINAL", self.text("class/50-host-classes"))
        final = self.text("scripts/FINAL/99-finalize")
        self.assertNotIn("update-grub", final)
        self.assertIn("workstation-security-upgrade.timer", final)
        self.assertIn('"$FAI/assets/workstation/kdbx.py" cleanup', final)
        self.assertLess(final.index("mkramdisk -au"), final.index("workstation-secureboot install"))
        self.assertNotIn("fai-divert -R", final)
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
