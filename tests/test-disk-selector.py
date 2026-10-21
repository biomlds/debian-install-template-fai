#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "fai/config/assets/disk-selection/disk_selector.py"
spec = importlib.util.spec_from_file_location("disk_selector", MODULE)
assert spec and spec.loader
selector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = selector
spec.loader.exec_module(selector)


def fixture(name: str):
    return json.loads((ROOT / "tests/fixtures" / name).read_text())


def test_local_filtering() -> None:
    data = fixture("disks-local.json")
    mode, media, disks, rejected = selector.eligible_disks(
        data["lsblk"], data["mounts"], data["cmdline"], data["by_id"]
    )
    assert mode == "local"
    assert media == {"/dev/sdb"}
    assert [disk.kernel_path for disk in disks] == ["/dev/sda"]
    assert disks[0].stable_path == "/dev/disk/by-id/wwn-0x5000c500os001"
    assert "/dev/sdb" in rejected and "installation medium" in rejected["/dev/sdb"]
    assert "/dev/nvme0n1" in rejected and "mounted" in rejected["/dev/nvme0n1"]
    assert "/dev/zram0" in rejected
    assert "/dev/ram0" in rejected
    assert "/dev/dm-0" in rejected
    assert "/dev/sr1" in rejected
    assert all(disk.kernel_path not in {"/dev/loop0", "/dev/sr0"} for disk in disks)


def test_network_boot() -> None:
    data = fixture("disks-network.json")
    mode, media, disks, rejected = selector.eligible_disks(
        data["lsblk"], data["mounts"], data["cmdline"], data["by_id"]
    )
    assert mode == "network"
    assert not media and not rejected
    assert len(disks) == 1
    assert disks[0].stable_path.endswith("virtio-DISPOSABLE-TEST-DISK")


def test_unknown_boot_refused() -> None:
    data = fixture("disks-network.json")
    try:
        selector.eligible_disks(data["lsblk"], [], "quiet", data["by_id"])
    except selector.SelectionError as exc:
        assert "neither verified network boot" in str(exc)
    else:
        raise AssertionError("unknown boot source was accepted")


def test_ambiguous_local_media_refused() -> None:
    data = fixture("disks-local.json")
    second = {
        "name": "/dev/sdc", "kname": "sdc", "path": "/dev/sdc", "type": "disk",
        "size": 16000000000, "model": "Second medium", "serial": "MEDIA-002",
        "wwn": "", "tran": "usb", "rm": 1, "ro": 0, "rota": 0,
        "maj:min": "8:32", "mountpoints": [None],
        "children": [{"name": "/dev/sdc1", "kname": "sdc1", "path": "/dev/sdc1", "type": "part",
                      "size": 4000000000, "pkname": "sdc", "fstype": "iso9660", "label": "FAI_CD",
                      "mountpoints": [None]}],
    }
    data["lsblk"]["blockdevices"].append(second)
    try:
        selector.eligible_disks(data["lsblk"], data["mounts"], data["cmdline"], data["by_id"])
    except selector.SelectionError as exc:
        assert "ambiguous" in str(exc) or "More than one" in str(exc)
    else:
        raise AssertionError("ambiguous local media was accepted")


def test_prompt_fail_closed() -> None:
    class FakeTTY:
        def __init__(self, value: str): self.value = value
        def write(self, _value: str): return None
        def flush(self): return None
        def readline(self): value, self.value = self.value, ""; return value

    data = fixture("disks-network.json")
    _, _, disks, _ = selector.eligible_disks(data["lsblk"], data["mounts"], data["cmdline"], data["by_id"])
    for value in ("", "0\n", "x\n", "2\n"):
        try:
            selector.prompt_choice("disk", disks, FakeTTY(value))
        except selector.SelectionError:
            pass
        else:
            raise AssertionError(f"invalid prompt value accepted: {value!r}")
    assert selector.prompt_choice("disk", disks, FakeTTY("\n"), default=1) == disks[0]


def test_record_is_tied_to_identity() -> None:
    data = fixture("disks-network.json")
    mode, media, disks, _ = selector.eligible_disks(data["lsblk"], data["mounts"], data["cmdline"], data["by_id"])
    record = selector.selection_record(disks[0], disks[0], mode, media, False)
    assert record["os_disk"]["identity"] == disks[0].identity
    assert record["boot_disk"]["stable_path"] == record["os_disk"]["stable_path"]
    assert not record["test_only_override"]


def test_incomplete_test_override_refused() -> None:
    data = fixture("disks-network.json")
    _, _, disks, _ = selector.eligible_disks(data["lsblk"], data["mounts"], data["cmdline"], data["by_id"])
    for cmdline in (
        "fai.test_disk_selection=DISPOSABLE_VM_I_UNDERSTAND_THIS_DISK_WILL_BE_ERASED",
        "fai.test_disposable_disk=/dev/vda",
        "fai.test_disk_selection=wrong fai.test_disposable_disk=/dev/vda",
    ):
        try:
            selector.test_override(cmdline, disks)
        except selector.SelectionError as exc:
            assert "Incomplete test-only" in str(exc)
        else:
            raise AssertionError("incomplete test-only override was accepted")


def main() -> None:
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for test in sorted(tests, key=lambda item: item.__name__):
        test()
    print(f"PASS {len(tests)} mocked disk-selector tests")


if __name__ == "__main__":
    main()
