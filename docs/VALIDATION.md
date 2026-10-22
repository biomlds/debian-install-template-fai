# Validation and disk-selector testing

All default validation is non-destructive:

```bash
make validate
python3 tests/test-disk-selector.py
python3 fai/config/assets/disk-selection/disk_selector.py \
  inventory --fixture tests/fixtures/disks-local.json
```

`make validate` runs Python compilation, shell syntax checks, YAML parsing, FAI/config consistency checks, mocked disk discovery/filtering, read-only first-boot input normalization, and a regular-file LUKS2 rotation test. `setup-storage -s` is required in CI and runs automatically when installed locally; the syntax check needs `setup-storage`, `cryptsetup`, `btrfs-progs`, `dosfstools`, and `parted`. Without `setup-storage`, local validation warns and performs static checks only. The LUKS test uses a temporary file in `/dev/shm` or `/tmp` and skips when `cryptsetup` is unavailable; it never opens or writes a block device. `.shellcheckrc` documents narrowly scoped exclusions for FAI-injected variables, the intentional `$ROOTCMD` command prefix, and intentional LUKS-slot word splitting.

## Manifest

Run `make manifest` after changing tracked files. `make manifest-check` regenerates the manifest in a temporary file and fails if it differs from the committed `MANIFEST.sha256`. Both targets use Git when available and fall back to a deterministic source-file scan in extracted source snapshots without `.git`; neither requires a Git checkout to verify the manifest.

## Interactive dry run

Boot the FAI environment and open a shell before allowing installation to proceed. From the repository/config media run:

```bash
python3 "$FAI/assets/disk-selection/disk_selector.py" select --dry-run
```

`tools/preview-install.sh` is the equivalent repository wrapper. This uses live `lsblk`/`findmnt` data and the production selector. It asks for OS and bootloader disks, shows the complete selection and layout, and requires `PREVIEW <selected-identifier>`. It does not persist the selection, call setup-storage, or write a disk.

## Disposable VM automation only

Production installation never accepts a preselected disk. CI or a disposable VM may bypass prompts only when **all** of the following are true:

1. `systemd-detect-virt --vm` succeeds;
2. the selected disk passes every normal eligibility and installation-media exclusion check;
3. the VM kernel command line contains both:

```text
fai.test_disk_selection=DISPOSABLE_VM_I_UNDERSTAND_THIS_DISK_WILL_BE_ERASED
fai.test_disposable_disk=/dev/disk/by-id/virtio-DISPOSABLE-TEST-DISK
```

Use a newly attached, empty virtual disk—not the VM boot disk. The deliberately long `fai.test_disk_selection` value is exact and has no default. Supplying only one parameter aborts. Physical hardware is rejected even if both parameters are present.

## Required manual hardware tests

Before relying on a release, test on representative UEFI hardware:

- local USB/ISO boot with the installer medium excluded;
- PXE/NFS or HTTP live boot with no local medium;
- SATA, NVMe, and USB candidate disks;
- mounted child partition exclusion;
- cancellation and EOF at each prompt;
- unplug/replug or identity change between confirmation and revalidation;
- selection record, FAI `disk_var.sh`, ESP parent, and GRUB target agreement;
- full installation, temporary LUKS unlock, first-boot rotation, and permanent-user finalization.

These tests are intentionally not simulated as proof of hardware behavior by the repository's fixture tests.
