#!/usr/bin/env python3
"""Archive the validated source worktree, including pending implementation."""
import subprocess
import zipfile
from pathlib import Path

import manifest

root = Path(__file__).resolve().parents[1]
output = root / "build/debian-install-template-fai.zip"
output.parent.mkdir(exist_ok=True)
subprocess.run(["python3", str(root / "tools/scan-public.py"), str(root / "fai/config")], check=True)
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    names = [line.split("  ", 1)[1] for line in manifest.content().splitlines()]
    for name in [*names, "MANIFEST.sha256"]:
        archive.write(root / name, "debian-install-template-fai/" + name)
subprocess.run([str(root / "tools/check-archive.sh"), str(output)], check=True)
