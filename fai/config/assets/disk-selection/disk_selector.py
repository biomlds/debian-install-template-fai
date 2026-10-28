#!/usr/bin/env python3
"""Interactive, fail-closed FAI installation disk selector.

The module keeps parsing/filtering pure enough for fixture tests. Production selection
uses lsblk/findmnt, persists stable identity, and revalidates immediately before the
partition hook calls setup-storage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import termios
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, TextIO

SCHEMA = 1
DEFAULT_JSON = Path("/run/fai/disk-selection.json")
DEFAULT_ENV = Path("/run/fai/disk-selection.env")
KNOWN_LIVE_TARGETS = (
    "/run/live/medium",
    "/lib/live/mount/medium",
    "/cdrom",
    "/media/cdrom",
    "/run/archiso/bootmnt",
    "/run/initramfs/live",
)
EXCLUDED_TYPES = {"loop", "rom", "ram", "zram", "dm", "crypt", "lvm", "mpath"}
TEST_ACK = "DISPOSABLE_VM_I_UNDERSTAND_THIS_DISK_WILL_BE_ERASED"


class SelectionError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise SelectionError(message)


def run_json(command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if proc.returncode:
        fail(f"{Path(command[0]).name} failed while discovering disks.")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SelectionError(f"Invalid JSON from {Path(command[0]).name}.") from exc


def read_cmdline(path: Path = Path("/proc/cmdline")) -> str:
    try:
        return path.read_text().strip()
    except OSError as exc:
        raise SelectionError("Cannot read kernel command line.") from exc


def cmdline_value(cmdline: str, key: str) -> str | None:
    prefix = key + "="
    for token in shlex.split(cmdline):
        if token.startswith(prefix):
            return token[len(prefix):]
    return None


def flatten_nodes(nodes: list[dict[str, Any]], parent: str | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in nodes:
        node = dict(raw)
        node["_parent"] = parent
        children = node.pop("children", []) or []
        result.append(node)
        child_parent = str(node.get("path") or node.get("name") or "")
        result.extend(flatten_nodes(children, child_parent))
    return result


def flatten_mounts(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in nodes:
        node = dict(raw)
        children = node.pop("children", []) or []
        result.append(node)
        result.extend(flatten_mounts(children))
    return result


def normalized_mountpoints(node: dict[str, Any]) -> list[str]:
    value = node.get("mountpoints")
    if value is None:
        value = [node.get("mountpoint")]
    elif isinstance(value, str):
        value = [value]
    return [str(item) for item in value or [] if item]


def node_path(node: dict[str, Any]) -> str:
    path = str(node.get("path") or "")
    if path:
        return path
    name = str(node.get("name") or "")
    return name if name.startswith("/dev/") else f"/dev/{name}"


def parent_disk(path: str, flat: list[dict[str, Any]]) -> str | None:
    by_path = {node_path(node): node for node in flat}
    current = os.path.realpath(path)
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        node = by_path.get(current) or by_path.get(path)
        if node is None:
            return None
        if str(node.get("type", "")) in {"disk", "rom"}:
            return node_path(node)
        parent = node.get("pkname") or node.get("_parent")
        if not parent:
            return None
        parent = str(parent)
        current = parent if parent.startswith("/dev/") else f"/dev/{parent}"
        path = current
    return None


def descendants(disk_path: str, flat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for node in flat:
        parent = node.get("pkname") or node.get("_parent")
        if parent:
            parent = str(parent)
            parent = parent if parent.startswith("/dev/") else f"/dev/{parent}"
            by_parent.setdefault(parent, []).append(node)
    result: list[dict[str, Any]] = []
    queue = list(by_parent.get(disk_path, []))
    while queue:
        node = queue.pop(0)
        result.append(node)
        queue.extend(by_parent.get(node_path(node), []))
    return result


def boot_mode(cmdline: str, mounts: list[dict[str, Any]]) -> str:
    root = cmdline_value(cmdline, "root") or ""
    live = any(token in cmdline for token in ("boot=live", "rd.live.image", "iso-scan/filename=", "CDLABEL="))
    network = root in {"/dev/nfs", "nfs", "dhcp"} or root.startswith(("nfs:", "live:http:", "live:https:", "http:", "https:"))
    network = network or any(str(m.get("fstype", "")).lower() in {"nfs", "nfs4"} and str(m.get("target")) == "/" for m in mounts)
    if live:
        return "local"
    if network:
        return "network"
    return "unknown"


def live_label(cmdline: str) -> str | None:
    for pattern in (
        r"(?:^|\s)root=live:CDLABEL=([^\s]+)",
        r"(?:^|\s)root=live:LABEL=([^\s]+)",
        r"(?:^|\s)CDLABEL=([^\s]+)",
    ):
        match = re.search(pattern, cmdline)
        if match:
            return match.group(1).replace("\\x20", " ")
    return None


def installation_media_disks(flat: list[dict[str, Any]], mounts: list[dict[str, Any]], cmdline: str) -> tuple[str, set[str]]:
    mode = boot_mode(cmdline, mounts)
    evidence: set[str] = set()
    label = live_label(cmdline)
    for mount in mounts:
        source = str(mount.get("source") or "")
        target = str(mount.get("target") or "")
        is_live_target = target in KNOWN_LIVE_TARGETS or target.startswith(("/run/live/", "/run/initramfs/live/"))
        if source.startswith("/dev/") and is_live_target:
            disk = parent_disk(source, flat)
            if disk:
                evidence.add(disk)
    if label:
        for node in flat:
            if str(node.get("label") or "") == label:
                disk = parent_disk(node_path(node), flat)
                if disk:
                    evidence.add(disk)
    for node in flat:
        if str(node.get("label") or "") in {"FAI_CD", "FAI-CD", "FAI_LIVE"}:
            disk = parent_disk(node_path(node), flat)
            if disk:
                evidence.add(disk)
    if mode == "local" and len(evidence) != 1:
        fail(f"Local live boot detected, but installation medium identity is ambiguous ({len(evidence)} matching disks).")
    if mode == "unknown":
        fail("Boot source is neither verified network boot nor an identifiable local FAI medium.")
    if len(evidence) > 1:
        fail("More than one possible installation-medium disk was detected.")
    return mode, evidence


def choose_stable_id(real_path: str, links: dict[str, str]) -> str:
    matches = [link for link, target in links.items() if os.path.realpath(target) == real_path and "-part" not in Path(link).name]
    def rank(link: str) -> tuple[int, str]:
        name = Path(link).name
        if name.startswith("wwn-"):
            return (0, name)
        if name.startswith("nvme-eui.") or name.startswith("nvme-uuid."):
            return (1, name)
        if name.startswith("ata-"):
            return (2, name)
        if name.startswith("usb-"):
            return (3, name)
        return (4, name)
    return sorted(matches, key=rank)[0] if matches else real_path


def discover_by_id(directory: Path = Path("/dev/disk/by-id")) -> dict[str, str]:
    links: dict[str, str] = {}
    if not directory.is_dir():
        return links
    for entry in directory.iterdir():
        try:
            links[str(entry)] = os.path.realpath(entry)
        except OSError:
            continue
    return links


@dataclass(frozen=True)
class Disk:
    kernel_path: str
    stable_path: str
    kname: str
    maj_min: str
    size: int
    model: str
    serial: str
    wwn: str
    transport: str
    removable: bool
    rotational: bool
    summary: tuple[str, ...]

    @property
    def identity(self) -> str:
        payload = {
            "kernel_path": self.kernel_path,
            "stable_path": self.stable_path,
            "kname": self.kname,
            "maj_min": self.maj_min,
            "size": self.size,
            "model": self.model,
            "serial": self.serial,
            "wwn": self.wwn,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @property
    def token(self) -> str:
        return Path(self.stable_path).name if self.stable_path.startswith("/dev/disk/by-id/") else self.kname


def disk_from_node(node: dict[str, Any], flat: list[dict[str, Any]], links: dict[str, str]) -> Disk:
    kernel = os.path.realpath(node_path(node))
    rows = []
    if node.get("fstype") or node.get("label"):
        rows.append(" | ".join([
            Path(node_path(node)).name,
            format_size(int(node.get("size") or 0)),
            str(node.get("fstype") or "-") or "-",
            str(node.get("label") or "-") or "-",
            ",".join(normalized_mountpoints(node)) or "-",
        ]))
    for child in descendants(node_path(node), flat):
        fields = [
            Path(node_path(child)).name,
            format_size(int(child.get("size") or 0)),
            str(child.get("fstype") or "-") or "-",
            str(child.get("label") or "-") or "-",
            ",".join(normalized_mountpoints(child)) or "-",
        ]
        rows.append(" | ".join(fields))
    if not rows:
        rows.append("no existing child partitions reported")
    return Disk(
        kernel_path=kernel,
        stable_path=choose_stable_id(kernel, links),
        kname=Path(str(node.get("kname") or kernel)).name,
        maj_min=str(node.get("maj:min") or node.get("maj_min") or ""),
        size=int(node.get("size") or 0),
        model=str(node.get("model") or "").strip(),
        serial=str(node.get("serial") or "").strip(),
        wwn=str(node.get("wwn") or "").strip(),
        transport=str(node.get("tran") or "").strip(),
        removable=bool(int(node.get("rm") or 0)),
        rotational=bool(int(node.get("rota") or 0)),
        summary=tuple(rows),
    )


def eligible_disks(lsblk_data: dict[str, Any], mounts: list[dict[str, Any]], cmdline: str,
                   links: dict[str, str]) -> tuple[str, set[str], list[Disk], dict[str, str]]:
    flat = flatten_nodes(lsblk_data.get("blockdevices", []))
    mode, media = installation_media_disks(flat, mounts, cmdline)
    eligible: list[Disk] = []
    rejected: dict[str, str] = {}
    for node in flat:
        path = node_path(node)
        dev_type = str(node.get("type") or "")
        if dev_type != "disk":
            continue
        reasons: list[str] = []
        if dev_type in EXCLUDED_TYPES or Path(path).name.startswith(("loop", "ram", "zram", "dm-", "sr")):
            reasons.append("unsupported virtual/device-mapper type")
        if bool(int(node.get("ro") or 0)):
            reasons.append("read-only")
        if path in media:
            reasons.append("installation medium")
        children = descendants(path, flat)
        if normalized_mountpoints(node) or any(normalized_mountpoints(child) for child in children):
            reasons.append("disk or child partition is mounted")
        if any(str(child.get("type") or "") in {"rom"} for child in children):
            reasons.append("optical child device")
        if any(str(child.get("type") or "") in {"dm", "crypt", "lvm", "mpath"} for child in children):
            reasons.append("active device-mapper child")
        if reasons:
            rejected[path] = "; ".join(sorted(set(reasons)))
            continue
        disk = disk_from_node(node, flat, links)
        if disk.size < 10 * 1024**3:
            rejected[path] = "smaller than 10 GiB minimum"
            continue
        eligible.append(disk)
    eligible.sort(key=lambda item: (item.stable_path, item.kernel_path))
    return mode, media, eligible, rejected


def system_inventory() -> tuple[dict[str, Any], list[dict[str, Any]], str, dict[str, str]]:
    lsblk = run_json([
        "lsblk", "--json", "--bytes", "--paths",
        "--output", "NAME,KNAME,PATH,TYPE,SIZE,MODEL,SERIAL,WWN,TRAN,RM,RO,ROTA,MAJ:MIN,PKNAME,FSTYPE,LABEL,UUID,MOUNTPOINTS",
    ])
    findmnt = run_json(["findmnt", "--json", "--output", "SOURCE,TARGET,FSTYPE,OPTIONS"])
    return lsblk, flatten_mounts(list(findmnt.get("filesystems", []))), read_cmdline(), discover_by_id()


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def show_disks(disks: list[Disk], stream: TextIO) -> None:
    print("Eligible physical installation disks:", file=stream)
    for index, disk in enumerate(disks, 1):
        print(
            f"  [{index}] {disk.stable_path}\n"
            f"      kernel={disk.kernel_path} size={format_size(disk.size)} transport={disk.transport or '-'} "
            f"model={disk.model or '-'} serial={disk.serial or '-'}",
            file=stream,
        )
        print("      existing layout:", file=stream)
        for row in disk.summary:
            print(f"        {row}", file=stream)


def show_rejected(rejected: dict[str, str], stream: TextIO) -> None:
    if not rejected:
        return
    print("Excluded disks:", file=stream)
    for path, reason in sorted(rejected.items()):
        print(f"  {path}: {reason}", file=stream)


def prompt_choice(prompt: str, disks: list[Disk], tty: TextIO, default: int | None = None) -> Disk:
    suffix = f" [{default}]" if default is not None else ""
    try:
        tty.write(prompt + suffix + ": ")
        tty.flush()
        value = tty.readline()
    except KeyboardInterrupt as exc:
        raise SelectionError("Disk selection cancelled.") from exc
    if value == "":
        fail("EOF while selecting a disk.")
    value = value.strip()
    if not value and default is not None:
        value = str(default)
    if not value.isdigit() or not 1 <= int(value) <= len(disks):
        fail("Invalid disk selection.")
    return disks[int(value) - 1]


def selection_record(os_disk: Disk, boot_disk: Disk, mode: str, media: set[str], test_only: bool) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "selected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "boot_source": mode,
        "installation_media": sorted(media),
        "test_only_override": test_only,
        "os_disk": {**asdict(os_disk), "identity": os_disk.identity},
        "boot_disk": {**asdict(boot_disk), "identity": boot_disk.identity},
    }


def atomic_write(path: Path, data: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def normalize_dev_path(path: str) -> str:
    if not path:
        return path
    path = str(path)
    path = re.sub(r'^/+dev/+dev/', '/dev/', path)
    path = re.sub(r'^/dev//+', '/dev/', path)
    if path.startswith('/dev/') and '//' in path:
        path = path.replace('//', '/')
    return path


def setup_storage_disk_name(disk: dict[str, Any]) -> str:
    """Return the bare kernel name required by setup-storage's disklist/-D."""
    name = str(disk.get("kname") or "").strip()
    if not name:
        path = normalize_dev_path(str(disk.get("kernel_path") or ""))
        name = path.removeprefix("/dev/")
    if not name or "/" in name or name in {".", ".."}:
        fail("Selected OS disk has an invalid setup-storage device name.")
    return name


