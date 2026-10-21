# Incus

Run `sudo incus-init-workstation` once. It creates one NAT bridge, one `dir` storage pool, and one default profile. There are no role-specific profiles.

VMs are the default and only path exposed by the creation helper:

```bash
base=/usr/local/share/workstation-bootstrap/incus/scripts
$base/create.sh devbox dev
$base/create.sh biobox bio
$base/create.sh aibox ai --cpu 12 --memory 32GiB
$base/snapshot.sh biobox before-upgrade
$base/restore.sh biobox before-upgrade
$base/stop.sh biobox
$base/start.sh biobox
$base/shell.sh biobox
$base/destroy.sh biobox
```

Templates install mise inside the VM, then role tools from `mise.toml`. AI and untrusted work use VMs, not system containers. Containers may be nested inside a VM if a project needs them. Ansible, Terraform, Nix, and multiple Incus profiles are intentionally absent.
