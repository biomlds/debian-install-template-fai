#!/usr/bin/env python3
"""Hash source inventory, including untracked implementation files before commit."""
import argparse
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def content():
    if (ROOT / ".git").exists():
        names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    else:
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()]
    lines = []
    for name in sorted(set(names)):
        path = ROOT / name
        if not name or not path.is_file() or path.is_symlink():
            continue
        if any(part in {".git", "build", "__pycache__"} for part in Path(name).parts):
            continue
        if name.startswith("fai/config/assets/bin/") or path.name in {"MANIFEST.sha256", "HOST_TOOLS.sha256", "HOST_TOOLS.versions"}:
            continue
        if path.suffix in {".pyc", ".kdbx", ".key", ".iso", ".passphrase", ".password"}:
            continue
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}\n")
    return "".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "MANIFEST.sha256")
    args = parser.parse_args()
    expected = content()
    if args.check:
        if args.output.read_text() != expected:
            raise SystemExit("MANIFEST.sha256 is out of date; run make manifest")
        print("PASS manifest inventory and hashes")
    else:
        args.output.write_text(expected)
