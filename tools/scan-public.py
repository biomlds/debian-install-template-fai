#!/usr/bin/env python3
"""Reject private payloads in a config tree or an extracted public ISO."""
import argparse
import contextlib
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

PRIVATE = re.compile(rb"-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=]{32}")
KDBX = bytes.fromhex("03d9a29a67fb4bb5")


def debian_gnutls_allowlist(root):
    """Trust only the exact packaged GnuTLS library containing upstream self-tests.

    fai-cd strips dpkg info from its root, so obtain hashes from the original
    apt-built NFSROOT before inspecting the ISO. Never exempt a directory or all
    ELF files: a modified library must still fail the private-payload scan.
    """
    allowed = {}
    manifests = list((root / "var/lib/dpkg/info").glob("libgnutls30*.md5sums"))
    for manifest in manifests:
        for line in manifest.read_text().splitlines():
            expected, name = line.split(maxsplit=1)
            if not re.fullmatch(r"usr/lib/x86_64-linux-gnu/libgnutls\.so\.30\.[0-9]+\.[0-9]+", name):
                continue
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"Packaged GnuTLS library missing or unsafe: {name}")
            data = path.read_bytes()
            if hashlib.md5(data, usedforsecurity=False).hexdigest() != expected:
                raise RuntimeError(f"GnuTLS package checksum mismatch: {name}")
            allowed[name] = hashlib.sha256(data).hexdigest()
    return allowed


def image_type(path):
    with path.open("rb") as stream:
        header = stream.read(1082)
    if header[:4] == b"hsqs":
        return "squashfs"
    # ext2/3/4 superblock magic, independent of the misleading ext3fs.img name.
    if header[1080:1082] == b"\x53\xef":
        return "ext"
    return None


@contextlib.contextmanager
def image_contents(path, kind):
    directory = Path(tempfile.mkdtemp(prefix="fai-public-scan."))
    mounted = False
    try:
        if kind == "squashfs":
            root = directory / "root"
            result = subprocess.run(["unsquashfs", "-no-progress", "-d", str(root), str(path)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            root = directory
            # ro alone can still replay an ext journal. noload prevents writes.
            result = subprocess.run(["mount", "-t", "ext4", "-o", "loop,ro,noload,nosuid,nodev,noexec",
                                     str(path), str(root)], capture_output=True)
            mounted = result.returncode == 0
        if result.returncode:
            raise RuntimeError(f"Cannot inspect {kind} filesystem: {path}")
        yield root
    finally:
        if mounted:
            result = subprocess.run(["umount", str(directory)], capture_output=True)
            if result.returncode:
                # Never recursively remove a directory while an image is mounted.
                raise RuntimeError(f"Cannot unmount scan filesystem; retained at {directory}")
        shutil.rmtree(directory)


def scan(root, *, images=False, prefix="", depth=0, allowed=None):
    errors = []
    if not root.is_dir():
        raise RuntimeError(f"Scan root is not a directory: {root}")
    forbidden = {"config.yaml", "luks.bootstrap.passphrase", "provision.password.hash", "GUID"}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in {".git", "__pycache__"} for part in path.relative_to(root).parts):
            continue
        display = prefix + str(path.relative_to(root)) if prefix else str(path)
        if path.name in forbidden or path.suffix.lower() in {".kdbx", ".key", ".passphrase", ".password"}:
            errors.append(f"{display} (forbidden filename)")
            continue
        kind = image_type(path) if images else None
        if kind:
            if depth >= 4:
                raise RuntimeError(f"Filesystem nesting limit exceeded: {display}")
            print(f"Inspecting {kind} filesystem: {display}", flush=True)
            with image_contents(path, kind) as contents:
                errors.extend(scan(contents, images=True, prefix=display + "!/", depth=depth + 1, allowed=allowed))
            continue
        # Inspect allocated files, not container bytes, deleted data or free space.
        with path.open("rb") as stream:
            overlap = b""
            while chunk := stream.read(1024 * 1024):
                data = overlap + chunk
                rule = "private-key PEM payload" if PRIVATE.search(data) else "KDBX signature" if data.startswith(KDBX) else None
                if rule:
                    expected = (allowed or {}).get(str(path.relative_to(root)))
                    if rule == "private-key PEM payload" and expected:
                        with path.open("rb") as library:
                            actual = hashlib.file_digest(library, "sha256").hexdigest()
                        if actual == expected:
                            print(f"Verified Debian GnuTLS self-test data: {display}", flush=True)
                            break
                    errors.append(f"{display} ({rule})")
                    break
                overlap = data[-128:]
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--images", action="store_true",
                        help="recursively inspect squashfs and ext filesystem contents (requires root/mount)")
    parser.add_argument("--debian-root", type=Path,
                        help="original apt-built NFSROOT for checksum-verified GnuTLS self-test exception")
    args = parser.parse_args()
    try:
        allowed = debian_gnutls_allowlist(args.debian_root) if args.debian_root else None
        errors = scan(args.root, images=args.images, allowed=allowed)
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"Public scan failed: {error}") from None
    if errors:
        raise SystemExit("Private payload found: " + ", ".join(errors))
    print("PASS public credential boundary")
