# Security model

## Public policy

Git, CI, and the ISO contain classes, package names, scripts, schemas, pinned tool versions, and placeholder examples. They contain no permanent passwords, private keys, KeePassXC database, password hashes, bootstrap-media payloads, Borg secrets, or LUKS/GRUB credentials.

## Temporary installation boundary

`tools/prepare-bootstrap.sh` writes a password hash for `provision`, an optional public SSH key, and a temporary LUKS passphrase to an existing ext4 removable filesystem labelled `FAI-BOOTSTRAP`. It disables shell tracing, uses mode 0600, and never prints credentials. Attach this media only during installation and keep it offline afterward.

The temporary LUKS passphrase is retained root-only inside the encrypted target solely so first boot can authorize safe rotation. Until rotation/finalization finishes, possession of that credential permits disk unlock. Treat an incomplete machine as unprovisioned.

## Destructive disk selection

The production installer has no unattended disk parameter. Before partitioning it filters block devices, distinguishes verified network boot from local live media, and requires a unique local installation-medium identity when booted from ISO/USB. Mounted devices—including the mounted bootstrap medium—cannot be targets. The selection is tied to model, serial, WWN, size, major/minor number, kernel path, and preferred stable ID, then re-read immediately before setup-storage.

The confirmation phrase contains the selected stable-ID basename (`ERASE …`) when available, otherwise the selected kernel name; it is never a generic yes/no. EOF, cancellation, ambiguity, identity change, newly mounted children, or loss of the stable symlink fails closed. Split OS/bootloader disks are rejected.

An automated override exists only for disposable VMs. It requires an exact conspicuous acknowledgement, an explicitly named disposable disk, and successful `systemd-detect-virt --vm`; it is not a production fallback.

## First boot

Secrets are not command arguments or log fields. Unavoidable transient secret files live under root-only `/run`, are overwritten on a best-effort basis, and are removed by cleanup. Source YAML and referenced files are rejected if group/world-readable unless an explicit recovery override is used. Debug modes are refused.

The log records stage names and success/failure type only. The state journal contains no secret values.
