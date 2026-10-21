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
sudo -u dev -H bash -c 'curl -fsSL https://mise.run | MISE_VERSION=2026.10.0 sh'
printf '%s\n' 'export PATH="$HOME/.local/bin:$PATH"' 'eval "$(mise activate bash)"' >> /home/dev/.bashrc
chown dev:dev /home/dev/.bashrc
sudo -u dev -H bash -lc 'export PATH="$HOME/.local/bin:$PATH"; cd ~/workspace; mise trust; mise install; mise run doctor'
apt-get clean
rm -rf /var/lib/apt/lists/*
