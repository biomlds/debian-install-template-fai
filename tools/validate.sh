#!/bin/bash
set -Eeuo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python3 "$repo/tools/validate.py"
if command -v shellcheck >/dev/null; then
  mapfile -t files < <(find "$repo" -type f \( -name '*.sh' -o -perm -u+x \) -print | while read -r f; do head -n1 "$f" | grep -qE '^#!.*(ba|d?a)?sh' && echo "$f"; done)
  shellcheck --rcfile "$repo/.shellcheckrc" --severity=warning "${files[@]}"
else
  echo 'WARN: shellcheck unavailable' >&2
fi
python3 "$repo/tests/test-disk-selector.py"
"$repo/tests/test-firstboot-input.sh"
"$repo/tests/test-luks-rotation-image.sh"
