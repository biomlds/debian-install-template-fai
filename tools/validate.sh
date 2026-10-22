#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Shell syntax checks"

mapfile -d '' shell_files < <(
    find "$REPO_ROOT" \
        -type f \
        \( -name "*.sh" -o -path "*/scripts/*" \) \
        ! -path "*/.git/*" \
        ! -path "*/build/*" \
        ! -path "*/fai/config/assets/bin/*" \
        ! -path "*/fai/config/assets/vendor/*" \
        -print0
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

echo "==> First-boot input validation"

bash "$REPO_ROOT/tests/test-firstboot-input.sh"

echo "==> LUKS rotation validation"

bash "$REPO_ROOT/tests/test-luks-rotation-image.sh"

echo "==> Disk selector validation"

python3 "$REPO_ROOT/tests/test-disk-selector.py"

echo "==> Repository validation successful"
