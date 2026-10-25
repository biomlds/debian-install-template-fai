#!/usr/bin/env python3
"""Failure-oriented tests for recovery retention, publication and private input."""
import importlib.util
import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fai/config/assets/workstation"))
import boot
import kdbx


class RecoveryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
