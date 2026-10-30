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


class RecoveryTests(unittest.TestCase):
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
