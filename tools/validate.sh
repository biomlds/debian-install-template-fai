#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Shell syntax checks"

mapfile -d '' shell_files < <(
    python3 - "$REPO_ROOT" <<'PYTHON'
import sys
from pathlib import Path
root = Path(sys.argv[1])
for path in sorted(root.rglob('*')):
    relative = path.relative_to(root)
    if not path.is_file() or any(part in {'.git', 'build', '__pycache__'} for part in relative.parts):
        continue
    if str(relative).startswith(('fai/config/assets/bin/', 'fai/config/assets/vendor/')):
        continue
    first = path.open('rb').readline(256)
    if path.suffix == '.sh' or (first.startswith(b'#!') and b'sh' in first):
        sys.stdout.buffer.write(str(path).encode() + b'\0')
PYTHON
)

for file in "${shell_files[@]}"; do
    bash -n "$file"
done

echo "==> Shellcheck"

if command -v shellcheck >/dev/null 2>&1; then
    shellcheck "${shell_files[@]}"
else
    echo "WARN: shellcheck unavailable; skipped" >&2
fi

echo "==> Repository validation"

python3 "$REPO_ROOT/tools/validate.py"

echo "==> Workstation recovery and input validation"

python3 "$REPO_ROOT/tests/test-workstation.py"

echo "==> LUKS rotation validation"

bash "$REPO_ROOT/tests/test-luks-rotation-image.sh"

echo "==> Disk selector validation"

python3 "$REPO_ROOT/tests/test-disk-selector.py"

echo "==> Repository validation successful"
