#!/usr/bin/env python3
"""Offline-key UKI maintenance and protected recovery snapshot lifecycle."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import kdbx

STATE = Path("/var/lib/workstation-uki")
ESP = Path("/boot")
LINUX = ESP / "EFI/Linux"
CERT = Path("/etc/workstation/secureboot/db.pem")


def run(*args):
    return kdbx.run(list(args)).decode().strip()


def run_snapper(*args):
    """Run snapper without D-Bus when no system bus exists (install chroot)."""
    command = [str(x) for x in args]
    if not Path("/run/dbus/system_bus_socket").exists():
        command.insert(1, "--no-dbus")
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).decode(errors="replace").strip()
        detail = " | ".join(detail.splitlines()[-3:]) or "no output"
        raise RuntimeError(f"snapper failed ({result.returncode}): {detail}")
    return result.stdout.decode().strip()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".new")
    kdbx.write(temp, data)
    with temp.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temp, path)
    descriptor = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_state():
    path = STATE / "state.json"
    return json.loads(path.read_text()) if path.exists() else {"schema": 1, "protected": [], "known_good": None}


def save_state(state):
    atomic(STATE / "state.json", json.dumps(state, indent=2).encode() + b"\n")


def recovery_id(cmdline=None):
    text = Path("/proc/cmdline").read_text() if cmdline is None else cmdline
    match = re.search(r"(?:^|\s)workstation\.snapshot=([0-9]+)(?:\s|$)", text)
    return int(match[1]) if match else None


def retained(records, known_good, current=None, limit=3):
    """Keep the pinned baseline/current recovery and newest other candidates."""
    pinned = {value for value in (known_good, current) if value is not None}
    ids = [record["id"] for record in records]
    if not pinned.issubset(ids):
        raise RuntimeError("Pinned recovery snapshot missing from state")
    chosen = set(pinned)
    for number in reversed(ids):
        if len(chosen) < limit:
            chosen.add(number)
    return chosen


def hash_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(path, cert=CERT):
    run("sbverify", "--cert", cert, path)


def secure_boot_enabled():
    variables = list(kdbx.EFI.glob("SecureBoot-*"))
    if len(variables) != 1 or variables[0].read_bytes()[4:5] != b"\x01":
        raise RuntimeError("Secure Boot is disabled; enable it before confirming recovery")
    cert = kdbx.run(["openssl", "x509", "-in", CERT, "-outform", "DER"])
    enrolled = list(kdbx.EFI.glob("db-*"))
    if len(enrolled) != 1 or cert not in enrolled[0].read_bytes()[4:]:
        raise RuntimeError("Installed signing certificate is not enrolled in firmware db")


def kernel_archive(root):
    version = (root / "etc/workstation/kernel-version").read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", version):
        raise RuntimeError("Invalid saved kernel version")
    archive = root / "usr/lib/workstation/kernels" / version
    if not (root / "usr/lib/modules" / version).is_dir():
        raise RuntimeError("Snapshot lacks matching kernel modules")
    if not all((archive / name).is_file() for name in ("vmlinuz", "initrd")):
        raise RuntimeError("Snapshot lacks matching kernel/initrd")
    return archive


def require_esp(*, reserve=False):
    if run("findmnt", "-n", "-o", "FSTYPE", "--mountpoint", ESP) != "vfat":
        raise RuntimeError("ESP must be mounted at /boot as vfat")
    LINUX.mkdir(parents=True, exist_ok=True)
    # Reserve room for transient replacement files before touching the working UKI.
    if reserve and shutil.disk_usage(ESP).free < 384 * 1024 * 1024:
        raise RuntimeError("ESP needs at least 384 MiB free for safe UKI replacement")
    if reserve and shutil.disk_usage("/").free < 2 * 1024**3:
        raise RuntimeError("Root needs at least 2 GiB free before maintenance")


def normal_root():
    if recovery_id() is not None:
        raise RuntimeError("This operation requires the normal @root boot")
    options = run("findmnt", "-n", "-o", "OPTIONS", "/").split(",")
    if not any(option in {"subvol=/@root", "subvol=@root"} for option in options):
        raise RuntimeError("Normal root must be the @root Btrfs subvolume")


@contextlib.contextmanager
def maintenance_lock():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    # /run is shared by normal/recovery processes; a lock inside a snapshot's
    # root would refer to a different inode from the live root's lock.
    with Path("/run/workstation-maintenance.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


@contextlib.contextmanager
def keys(args):
    if getattr(args, "secrets", None):
        root = args.secrets
        if run("findmnt", "-n", "-o", "FSTYPE", "--target", root) != "tmpfs":
            raise RuntimeError("Signing keys must reside on tmpfs")
        kdbx.validate_keys(root)
        yield root
        return
    if not args.database:
        raise RuntimeError("Supply --database /path/to/Workstation.kdbx")
    root = Path(tempfile.mkdtemp(prefix="workstation-sign.", dir="/run"))
    root.rmdir()  # extract creates a new private directory itself.
    try:
        kdbx.extract(args.database, root, identity=False)
        kdbx.firmware_mode(root)
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def sign(source, destination, root):
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate = destination.with_name(destination.name + ".new")
    run("sbsign", "--key", root / "keys/db/db.key", "--cert", root / "keys/db/db.pem",
        "--output", candidate, source)
    verify(candidate, root / "keys/db/db.pem")
    with candidate.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(candidate, destination)
    run("sync", "-f", destination.parent)


def sign_bootloader(root):
    source = Path("/usr/lib/systemd/boot/efi/systemd-bootx64.efi")
    # Write signed artifacts ourselves: bootctl update must never replace them.
    for destination in (ESP / "EFI/systemd/systemd-bootx64.efi", ESP / "EFI/BOOT/BOOTX64.EFI"):
        sign(source, destination, root)
    fwupd = Path("/usr/libexec/fwupd/efi/fwupdx64.efi")
    if not fwupd.exists():
        fwupd = Path("/usr/lib/fwupd/efi/fwupdx64.efi")
    if fwupd.exists():
        # fwupd prefers the .signed sibling when installing its capsule loader.
        sign(fwupd, fwupd.with_suffix(".efi.signed"), root)
    atomic(STATE / "boot-source.sha256", hash_file(source).encode())


def base_cmdline():
    luks = Path("/etc/workstation/luks-uuid").read_text().strip()
    if not re.fullmatch(r"[0-9a-f-]{36}", luks):
        raise RuntimeError("Invalid LUKS UUID")
    return f"rd.luks.uuid=luks-{luks} rd.luks.name={luks}=cryptroot root=/dev/mapper/cryptroot rootfstype=btrfs"


def build_normal():
    normal_root_check = Path("/run/workstation-install")
    if not normal_root_check.exists():
        normal_root()
    kernels = [p for p in Path("/usr/lib/modules").iterdir() if p.is_dir() and (ESP / f"vmlinuz-{p.name}").is_file()]
    if not kernels:
        raise RuntimeError("No installed kernel image found")
    ordered = subprocess.run(["sort", "-V"], input="\n".join(p.name for p in kernels),
                             capture_output=True, text=True, check=True).stdout.splitlines()
    version = ordered[-1]
    archive = Path("/usr/lib/workstation/kernels") / version
    archive.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ESP / f"vmlinuz-{version}", archive / "vmlinuz")
    run("dracut", "--force", "--no-hostonly", "--kver", version, archive / "initrd")
    atomic(Path("/etc/workstation/kernel-version"), version.encode() + b"\n")
    cmdline = base_cmdline() + " rootflags=subvol=@root rw"
    return build_uki(archive, cmdline, STATE / "staged/debian.efi", "Debian workstation")


def build_uki(archive, cmdline, destination, title):
    destination.parent.mkdir(parents=True, exist_ok=True)
    # @ prefix means file to ukify; pass a file so command-line syntax is unambiguous.
    with tempfile.TemporaryDirectory(prefix="workstation-uki.", dir="/run") as temp:
        temp = Path(temp)
        (temp / "cmdline").write_text(cmdline + "\n")
        os_release = Path("/etc/os-release").read_text()
        os_release = re.sub(r"(?m)^PRETTY_NAME=.*$", f'PRETTY_NAME="{title}"', os_release)
        (temp / "os-release").write_text(os_release)
        run("/usr/lib/systemd/ukify", "build", "--linux", archive / "vmlinuz", "--initrd", archive / "initrd",
            "--cmdline", "@" + str(temp / "cmdline"), "--os-release", "@" + str(temp / "os-release"),
            "--output", destination)
    return destination


def publish_normal(root):
    staged = build_normal()
    signed = STATE / "staged/debian-signed.efi"
    sign(staged, signed, root)
    current = LINUX / "debian.efi"
    if current.exists():
        verify(current)
        atomic(LINUX / "debian-previous.efi", current.read_bytes())
    atomic(current, signed.read_bytes())
    atomic(STATE / "normal.sha256", hash_file(current).encode())
    (STATE / "pending").unlink(missing_ok=True)


def snapshot(root, description="Protected pre-update"):
    number = int(run_snapper("snapper", "-c", "root", "create", "--type", "single", "--print-number",
                             "--description", description))
    saved = Path(f"/.snapshots/{number}/snapshot")
    archive = kernel_archive(saved)
    esp_uuid = run("findmnt", "-n", "-o", "UUID", "--mountpoint", ESP)
    cmdline = (base_cmdline() + f" rootflags=subvol=@snapshots/{number}/snapshot ro systemd.volatile=overlay"
               f" workstation.snapshot={number} rd.fstab=no fstab=no systemd.mask=systemd-remount-fs.service"
                " systemd.mount-extra=/dev/mapper/cryptroot:/home:btrfs:subvol=@home,noatime,compress=zstd"
                " systemd.mount-extra=/dev/mapper/cryptroot:/.snapshots:btrfs:subvol=@snapshots,noatime,compress=zstd"
               f" systemd.mount-extra=UUID={esp_uuid}:/boot:vfat:umask=0077")
    staged = build_uki(archive, cmdline, STATE / f"staged/snapshot-{number}.efi", f"Recovery snapshot {number}")
    destination = LINUX / f"ws-protected-{number}.efi"
    sign(staged, destination, root)
    state = load_state()
    state["protected"].append({"id": number, "sha256": hash_file(destination), "boot_tested": False})
    save_state(state)
    prune(state)
    return number


def prune(state):
    keep = retained(state["protected"], state["known_good"], recovery_id())
    for record in state["protected"][:]:
        number = record["id"]
        if number not in keep:
            (LINUX / f"ws-protected-{number}.efi").unlink(missing_ok=True)
            run("sync", "-f", LINUX)
            run_snapper("snapper", "-c", "root", "delete", str(number))
            (STATE / f"staged/snapshot-{number}.efi").unlink(missing_ok=True)
            state["protected"].remove(record)
            save_state(state)


def confirm():
    secure_boot_enabled()
    number = recovery_id()
    if number is None or run("findmnt", "-n", "-o", "FSTYPE", "/") != "overlay":
        raise RuntimeError("Confirm only while booted into the protected overlay recovery entry")
    uki = LINUX / f"ws-protected-{number}.efi"
    verify(uki)
    # State from snapshot lives in overlay; persist confirmation to real @root.
    with top_level() as top:
        path = top / "@root/var/lib/workstation-uki/state.json"
        actual = json.loads(path.read_text())
        candidate = next((r for r in actual["protected"] if r["id"] == number), None)
        if not candidate or candidate["sha256"] != hash_file(uki):
            raise RuntimeError("Recovery entry not registered in writable root")
        run("systemctl", "is-active", "multi-user.target")
        run("findmnt", "--mountpoint", "/home")
        run("findmnt", "--mountpoint", "/.snapshots")
        candidate["boot_tested"] = True
        actual["known_good"] = number
        atomic(path, json.dumps(actual, indent=2).encode() + b"\n")
    print(f"Pinned boot-tested recovery snapshot {number}")


@contextlib.contextmanager
def top_level():
    with tempfile.TemporaryDirectory(prefix="workstation-top.", dir="/run") as temp:
        top = Path(temp)
        run("mount", "-t", "btrfs", "-o", "subvolid=5", "/dev/mapper/cryptroot", top)
        try:
            yield top
        finally:
            run("umount", top)


def rollback(number, root):
    if recovery_id() is None:
        raise RuntimeError("Rollback requires a protected recovery boot")
    with top_level() as top:
        live_state = json.loads((top / "@root/var/lib/workstation-uki/state.json").read_text())
        if number not in {r["id"] for r in live_state["protected"]}:
            raise RuntimeError("Snapshot is not a registered protected entry")
        source = top / f"@snapshots/{number}/snapshot"
        working = top / "@root"
        candidate = top / "@root-rollback-candidate"
        if candidate.exists():
            raise RuntimeError("Interrupted rollback candidate exists; inspect from live media")
        # Refuse if any process still has the old root mounted outside our top mount.
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            if line.split()[3] == "/@root":
                raise RuntimeError("@root is still mounted; refusing rollback")
        run("btrfs", "subvolume", "snapshot", source, candidate)
        atomic(candidate / "var/lib/workstation-uki/state.json", json.dumps(live_state, indent=2).encode())
        staged = build_uki(kernel_archive(candidate),
                           base_cmdline() + " rootflags=subvol=@root rw", STATE / "staged/rollback.efi", "Debian workstation")
        signed = STATE / "staged/rollback-signed.efi"
        sign(staged, signed, root)
        backup = top / f"@root-broken-{time.time_ns()}"
        working.rename(backup)
        try:
            candidate.rename(working)
        except BaseException:
            backup.rename(working)
            raise
        # Explicit rootflags select @root even if the old Btrfs default still exists.
        atomic(LINUX / "debian.efi", signed.read_bytes())
        atomic(working / "var/lib/workstation-uki/normal.sha256", hash_file(LINUX / "debian.efi").encode())
        (working / "var/lib/workstation-uki/pending").unlink(missing_ok=True)
        print(f"Restored @root; preserved broken system as {backup.name}. Reboot manually.")


def check(*, allow_pending=False):
    secure_boot_enabled()
    state = load_state()
    if recovery_id() is not None:
        with top_level() as top:
            state = json.loads((top / "@root/var/lib/workstation-uki/state.json").read_text())
    if state["known_good"] is None:
        raise RuntimeError("No boot-tested recovery baseline: boot a recovery entry and run confirm")
    baseline = next((r for r in state["protected"] if r["id"] == state["known_good"]), None)
    if baseline is None or not baseline.get("boot_tested"):
        raise RuntimeError("Pinned baseline is missing or was never boot-tested")
    for record in state["protected"]:
        path = LINUX / f"ws-protected-{record['id']}.efi"
        verify(path)
        if hash_file(path) != record["sha256"]:
            raise RuntimeError("Protected UKI checksum mismatch")
        if not Path(f"/.snapshots/{record['id']}/snapshot").is_dir():
            raise RuntimeError("Protected snapshot missing")
    for path in (LINUX / "debian.efi", ESP / "EFI/systemd/systemd-bootx64.efi", ESP / "EFI/BOOT/BOOTX64.EFI"):
        verify(path)
    installed_source = STATE / "boot-source.sha256"
    if not allow_pending and (not installed_source.exists() or installed_source.read_text().strip() !=
                              hash_file(Path("/usr/lib/systemd/boot/efi/systemd-bootx64.efi"))):
        raise RuntimeError("systemd-boot package changed; run workstation-update with KDBX")
    if (STATE / "pending").exists() and not allow_pending:
        raise RuntimeError("Boot-stack changes pending: run workstation-update with KDBX")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "sign", "snapshot", "confirm", "check", "status", "update", "rollback", "security", "stage"))
    parser.add_argument("number", nargs="?", type=int)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--secrets", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.geteuid():
        raise RuntimeError("Run as root")
    os.umask(0o077)
    if args.action == "stage":
        STATE.mkdir(parents=True, exist_ok=True)
        atomic(STATE / "pending", b"Boot stack changed; use workstation-update\n")
        return
    with maintenance_lock():
        if args.action == "status":
            if recovery_id() is not None:
                with top_level() as top:
                    print((top / "@root/var/lib/workstation-uki/state.json").read_text())
            else:
                print(json.dumps(load_state(), indent=2))
            return
        require_esp(reserve=args.action not in {"check", "confirm"})
        if args.action == "check":
            check()
            return
        if args.action == "confirm":
            confirm()
            return
        if args.action == "security":
            normal_root()
            check()
            run_snapper("snapper", "-c", "root", "create", "--description", "Before unattended security update", "--cleanup-algorithm", "number")
            # This wrapper, not apt-daily-upgrade, owns all unattended transactions.
            result = subprocess.run(["unattended-upgrade", "--verbose"])
            if result.returncode:
                raise RuntimeError("Unattended security upgrade failed; inspect journal")
            return
        with keys(args) as root:
            if args.action == "rollback":
                if args.number is None:
                    raise RuntimeError("Supply a protected snapshot number")
                rollback(args.number, root)
                return
            if args.action == "install":
                CERT.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / "keys/db/db.pem", CERT)
                publish_normal(root)
                # This marker belongs only to the installer. A saved marker
                # would disable security maintenance after snapshot rollback.
                Path("/run/workstation-install").unlink(missing_ok=True)
                sign_bootloader(root)
                snapshot(root, "Initial installation recovery baseline (not yet boot-tested)")
                if kdbx.firmware_mode(root) == "setup":
                    config = root / "sbctl.conf"
                    kdbx.write(config, f"keydir: {root / 'keys'}\nguid: {root / 'GUID'}\nfiles_db: {root / 'files.json'}\nbundles_db: {root / 'bundles.json'}\nlandlock: false\n")
                    run("sbctl", "--config", config, "enroll-keys", "-m")
                    if kdbx.firmware_mode(root) != "enrolled":
                        raise RuntimeError("Firmware enrollment did not leave Setup Mode")
                return
            normal_root()
            if args.action == "snapshot":
                print(f"Published recovery snapshot {snapshot(root)}; boot it before pinning")
            elif args.action == "sign":
                check(allow_pending=True)
                publish_normal(root)
                sign_bootloader(root)
            elif args.action == "update":
                check(allow_pending=True)
                snapshot(root)
                # The security wrapper uses this same lock. APT itself owns
                # dpkg/frontend transaction locks; direct APT is not orchestrated.
                run("apt-get", "update")
                result = subprocess.run(["apt-get", "full-upgrade"])
                if result.returncode:
                    raise RuntimeError("Upgrade failed; signed recovery entry preserved")
                publish_normal(root)
                sign_bootloader(root)
                check()
                print("Update signed. Reboot manually; test a recovery entry before replacing the pinned baseline.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Workstation maintenance failed: {error}", file=sys.stderr)
        sys.exit(1)
