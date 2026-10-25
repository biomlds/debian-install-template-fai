#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "fai/config"
errors: list[str] = []
warnings: list[str] = []

required = [
    "class/10-base-classes",
    "class/20-bootstrap",
    "class/50-host-classes",
    "class/DEBIAN.var",
    "class/TRIXIE.var",
    "class/WORKSTATION.var",
    "disk_config/LUKS_BTRFS",
    "debconf/WORKSTATION",
    "hooks/partition.WORKSTATION",
    "hooks/mountdisks.LUKS_BTRFS",
    "package_config/DEBIAN",
    "package_config/FAIBASE",
    "package_config/TRIXIE",
    "package_config/AMD64",
    "package_config/SYSTEMD_BOOT",
    "package_config/LUKS_BTRFS",
    "package_config/WORKSTATION",
    "package_config/SWAY",
    "package_config/BACKUP",
    "package_config/INCUS",
    "package_config/FLATPAK_APPS",
    "scripts/LUKS_BTRFS/10-luks-key",
    "scripts/LUKS_BTRFS/20-snapper",
    "scripts/SYSTEMD_BOOT/10-setup",
    "scripts/FINAL/99-finalize",
    "files/etc/systemd/system/workstation-flatpaks.service/FLATPAK_APPS",
    "files/etc/systemd/system/workstation-flatpaks.timer/FLATPAK_APPS",
    "assets/workstation/kdbx.py",
    "assets/workstation/boot.py",
    "files/usr/local/sbin/workstation-flatpaks/FLATPAK_APPS",
    "assets/disk-selection/disk_selector.py",
]


def ignored(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in {".git", "build", "__pycache__"} for part in relative.parts):
        return True
    return relative.parts[:4] in {
        ("fai", "config", "assets", "bin"),
        ("fai", "config", "assets", "vendor"),
    }


for rel in required:
    if not (CFG / rel).is_file():
        errors.append(f"missing {rel}")

nfsroot = ROOT / "server/NFSROOT"
if not nfsroot.is_file():
    errors.append("missing server/NFSROOT")
else:
    nfsroot_packages: set[str] = set()
    for raw in nfsroot.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and not line.startswith("PACKAGES "):
            nfsroot_packages.update(line.split())
    for package in ("dracut", "initramfs-tools-", "kbd", "dbus", "keepassxc-minimal", "libpcsclite1"):
        if package not in nfsroot_packages:
            errors.append(f"server/NFSROOT missing {package}")

for path in ROOT.rglob("*"):
    if not path.is_file() or ignored(path) or path.name == "MANIFEST.sha256":
        continue
    data = path.read_bytes()
    relative = path.relative_to(ROOT)
    if b"\r\n" in data:
        errors.append(f"CRLF {relative}")
    if b"\x00" in data:
        errors.append(f"NUL {relative}")
    try:
        text = data.decode()
    except UnicodeDecodeError:
        continue
    for number, line in enumerate(text.splitlines(), 1):
        if line.rstrip(" \t") != line:
            errors.append(f"trailing whitespace {relative}:{number}")

shell: list[Path] = []
for path in ROOT.rglob("*"):
    if not path.is_file() or ignored(path):
        continue
    first = path.read_bytes().splitlines()[:1]
    if path.suffix == ".sh" or (first and first[0].startswith(b"#!") and b"sh" in first[0]):
        shell.append(path)
        if not path.stat().st_mode & stat.S_IXUSR:
            errors.append(f"not executable {path.relative_to(ROOT)}")
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        if result.returncode:
            errors.append(f"bash syntax {path.relative_to(ROOT)}: {result.stderr.strip()}")

pyfiles = [path for path in ROOT.rglob("*.py") if path.is_file() and not ignored(path)]
for path in pyfiles:
    try:
        compile(path.read_text(), str(path), "exec")
    except SyntaxError as exc:
        errors.append(f"python syntax {path.relative_to(ROOT)}: {exc}")

yaml_files = [path for path in list(ROOT.rglob("*.yaml")) + list(ROOT.rglob("*.yml")) if not ignored(path)]
for path in yaml_files:
    try:
        yaml.safe_load(path.read_text())
    except Exception as exc:
        errors.append(f"YAML {path.relative_to(ROOT)}: {exc}")

for path in sorted((CFG / "package_config").iterdir()):
    mode = None
    seen: set[tuple[str, str]] = set()
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("PACKAGES "):
            mode = line.split(maxsplit=1)[1]
            continue
        if mode not in {"install", "remove"}:
            errors.append(f"package before header {path.name}:{number}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", line):
            errors.append(f"bad package {path.name}:{number}:{line}")
        if (mode, line) in seen:
            errors.append(f"duplicate package {path.name}:{line}")
        seen.add((mode, line))

secret_patterns = [
    re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:password|passphrase)[ \t]*[:=][ \t]*[\"'](?!REPLACE|/media|/run|/var|\$)[^\"'\r\n]{8,}[\"']"),
    re.compile(r"\$\{\{\s*secrets\."),
]
for path in ROOT.rglob("*"):
    if not path.is_file() or ignored(path) or path.name == "validate.py":
        continue
    text = path.read_text(errors="ignore")
    for pattern in secret_patterns:
        if pattern.search(text):
            errors.append(f"possible committed secret {path.relative_to(ROOT)}")

setup_storage = shutil.which("setup-storage")
if setup_storage:
    with tempfile.TemporaryDirectory(prefix="fai-validate-") as temp:
        result = subprocess.run(
            [setup_storage, "-s", "-f", str(CFG / "disk_config/LUKS_BTRFS")],
            env={**os.environ, "disklist": "sda", "LOGDIR": temp, "LC_ALL": "C"},
            capture_output=True,
            text=True,
        )
        if result.returncode:
            errors.append("setup-storage syntax: " + (result.stderr.strip() or result.stdout.strip()))
else:
    message = "setup-storage unavailable; static disk validation only"
    if os.environ.get("CI"):
        errors.append("setup-storage is required in CI")
    else:
        warnings.append(message)

result = subprocess.run([sys.executable, str(ROOT / "tests/test-consistency.py")], capture_output=True, text=True)
if result.returncode:
    errors.append("consistency: " + result.stdout.strip() + result.stderr.strip())

for warning in warnings:
    print("WARN:", warning)
if errors:
    for error in errors:
        print("ERROR:", error, file=sys.stderr)
    raise SystemExit(1)
print(
    f"PASS {len(required)} required files; {len(shell)} shell files; "
    f"{len(pyfiles)} Python files; {len(list((CFG / 'package_config').iterdir()))} package classes"
)
