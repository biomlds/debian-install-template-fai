#!/usr/bin/env python3
import json
import re
from pathlib import Path
import yaml
root=Path(__file__).resolve().parents[1]
errors=[]
cfg=root/'fai/config'
mount=(cfg/'hooks/mountdisks.LUKS_BTRFS').read_text()
for name in ('@root','@home','@snapshots'):
    if name not in mount: errors.append(f'missing subvolume {name}')
for name in ('@var_log','@var_cache','@var_tmp','@incus','@swap'):
    if name in mount or name in (cfg/'disk_config/LUKS_BTRFS').read_text(): errors.append(f'forbidden subvolume {name}')
if 'subvol=@home' not in mount or 'subvol=@snapshots' not in mount: errors.append('missing mount options')
for token in ('mkfs.btrfs','blkid -s TYPE -o value','expected btrfs'):
    if token not in mount: errors.append(f'encrypted btrfs guard missing {token}')
snap=(cfg/'files/etc/snapper/configs/root/LUKS_BTRFS').read_text()
if 'SUBVOLUME="/"' not in snap: errors.append('snapper is not root-only')
disk=(cfg/'disk_config/LUKS_BTRFS').read_text()
for token in ('disklabel:gpt','p=efi','disk_config cryptsetup','--type=luks2','--pbkdf=pbkdf2','btrfs'):
    if token not in disk: errors.append(f'disk config missing {token}')
if 'createopts="-L debian-root"' in disk:
    errors.append('btrfs label must be applied by the mountdisks hook, not setup-storage')
for line in disk.splitlines():
    if line.strip() and not line.lstrip().startswith('#'):
        fields=line.split()
        if len(fields) > 1 and fields[1] == '/boot':
            errors.append('separate /boot would break snapshot kernel consistency')
first=(cfg/'files/usr/local/lib/workstation-firstboot/workstation_firstboot.py/WORKSTATION').read_text()
for token in ('luksAddKey','--test-passphrase','luksKillSlot','len(slots) < 2','permanent-verified','SecretStore','finalize'):
    if token not in first: errors.append(f'firstboot missing safety token {token}')
example=yaml.safe_load((cfg/'files/etc/workstation-bootstrap/config.yaml.example/WORKSTATION').read_text())
canonical=yaml.safe_load((root/'config/config.yaml.example').read_text())
if example != canonical: errors.append('canonical and installed config.yaml examples differ')
for path in ('identity','account','git','ssh','chezmoi','borg','vorta','cryptomator','grub','luks'):
    if path not in example: errors.append(f'config example missing {path}')
if 'choices=("keepassxc", "yaml")' not in first: errors.append('firstboot does not enforce exactly two primary sources')
fai_key=(cfg/'scripts/LUKS_BTRFS/10-bootstrap-key').read_text()
for token in ('luksAddKey','--test-passphrase','luksKillSlot','fewer than two active slots'):
    if token not in fai_key: errors.append(f'FAI bootstrap rotation missing {token}')
provision=(cfg/'scripts/WORKSTATION/10-provision-user').read_text()
if 'chpasswd --encrypted' not in provision or 'usermod --password' in provision:
    errors.append('temporary account password is not supplied over stdin')
incus=(cfg/'assets/incus/scripts/create.sh').read_text()
if ' --vm ' not in incus or '--container' in incus: errors.append('Incus helper must create VMs only')
packages='\n'.join(p.read_text() for p in (cfg/'package_config').iterdir())
if any(re.search(rf'(?m)^{name}$',packages) for name in ('mise','nodejs','golang','rustc','cargo')):
    errors.append('project runtime/toolchain found in host package manifests')
workflows='\n'.join(p.read_text() for p in (root/'.github/workflows').glob('*.yml'))
if re.search(r'\$\{\{\s*secrets\.',workflows): errors.append('workflow consumes a GitHub secret')
grub=(cfg/'files/usr/local/sbin/update-grub-secure/GRUB_EFI').read_text()
if '--unrestricted' not in grub or 'snapshot' not in grub or 'password_pbkdf2' not in grub:
    errors.append('GRUB authentication policy is incomplete')
workstation_var=(cfg/'class/WORKSTATION.var').read_text()
if 'fai.disk' in workstation_var or 'FAI_DISK=' in workstation_var:
    errors.append('obsolete production kernel-command-line disk selection remains')
partition=(cfg/'hooks/partition.WORKSTATION').read_text()
for token in ('disk_selector.py',' select ','--tty /dev/console',' revalidate ','setup-storage -X','-D "$disklist"','BOOT_DEVICE'):
    if token not in partition: errors.append(f'partition hook missing {token}')
selector=(cfg/'assets/disk-selection/disk_selector.py').read_text()
for token in ('KNOWN_LIVE_TARGETS','EXCLUDED_TYPES','ERASE','test_disk_selection','systemd-detect-virt','identity changed','Split bootloader','console_candidates','/sys/class/tty/console/active'):
    if token not in selector: errors.append(f'disk selector missing safety control {token}')
grub_setup=(cfg/'scripts/GRUB_EFI/10-setup').read_text()
for token in ('FAI_SELECTED_BOOT_STABLE','BOOT_DEVICE','/boot/efi','efi_disk'):
    if token not in grub_setup: errors.append(f'GRUB setup missing selected-device check {token}')
for path in (root/'README.md', root/'docs/FAI.md', root/'docs/STORAGE.md', root/'docs/SECURITY.md'):
    if 'fai.disk=' in path.read_text(): errors.append(f'obsolete fai.disk instruction in {path.relative_to(root)}')
for workflow in (root/'.github/workflows').glob('*.yml'):
    yaml.safe_load(workflow.read_text())
required_docs={'ARCHITECTURE.md','STORAGE.md','SECURITY.md','FIRST_BOOT.md','KEEPASSXC.md','CONFIG_YAML.md','BACKUP.md','RECOVERY.md','GRUB.md','LUKS.md','FAI.md','GITHUB_ACTIONS.md','INCUS.md','VALIDATION.md'}
missing=required_docs-{p.name for p in (root/'docs').glob('*.md')}
errors.extend(f'missing doc {name}' for name in sorted(missing))
if errors:
    print('\n'.join('ERROR '+e for e in errors)); raise SystemExit(1)
print('PASS implementation/documentation consistency checks')
