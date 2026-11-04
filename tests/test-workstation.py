#!/usr/bin/env python3
"""Failure-oriented tests for recovery retention, publication and private input."""
import importlib.util
import contextlib
import hashlib
import json
import os
import sys
import tempfile
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fai/config/assets/workstation"))
import boot
import kdbx
import recovery


class RecoveryTests(unittest.TestCase):
    def test_recovery_esp_never_selects_other_disk_or_ambiguous_partition(self):
        nodes = [
            {"path": "/dev/sda", "type": "disk"},
            {"path": "/dev/sdb", "type": "disk"},
            {"path": "/dev/sda2", "type": "part", "pkname": "/dev/sda", "fstype": "crypto_LUKS"},
            {"path": "/dev/sda1", "type": "part", "pkname": "/dev/sda", "fstype": "vfat", "parttype": recovery.ESP_TYPE},
            {"path": "/dev/sdb1", "type": "part", "pkname": "/dev/sdb", "fstype": "vfat", "parttype": recovery.ESP_TYPE},
        ]
        self.assertEqual(recovery.select_esp(nodes, "/dev/sda2"), "/dev/sda1")
        with self.assertRaises(RuntimeError):
            recovery.select_esp(nodes, "/dev/sda2", "/dev/sdb1")
        nodes.append({**nodes[3], "path": "/dev/sda3"})
        with self.assertRaises(RuntimeError):
            recovery.select_esp(nodes, "/dev/sda2")
        self.assertEqual(recovery.select_esp(nodes, "/dev/sda2", "/dev/sda3"), "/dev/sda3")

    def test_partition_failures_stop_before_destructive_command(self):
        hook = ROOT / "fai/config/hooks/partition.WORKSTATION.sh"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ("assets/disk-selection", "disk_config", "logs", "secrets"):
                (base / name).mkdir(parents=True)
            for name in ("assets/disk-selection/disk_selector.py", "disk_config/LUKS_BTRFS",
                         "secrets/identity.json", "secrets/luks"):
                (base / name).write_text("fixture")
            # Stale records must never allow a failed selection to proceed.
            (base / "logs/disk-selection.env").write_text(
                "disklist=reviewfake\nBOOT_DEVICE=/dev/reviewfake\n"
                "PHYSICAL_BOOT_DEVICES=/dev/reviewfake\nFAI_SELECTED_BOOT_KERNEL=/dev/reviewfake\n")
            script = r'''
mountpoint() { return 1; }
uname() { builtin printf x86_64; }
python3() { if [ "$2" = "$FAIL_AT" ]; then return 23; fi; return 0; }
findmnt() { return 1; }
blockdev() { builtin printf 21474836480; }
setup-storage() { builtin printf 'DESTRUCTIVE_COMMAND\n'; return 99; }
[() {
    if builtin [ "$1" = -b ]; then return 0; fi
    if builtin [ "$*" = '! -d /sys/firmware/efi ]' ]; then return 1; fi
    builtin [ "$@"
}
die() { exit 42; }
source "$HOOK"
'''
            for failure in ("preflight", "select", "revalidate"):
                with self.subTest(failure=failure):
                    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                        env={**os.environ, "FAI": str(base), "LOGDIR": str(base / "logs"),
                             "WORKSTATION_SECRETS": str(base / "secrets"), "target": str(base / "target"),
                             "HOOK": str(hook), "FAIL_AT": failure})
                    self.assertEqual(result.returncode, 42, result.stderr)
                    self.assertNotIn("DESTRUCTIVE_COMMAND", result.stdout)
                    self.assertTrue((base / "logs/skip.partition").exists())

    def test_nfsroot_retry_preserves_failure_status(self):
        text = (ROOT / "tools/build-iso.sh").read_text()
        function = text[text.index("retry_n() {"):text.index('if [ "${FAI_REUSE_NFSROOT')]
        for command, expected in (("false", 1), ("true", 0)):
            result = subprocess.run(["bash", "-c", function + f'\nsleep() {{ :; }}\nretry_n 2 {command}'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, expected)

    def test_bootloader_rollback_signs_candidate_and_tracks_deployed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            candidate = base / "candidate"
            source = candidate / "usr/lib/systemd/boot/efi/systemd-bootx64.efi"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"old-root-loader")
            state, esp = base / "state", base / "esp"

            def sign(source, destination, keys):
                boot.atomic(destination, b"signed:" + source.read_bytes())

            with patch.object(boot, "STATE", state), patch.object(boot, "ESP", esp), patch.object(boot, "sign", side_effect=sign):
                loader, source_hash = boot.stage_bootloader(base, candidate)
                boot.publish_bootloader(loader, source_hash, candidate / "var/lib/workstation-uki")
            for name in ("EFI/systemd/systemd-bootx64.efi", "EFI/BOOT/BOOTX64.EFI"):
                self.assertEqual((esp / name).read_bytes(), b"signed:old-root-loader")
            saved = candidate / "var/lib/workstation-uki"
            self.assertEqual((saved / "boot-source.sha256").read_text(), boot.hash_file(source))
            self.assertEqual((saved / "boot-deployed.sha256").read_text(), boot.hash_file(loader))

    def test_rollback_stages_loader_before_root_swap_and_publishes_it(self):
        with tempfile.TemporaryDirectory() as directory:
            top = Path(directory)
            working = top / "@root"
            state_path = working / "var/lib/workstation-uki/state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps({"known_good": 7, "protected": [{"id": 7}]}))
            (working / "identity").write_text("original-root")
            signed = top / "state/staged/rollback-signed.efi"
            loader = top / "signed-loader"
            loader.write_bytes(b"restored-loader")

            @contextlib.contextmanager
            def mount_top():
                yield top

            def command(*args):
                if args[:3] == ("btrfs", "subvolume", "snapshot"):
                    (top / "@root-rollback-candidate").mkdir()
                return ""

            def sign(source, destination, keys):
                boot.atomic(destination, b"signed-uki")

            with patch.object(boot, "STATE", top / "state"), patch.object(boot, "ESP", top / "esp"), \
                 patch.object(boot, "LINUX", top / "esp/EFI/Linux"), patch.object(boot, "top_level", mount_top), \
                 patch.object(boot, "recovery_id", return_value=7), patch.object(boot, "run", side_effect=command), \
                 patch.object(boot, "kernel_archive", return_value=top), patch.object(boot, "base_cmdline", return_value="root=test"), \
                 patch.object(boot, "update_esp_fstab"), \
                 patch.object(boot, "build_uki", return_value=signed), patch.object(boot, "sign", side_effect=sign), \
                 patch.object(boot, "stage_bootloader", side_effect=RuntimeError("loader signing failed")) as stage:
                with self.assertRaisesRegex(RuntimeError, "loader signing failed"):
                    boot.rollback(7, top)
                self.assertEqual((working / "identity").read_text(), "original-root")
                self.assertEqual(list(top.glob("@root-broken-*")), [])
                shutil.rmtree(top / "@root-rollback-candidate")
                stage.side_effect = None
                stage.return_value = loader, "restored-source-hash"
                boot.rollback(7, top)
            self.assertEqual(len(list(top.glob("@root-broken-*"))), 1)
            self.assertEqual((top / "esp/EFI/BOOT/BOOTX64.EFI").read_bytes(), b"restored-loader")
            self.assertEqual((working / "var/lib/workstation-uki/boot-source.sha256").read_text(),
                             "restored-source-hash")

    def test_vm_bootstrap_rejects_download_failure_and_checksum_mismatch(self):
        for role in ("dev", "bio", "ai"):
            text = (ROOT / f"fai/config/assets/incus/templates/{role}/bootstrap.sh").read_text()
            install = text[text.index("mise_binary=$(mktemp)"):text.index("cat >> /home/dev/.bashrc")]
            # Never run real download/install commands in this failure test.
            for failure in ("download", "checksum"):
                with self.subTest(role=role, failure=failure):
                    script = '''set -Eeuo pipefail
uname() { builtin printf x86_64; }
curl() { if [ "$FAIL_AT" = download ]; then return 22; fi; return 0; }
sha256sum() { return 1; }
install() { builtin printf 'UNVERIFIED_INSTALL'; }
''' + install
                    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                            env={**os.environ, "FAIL_AT": failure})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("UNVERIFIED_INSTALL", result.stdout)

    def test_baseline_stops_when_fai_diversions_cannot_be_restored(self):
        text = (ROOT / "fai/config/scripts/FINAL/99-finalize").read_text()
        before_snapshot = text[:text.index("fcopy -riM /etc/systemd/system")]
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "disk-selection.env").touch()
            for failure in ("restore", "remaining"):
                script = '''mkramdisk() { return 0; }
fai-divert() { if [ "$FAIL_AT" = restore ]; then return 1; fi; return 0; }
rootcmd() { builtin printf 'diversion of /usr/sbin/example by fai'; }
''' + before_snapshot + "\nbuiltin printf 'BASELINE_ALLOWED'\n"
                result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                    env={**os.environ, "LOGDIR": directory, "ROOTCMD": "rootcmd", "FAIL_AT": failure})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("BASELINE_ALLOWED", result.stdout)

    def test_repair_rebuilds_empty_esp_and_invalidates_changed_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            esp, state_dir = base / "esp", base / "state"
            fstab = base / "fstab"
            fstab.write_text("UUID=old /boot vfat umask=0077 0 1\n")
            state = {"schema": 1, "known_good": 7,
                     "protected": [{"id": 7, "sha256": "old", "boot_tested": True}]}
            staged = base / "unsigned"
            staged.write_bytes(b"uki")
            (base / "vmlinuz").write_bytes(b"saved-kernel")
            loader = base / "loader"
            loader.write_bytes(b"signed-loader")

            def sign(source, destination, keys):
                boot.atomic(destination, b"signed:" + source.read_bytes())

            def publish(number, keys):
                path = esp / f"EFI/Linux/ws-protected-{number}.efi"
                boot.atomic(path, b"rebuilt-recovery")
                return path

            with patch.object(boot, "STATE", state_dir), patch.object(boot, "ESP", esp), \
                 patch.object(boot, "LINUX", esp / "EFI/Linux"), patch.object(boot, "FSTAB", fstab), \
                 patch.object(boot, "normal_root"), patch.object(boot, "load_state", return_value=state), \
                 patch.object(boot, "kernel_archive", return_value=base), patch.object(boot, "base_cmdline", return_value="root=test"), \
                 patch.object(boot, "build_uki", return_value=staged), patch.object(boot, "sign", side_effect=sign), \
                 patch.object(boot, "stage_bootloader", return_value=(loader, "source-hash")), \
                 patch.object(boot, "publish_recovery", side_effect=publish), patch.object(boot, "run", return_value="new-esp"), \
                 patch.object(boot, "check", side_effect=AssertionError("Cannot require existing artifacts")):
                boot.repair(base)
            self.assertTrue((esp / "EFI/Linux/debian.efi").is_file())
            self.assertTrue((esp / "EFI/BOOT/BOOTX64.EFI").is_file())
            self.assertTrue((esp / "loader/loader.conf").is_file())
            self.assertIn("UUID=new-esp", fstab.read_text())
            actual = json.loads((state_dir / "state.json").read_text())
            self.assertIsNone(actual["known_good"])
            self.assertFalse(actual["protected"][0]["boot_tested"])

    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen unavailable")
    def test_protected_ssh_keys_match_without_decrypting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "id_ed25519"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-a", "4", "-N",
                            "test-only-encryption-passphrase", "-f", str(key)], check=True)
            public = root / "id_ed25519.pub"
            kdbx.validate_ssh_key(key, public)
            other = root / "other"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other)], check=True)
            with self.assertRaisesRegex(RuntimeError, "passphrase-protected"):
                kdbx.validate_ssh_key(other, root / "other.pub")
            with self.assertRaisesRegex(RuntimeError, "mismatch"):
                kdbx.validate_ssh_key(key, root / "other.pub")
            key.write_bytes(b"corrupt")
            with self.assertRaises(RuntimeError):
                kdbx.validate_ssh_key(key, public)

    def test_usb_borg_configuration_has_no_ssh_or_passphrase(self):
        self.assertEqual(kdbx.borg_environment("/media/alex/Backup Drive/borg-repo"),
                         "BORG_REPO='/media/alex/Backup Drive/borg-repo'\n")
        for repository in ("ssh://backup@example/repo", "backup@example:repo", "relative/repo", "/mnt/usb\nsecret"):
            with self.assertRaises(RuntimeError):
                kdbx.borg_environment(repository)

    def test_pinned_baseline_survives_many_updates(self):
        records = [{"id": n} for n in range(1, 12)]
        self.assertEqual(boot.retained(records, 1), {1, 10, 11})

    def test_current_recovery_cannot_be_pruned(self):
        records = [{"id": n} for n in range(1, 12)]
        self.assertEqual(boot.retained(records, 1, 2), {1, 2, 11})

    def test_missing_pinned_baseline_aborts(self):
        with self.assertRaises(RuntimeError):
            boot.retained([{"id": 2}], 1)

    def test_failed_signature_leaves_old_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "working.efi"
            path.write_bytes(b"old-working-boot")
            with patch.object(boot, "run", side_effect=RuntimeError("bad signature")):
                with self.assertRaises(RuntimeError):
                    boot.sign(Path("unsigned"), path, Path(directory))
            self.assertEqual(path.read_bytes(), b"old-working-boot")

    def test_failed_normal_build_leaves_current_and_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            linux = Path(directory)
            (linux / "debian.efi").write_bytes(b"current")
            (linux / "debian-previous.efi").write_bytes(b"previous")
            with patch.object(boot, "LINUX", linux), patch.object(boot, "build_normal", side_effect=RuntimeError("build failed")):
                with self.assertRaises(RuntimeError):
                    boot.publish_normal(Path(directory))
            self.assertEqual((linux / "debian.efi").read_bytes(), b"current")
            self.assertEqual((linux / "debian-previous.efi").read_bytes(), b"previous")

    def test_snapshot_kernel_selection_cannot_escape_directory(self):
        self.assertEqual(boot.recovery_id("ro workstation.snapshot=42 quiet"), 42)
        self.assertIsNone(boot.recovery_id("workstation.snapshot=../../etc"))

    def test_saved_kernel_version_cannot_escape_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "etc/workstation").mkdir(parents=True)
            (root / "etc/workstation/kernel-version").write_text("../../etc")
            with self.assertRaisesRegex(RuntimeError, "Invalid saved kernel"):
                boot.kernel_archive(root)

    def test_first_recovery_confirmation_uses_real_root_registry(self):
        # The snapshot cannot contain its own registration: it was created first.
        # Confirmation must load the live root's newer registry, not overlay state.
        with tempfile.TemporaryDirectory() as directory:
            top = Path(directory)
            path = top / "@root/var/lib/workstation-uki/state.json"
            path.parent.mkdir(parents=True)
            state = {"schema": 1, "known_good": None,
                     "protected": [{"id": 7, "sha256": "expected", "boot_tested": False}]}
            path.write_text(json.dumps(state))

            @contextlib.contextmanager
            def fake_top():
                yield top

            def command(*args):
                return "overlay" if args[0] == "findmnt" and "FSTYPE" in args else ""

            with patch.object(boot, "top_level", fake_top), patch.object(boot, "recovery_id", return_value=7), \
                 patch.object(boot, "secure_boot_enabled"), patch.object(boot, "verify"), \
                 patch.object(boot, "hash_file", return_value="expected"), patch.object(boot, "run", side_effect=command), \
                 patch.object(boot, "load_state", side_effect=AssertionError("stale snapshot registry")):
                boot.confirm()
            actual = json.loads(path.read_text())
            self.assertEqual(actual["known_good"], 7)
            self.assertTrue(actual["protected"][0]["boot_tested"])

    def test_confirmation_rejects_changed_recovery_uki(self):
        with tempfile.TemporaryDirectory() as directory:
            top = Path(directory)
            path = top / "@root/var/lib/workstation-uki/state.json"
            path.parent.mkdir(parents=True)
            state = {"known_good": 1, "protected": [{"id": 7, "sha256": "original", "boot_tested": False}]}
            path.write_text(json.dumps(state))

            @contextlib.contextmanager
            def fake_top():
                yield top

            with patch.object(boot, "top_level", fake_top), patch.object(boot, "recovery_id", return_value=7), \
                 patch.object(boot, "secure_boot_enabled"), patch.object(boot, "verify"), \
                 patch.object(boot, "hash_file", return_value="changed"), patch.object(boot, "run", return_value="overlay"):
                with self.assertRaises(RuntimeError):
                    boot.confirm()
            self.assertEqual(json.loads(path.read_text()), state)

    def test_secure_boot_disabled_cannot_confirm_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            variables = Path(directory)
            (variables / "SecureBoot-guid").write_bytes(b"\x07\x00\x00\x00\x00")
            with patch.object(kdbx, "EFI", variables):
                with self.assertRaisesRegex(RuntimeError, "Secure Boot is disabled"):
                    boot.secure_boot_enabled()

    def test_normalize_guid_strips_newline(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "GUID"
            path.write_text("11111111-2222-3333-4444-555555555555\n")
            kdbx.normalize_guid(path)
            self.assertEqual(path.read_bytes(), b"11111111-2222-3333-4444-555555555555")

    def test_sbctl_config_lists_explicit_key_paths(self):
        root = Path("/run/workstation-secrets")
        config = boot.sbctl_config(root)
        self.assertIn("keys:\n", config)
        for name, directory in (("pk", "PK"), ("kek", "KEK"), ("db", "db")):
            self.assertIn(f"  {name}:", config)
            self.assertIn(f"privkey: {root}/keys/{directory}/{directory}.key", config)
            self.assertIn(f"pubkey: {root}/keys/{directory}/{directory}.pem", config)

    def test_snapper_uses_no_dbus_only_without_system_bus(self):
        completed = Mock(returncode=0, stdout=b"7\n", stderr=b"")
        with patch("boot.Path.exists", return_value=False), patch("boot.subprocess.run", return_value=completed) as run:
            self.assertEqual(boot.run_snapper("snapper", "-c", "root", "list"), "7")
            self.assertEqual(run.call_args.args[0][:2], ["snapper", "--no-dbus"])
        with patch("boot.Path.exists", return_value=True), patch("boot.subprocess.run", return_value=completed) as run:
            boot.run_snapper("snapper", "-c", "root", "list")
            self.assertEqual(run.call_args.args[0][:2], ["snapper", "-c"])

    def test_identity_replaces_shipped_symlink_without_following(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            (target / "etc/default").mkdir(parents=True)
            real = root / "locale.conf"
            real.write_text("LANG=old\n")
            link = target / "etc/default/locale"
            link.symlink_to(real)
            with self.assertRaises(OSError):
                kdbx.write(link, "LANG=should-not-follow\n", 0o644)
            self.assertEqual(real.read_text(), "LANG=old\n")
            kdbx.write_replacing_symlink(link, "LANG=de_DE.UTF-8\n")
            self.assertFalse(link.is_symlink())
            self.assertEqual(link.read_text(), "LANG=de_DE.UTF-8\n")
            self.assertEqual(real.read_text(), "LANG=old\n")

    def test_database_rejects_world_readable_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.kdbx"
            path.write_bytes(b"encrypted")
            path.chmod(0o644)
            with self.assertRaises(RuntimeError):
                kdbx.safe_database(path)
            path.chmod(0o600)
            self.assertEqual(kdbx.safe_database(path), path)
            link = path.with_name("link.kdbx")
            link.symlink_to(path)
            with self.assertRaises(RuntimeError):
                kdbx.safe_database(link)

    def test_public_scanner_detects_generic_pkcs8_and_kdbx(self):
        spec = importlib.util.spec_from_file_location("scanner", ROOT / "tools/scan-public.py")
        scanner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scanner)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "hidden.dat").write_bytes(b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"A" * 64)
            (root / "database.dat").write_bytes(bytes.fromhex("03d9a29a67fb4bb5") + b"payload")
            self.assertEqual(len(scanner.scan(root)), 2)

    def scanner(self):
        spec = importlib.util.spec_from_file_location("scanner", ROOT / "tools/scan-public.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_nested_fai_images_scan_files_not_raw_container_bytes(self):
        scanner = self.scanner()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            iso, squash, filesystem = (base / name for name in ("iso", "squash", "filesystem"))
            for path in (iso, squash / "LiveOS", filesystem / "etc"):
                path.mkdir(parents=True)
            (iso / "squashfs.img").write_bytes(b"hsqs" + b"\0" * 1100)
            ext = squash / "LiveOS/ext3fs.img"
            # A PEM payload in raw free space must not be mistaken for a file.
            payload = b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"A" * 64
            ext.write_bytes(b"\0" * 1080 + b"\x53\xef" + payload)

            @contextlib.contextmanager
            def contents(path, kind):
                yield squash if kind == "squashfs" else filesystem

            with patch.object(scanner, "image_contents", side_effect=contents):
                self.assertEqual(scanner.scan(iso, images=True), [])
                (filesystem / "etc/credential.pem").write_bytes(payload)
                errors = scanner.scan(iso, images=True)
            self.assertEqual(len(errors), 1)
            self.assertIn("squashfs.img!/LiveOS/ext3fs.img!/etc/credential.pem", errors[0])
            self.assertIn("private-key PEM payload", errors[0])

    def test_ext_scan_mount_is_read_only_and_unmounted_on_scan_error(self):
        scanner = self.scanner()
        calls = []

        def command(args, **kwargs):
            calls.append(args)
            return Mock(returncode=0)

        with patch.object(scanner.subprocess, "run", side_effect=command):
            with self.assertRaisesRegex(RuntimeError, "scan failed"):
                with scanner.image_contents(Path("ext3fs.img"), "ext"):
                    raise RuntimeError("scan failed")
        self.assertEqual(calls[0][:4], ["mount", "-t", "ext4", "-o"])
        self.assertIn("ro,noload,nosuid,nodev,noexec", calls[0][4])
        self.assertEqual(calls[-1][0], "umount")
        self.assertFalse(Path(calls[-1][1]).exists())

    def test_image_mount_failure_fails_closed(self):
        scanner = self.scanner()
        with patch.object(scanner.subprocess, "run", return_value=Mock(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, "Cannot inspect ext filesystem"):
                with scanner.image_contents(Path("ext3fs.img"), "ext"):
                    self.fail("Failed mount must never be accepted as an empty scan")

    def test_only_checksum_verified_packaged_gnutls_is_exempt(self):
        scanner = self.scanner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "usr/lib/x86_64-linux-gnu/libgnutls.so.30.40.3"
            library = root / name
            library.parent.mkdir(parents=True)
            payload = b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"A" * 64
            library.write_bytes(b"\x7fELF\0" + payload)
            info = root / "var/lib/dpkg/info"
            info.mkdir(parents=True)
            digest = hashlib.md5(library.read_bytes(), usedforsecurity=False).hexdigest()
            (info / "libgnutls30t64:amd64.md5sums").write_text(f"{digest}  {name}\n")
            allowed = scanner.debian_gnutls_allowlist(root)
            self.assertEqual(scanner.scan(root, allowed=allowed), [])
            # A different PEM file is never exempt, even with identical content.
            (root / "credential.pem").write_bytes(library.read_bytes())
            self.assertEqual(len(scanner.scan(root, allowed=allowed)), 1)
            library.write_bytes(library.read_bytes() + b"modified")
            self.assertEqual(len(scanner.scan(root, allowed=allowed)), 2)
            with self.assertRaisesRegex(RuntimeError, "package checksum mismatch"):
                scanner.debian_gnutls_allowlist(root)


if __name__ == "__main__":
    unittest.main()
