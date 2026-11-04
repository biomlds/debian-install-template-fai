#!/bin/bash
set -Eeuo pipefail
config=${1:-/root/mise.toml}
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends bash-completion build-essential ca-certificates curl git jq sudo unzip xz-utils zstd bcftools bedtools fastqc ncbi-blast+ samtools seqtk tabix
id dev >/dev/null 2>&1 || useradd --create-home --shell /bin/bash dev
printf 'dev ALL=(ALL:ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/90-dev
chmod 0440 /etc/sudoers.d/90-dev
install -d -m 0755 -o dev -g dev /home/dev/workspace
install -m 0644 -o dev -g dev "$config" /home/dev/workspace/mise.toml
mise_binary=$(mktemp)
trap 'rm -f "$mise_binary"' EXIT
[ "$(uname -m)" = x86_64 ] || { echo "Pinned mise binary requires x86_64." >&2; exit 1; }
curl --proto '=https' --tlsv1.2 -fsSL -o "$mise_binary" \
    https://github.com/jdx/mise/releases/download/v2026.10.0/mise-v2026.10.0-linux-x64
printf '%s  %s\n' 57ced973f968b8fbab07aa8e32bd7077d4a357e200a22356d98963c723c6de0a "$mise_binary" | sha256sum -c -
install -d -m 0755 -o dev -g dev /home/dev/.local/bin
install -m 0755 -o root -g root "$mise_binary" /home/dev/.local/bin/mise
cat >> /home/dev/.bashrc <<'EOF'
export PATH="$HOME/.local/bin:$PATH"
eval "$(mise activate bash)"
EOF
chown dev:dev /home/dev/.bashrc
sudo -u dev -H bash -lc 'export PATH="$HOME/.local/bin:$PATH"; cd ~/workspace; mise trust; mise install; mise run doctor'
apt-get clean
rm -rf /var/lib/apt/lists/*
