#!/usr/bin/env python3
"""Reject private payloads in a config tree or an extracted public ISO."""
import argparse
import re
from pathlib import Path

PRIVATE = re.compile(rb"-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=]{32}")
KDBX = bytes.fromhex("03d9a29a67fb4bb5")


def scan(root):
    errors = []
    forbidden = {"config.yaml", "luks.bootstrap.passphrase", "provision.password.hash", "GUID"}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in {".git", "__pycache__"} for part in path.relative_to(root).parts):
            continue
        if path.name in forbidden or path.suffix.lower() in {".kdbx", ".key", ".passphrase", ".password"}:
            errors.append(str(path))
            continue
        # Scan in bounded chunks including cross-chunk overlaps (large squashfs).
        with path.open("rb") as stream:
            overlap = b""
            while chunk := stream.read(1024 * 1024):
                data = overlap + chunk
                if PRIVATE.search(data) or data.startswith(KDBX):
                    errors.append(str(path))
                    break
                overlap = data[-128:]
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    errors = scan(args.root)
    if errors:
        raise SystemExit("Private payload found: " + ", ".join(errors))
    print("PASS public credential boundary")
