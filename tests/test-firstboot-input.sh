#!/bin/bash
set +x
set -Eeuo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d /tmp/firstboot-input-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT INT TERM HUP
umask 077
printf '%016d' 0 > "$tmp/login"
printf '%020d' 0 > "$tmp/grub"
printf '%024d' 0 > "$tmp/luks"
printf '%s\n' '-----BEGIN TEST KEY-----' 'not-a-real-private-key' '-----END TEST KEY-----' > "$tmp/id"
printf '%s\n' 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeNonSecretValidationMaterial test' > "$tmp/id.pub"
printf '%s\n' 'Host *' '    IdentitiesOnly yes' > "$tmp/ssh_config"
printf '%s\n' 'not-a-real-borg-key' > "$tmp/borg-key"
cat > "$tmp/config.yaml" <<YAML
schema_version: 1
identity:
  username: tester
  full_name: Test User
  hostname: test-workstation
account:
  login_password: {file: "$tmp/login"}
git:
  name: Test User
  email: test@example.invalid
ssh:
  private_key_file: "$tmp/id"
  public_key_file: "$tmp/id.pub"
  config_file: "$tmp/ssh_config"
chezmoi:
  repository: local-scaffold
  branch: main
borg:
  repository: ssh://example.invalid/repository
  ssh_key_file: "$tmp/borg-key"
cryptomator:
  vault_path: ~/ColdStorage/Cryptomator
grub:
  username: workstation-admin
  password: {file: "$tmp/grub"}
luks:
  passphrase: {file: "$tmp/luks"}
YAML
chmod 0600 "$tmp"/*
firstboot="$repo/fai/config/files/usr/local/lib/workstation-firstboot/workstation_firstboot.py/WORKSTATION"
python3 "$firstboot" validate-input --source yaml --config "$tmp/config.yaml" --non-interactive
expect_failure(){
  local name=$1 config=$2
  if python3 "$firstboot" validate-input --source yaml --config "$config" --non-interactive >/dev/null 2>&1; then
    echo "FAIL first-boot input accepted invalid case: $name" >&2
    exit 1
  fi
}
sed "s#login_password: {file: \"$tmp/login\"}#login_password: scalar-password-value#" \
  "$tmp/config.yaml" > "$tmp/scalar-secret.yaml"
sed 's/full_name: Test User/full_name: Test:User/' \
  "$tmp/config.yaml" > "$tmp/bad-full-name.yaml"
sed '/hostname: test-workstation/a\  timezone: ../../etc/passwd' \
  "$tmp/config.yaml" > "$tmp/bad-timezone.yaml"
expect_failure scalar-secret "$tmp/scalar-secret.yaml"
expect_failure full-name-colon "$tmp/bad-full-name.yaml"
expect_failure timezone-traversal "$tmp/bad-timezone.yaml"
echo "PASS first-boot YAML normalization and invalid-input rejection; no system changes made"