def write_record(record: dict[str, Any], json_path: Path, env_path: Path) -> None:
    record = dict(record)
    os_disk = dict(record.get("os_disk", {}))
    boot_disk = dict(record.get("boot_disk", {}))
    for disk in (os_disk, boot_disk):
        if "kernel_path" in disk:
            disk["kernel_path"] = normalize_dev_path(disk["kernel_path"])
        if "stable_path" in disk and disk["stable_path"].startswith("/dev/"):
            disk["stable_path"] = normalize_dev_path(disk["stable_path"])
    record["os_disk"] = os_disk
    record["boot_disk"] = boot_disk
    atomic_write(json_path, json.dumps(record, indent=2, sort_keys=True) + "\n")
    values = {
        "FAI_SELECTED_OS_STABLE": os_disk["stable_path"],
        "FAI_SELECTED_OS_KERNEL": os_disk["kernel_path"],
        "FAI_SELECTED_OS_IDENTITY": os_disk["identity"],
        "FAI_SELECTED_BOOT_STABLE": boot_disk["stable_path"],
        "FAI_SELECTED_BOOT_KERNEL": boot_disk["kernel_path"],
        "FAI_SELECTED_BOOT_IDENTITY": boot_disk["identity"],
        # setup-storage prepends /dev/ when resolving disk1. Passing /dev/sdb
        # here would therefore produce the invalid partition /dev/dev/sdb2.
        "disklist": setup_storage_disk_name(os_disk),
        "BOOT_DEVICE": boot_disk["kernel_path"],
        "PHYSICAL_BOOT_DEVICES": boot_disk["kernel_path"],
    }
    atomic_write(env_path, "".join(f"export {key}={shlex.quote(normalize_dev_path(value) if isinstance(value, str) else value)}\n" for key, value in values.items()))


def test_override(cmdline: str, disks: list[Disk]) -> Disk | None:
    ack = cmdline_value(cmdline, "fai.test_disk_selection")
    requested = cmdline_value(cmdline, "fai.test_disposable_disk")
    if ack is None and requested is None:
        return None
    if ack != TEST_ACK or not requested:
        fail("Incomplete test-only disk override; both exact acknowledgement and disposable disk are required.")
    if subprocess.run(["systemd-detect-virt", "--vm"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        fail("Test-only disk override is permitted only inside a detected virtual machine.")
    requested_real = os.path.realpath(requested)
    for disk in disks:
        if requested in {disk.stable_path, disk.kernel_path} or requested_real == disk.kernel_path:
            return disk
    fail("Test-only disposable disk is not eligible.")


def fresh_eligible() -> tuple[str, set[str], list[Disk], dict[str, str], str]:
    lsblk, mounts, cmdline, links = system_inventory()
    mode, media, disks, rejected = eligible_disks(lsblk, mounts, cmdline, links)
    return mode, media, disks, rejected, cmdline


def revalidate_record(record: dict[str, Any]) -> Disk:
    mode, media, disks, _rejected, _cmdline = fresh_eligible()
    selected = record["os_disk"]
    matches = [disk for disk in disks if disk.stable_path == selected["stable_path"]]
    if len(matches) != 1:
        fail("Selected OS disk is no longer uniquely eligible.")
    current = matches[0]
    if current.identity != selected["identity"]:
        fail("Selected OS disk identity changed after confirmation.")
    boot = record["boot_disk"]
    if boot["stable_path"] != selected["stable_path"] or boot["identity"] != selected["identity"]:
        fail("Split bootloader/OS selection is unsupported by this repository.")
    if mode != record["boot_source"] or sorted(media) != sorted(record["installation_media"]):
        fail("Boot-source or installation-medium identity changed after confirmation.")
    return current


def load_record(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectionError(
            "Cannot load persisted disk selection."
        ) from exc

    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        fail("Unsupported disk-selection schema.")

    if data.get("boot_source") not in {"local", "network"}:
        fail("Persisted disk selection has an invalid boot source.")

    if not isinstance(data.get("test_only_override"), bool):
        fail("Persisted disk selection has an invalid test override flag.")

    media = data.get("installation_media")
    if (
        not isinstance(media, list)
        or not all(isinstance(item, str) for item in media)
    ):
        fail("Persisted disk selection has invalid installation media.")

    required_strings = (
        "kernel_path",
        "stable_path",
        "kname",
        "maj_min",
        "identity",
    )

    optional_strings = (
        "model",
        "serial",
        "wwn",
        "transport",
    )

    for name in ("os_disk", "boot_disk"):
        disk = data.get(name)

        if not isinstance(disk, dict):
            fail(f"Persisted disk selection is missing {name}.")

        for key in required_strings:
            value = disk.get(key)
            if not isinstance(value, str) or not value:
                fail(
                    f"Persisted disk selection has an invalid "
                    f"{name}.{key}."
                )

        for key in optional_strings:
            value = disk.get(key)
            if not isinstance(value, str):
                fail(
                    f"Persisted disk selection has an invalid "
                    f"{name}.{key}."
                )

        if (
            not isinstance(disk.get("size"), int)
            or isinstance(disk["size"], bool)
            or disk["size"] <= 0
        ):
            fail(
                f"Persisted disk selection has an invalid "
                f"{name}.size."
            )

        if not isinstance(disk.get("removable"), bool):
            fail(
                f"Persisted disk selection has an invalid "
                f"{name}.removable."
            )

        if not isinstance(disk.get("rotational"), bool):
            fail(
                f"Persisted disk selection has an invalid "
                f"{name}.rotational."
            )

        summary = disk.get("summary")
        if (
            not isinstance(summary, list)
            or not all(isinstance(row, str) for row in summary)
        ):
            fail(
                f"Persisted disk selection has an invalid "
                f"{name}.summary."
            )

    return data


def print_detail(os_disk: Disk, boot_disk: Disk, mode: str, media: set[str], stream: TextIO) -> None:
    print("\nSelected destructive installation plan", file=stream)
    print(f"  OS kernel path:     {os_disk.kernel_path}", file=stream)
    print(f"  OS stable ID:       {os_disk.stable_path}", file=stream)
    print(f"  Model:              {os_disk.model or '-'}", file=stream)
    print(f"  Serial:             {os_disk.serial or '-'}", file=stream)
    print(f"  WWN:                {os_disk.wwn or '-'}", file=stream)
    print(f"  Transport:          {os_disk.transport or '-'}", file=stream)
    print(f"  Size:               {format_size(os_disk.size)}", file=stream)
    print(f"  Bootloader target:  {boot_disk.stable_path}", file=stream)
    print(f"  FAI boot source:    {mode}", file=stream)
    print(f"  Excluded FAI media: {', '.join(sorted(media)) or 'none (verified network boot)'}", file=stream)
    print("  Existing layout:", file=stream)
    for row in os_disk.summary:
        print(f"    {row}", file=stream)
    print("\nWARNING: ALL DATA on the selected OS disk will be DESTROYED.", file=stream)


def active_console_path() -> str | None:
    try:
        active = Path("/sys/class/tty/console/active").read_text().split()
    except OSError:
        return None
    if not active:
        return None
    return f"/dev/{active[-1]}"


def console_candidates(requested: str) -> list[str]:
    candidates = [requested, "/dev/console", "/dev/tty0", "/dev/tty1", "/dev/ttyS0", "/dev/tty"]
    active = active_console_path()
    if active:
        candidates.append(active)
    unique: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in unique:
            continue
        unique.append(candidate)
    return unique


class ConsoleIO:
    def __init__(self, path: str):
        self.path = path
        self.fd = None
        self.old_settings = None

    def __enter__(self):
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY)
        except OSError as exc:
            raise OSError(f"{exc.strerror or exc}") from exc
        try:
            self.old_settings = termios.tcgetattr(self.fd)
        except termios.error:
            self.old_settings = None
        return self

    def write(self, data: str) -> int:
        if self.fd is None:
            raise OSError("Console not open")
        try:
            return os.write(self.fd, data.encode())
        except OSError:
            raise

    def flush(self) -> None:
        return None

    def readline(self) -> str:
        if self.fd is None:
            raise OSError("Console not open")
        data = bytearray()
        while True:
            try:
                chunk = os.read(self.fd, 1)
            except OSError as exc:
                raise OSError(f"{exc.strerror or exc}") from exc
            if not chunk:
                break
            if chunk in (b"\n", b"\r"):
                break
            data.extend(chunk)
        return data.decode(errors="replace")

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            if self.old_settings is not None:
                try:
                    termios.tcsetattr(self.fd, termios.TCSAFLUSH, self.old_settings)
                except Exception:
                    pass
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None


def open_console(path: str) -> ConsoleIO:
    return ConsoleIO(path)


def run_selection(
    tty: TextIO,
    mode: str,
    media: set[str],
    disks: list[Disk],
    rejected: dict[str, str],
    dry_run: bool,
) -> tuple[Disk, Disk]:
    show_rejected(rejected, tty)
    show_disks(disks, tty)
    os_disk = prompt_choice("Select OS target disk number", disks, tty)
    show_disks(disks, tty)
    default = disks.index(os_disk) + 1
    boot_disk = prompt_choice("Select bootloader disk number (Enter uses OS disk)", disks, tty, default)
    if boot_disk.stable_path != os_disk.stable_path:
        fail("Split bootloader/OS disks are unsupported for this single-disk UEFI layout.")
    print_detail(os_disk, boot_disk, mode, media, tty)
    action = "PREVIEW" if dry_run else "ERASE"
    token = f"{action} {os_disk.token}"
    tty.write(f"Type exactly '{token}' to continue: ")
    tty.flush()
    confirmation = tty.readline()
    if confirmation == "":
        fail("EOF during destructive confirmation.")
    if confirmation.rstrip("\r\n") != token:
        fail("Destructive confirmation did not match the selected disk.")
    return os_disk, boot_disk


def interactive_selection(
    mode: str,
    media: set[str],
    disks: list[Disk],
    rejected: dict[str, str],
    requested_tty: str,
    dry_run: bool,
) -> tuple[Disk, Disk]:
    errors: list[str] = []
    for path in console_candidates(requested_tty):
        try:
            with open_console(path) as tty:
                return run_selection(tty, mode, media, disks, rejected, dry_run)
        except OSError as exc:
            errors.append(f"{path}: {exc.strerror or exc}")
    raise SelectionError("Interactive console unavailable: " + "; ".join(errors))


def select_command(args: argparse.Namespace) -> None:
    mode, media, disks, rejected, cmdline = fresh_eligible()
    if not disks:
        fail("No eligible physical installation disks remain after safety filtering.")
    override = test_override(cmdline, disks)
    if override:
        os_disk = boot_disk = override
        test_only = True
    else:
        test_only = False
        os_disk, boot_disk = interactive_selection(
            mode, media, disks, rejected, args.tty, args.dry_run
        )
    record = selection_record(os_disk, boot_disk, mode, media, test_only)
    print_detail(os_disk, boot_disk, mode, media, sys.stdout)
    if args.dry_run:
        print("\nDRY RUN: selection was not persisted and setup-storage was not invoked.")
        return
    write_record(record, Path(args.output), Path(args.env_output))
    revalidate_record(load_record(Path(args.output)))
    print(f"Selection persisted to {args.output}; identity revalidation passed.")


def inventory_command(args: argparse.Namespace) -> None:
    if args.fixture:
        data = json.loads(Path(args.fixture).read_text())
        mode, media, disks, rejected = eligible_disks(data["lsblk"], data["mounts"], data["cmdline"], data.get("by_id", {}))
    else:
        mode, media, disks, rejected, _cmdline = fresh_eligible()
    print(json.dumps({
        "boot_source": mode,
        "installation_media": sorted(media),
        "eligible": [asdict(disk) | {"identity": disk.identity} for disk in disks],
        "rejected": rejected,
    }, indent=2, sort_keys=True))


def revalidate_command(args: argparse.Namespace) -> None:
    disk = revalidate_record(load_record(Path(args.selection)))
    print(f"Revalidated {disk.stable_path} ({disk.model or '-'}, {disk.serial or '-'}, {format_size(disk.size)}).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed FAI installation disk selector")
    sub = parser.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory", help="show eligible and rejected disks without writing")
    inventory.add_argument("--fixture", help="use test fixture JSON instead of host devices")
    select = sub.add_parser("select", help="interactively select OS and bootloader disks")
    select.add_argument("--output", default=str(DEFAULT_JSON))
    select.add_argument("--env-output", default=str(DEFAULT_ENV))
    select.add_argument("--tty", default="/dev/tty")
    select.add_argument("--dry-run", action="store_true")
    revalidate = sub.add_parser("revalidate", help="re-read hardware and verify persisted identity")
    revalidate.add_argument("--selection", default=str(DEFAULT_JSON))
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        if args.command == "inventory":
            inventory_command(args)
        elif args.command == "select":
            select_command(args)
        elif args.command == "revalidate":
            revalidate_command(args)
        return 0
    except SelectionError as exc:
        print(f"DISK SELECTION ABORTED: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("DISK SELECTION ABORTED: cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
