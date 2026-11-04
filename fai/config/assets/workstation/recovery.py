"""Resolve a recovery ESP on the selected LUKS disk, never by label/order."""
import argparse
import json
import os
import subprocess

ESP_TYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


def select_esp(nodes, luks, requested=None):
    by_path = {os.path.realpath(node["path"]): node for node in nodes}

    def disk(path):
        seen = set()
        while path in by_path and path not in seen:
            seen.add(path)
            node = by_path[path]
            if node["type"] == "disk":
                return path
            parent = node.get("pkname")
            if not parent:
                break
            path = os.path.realpath(parent if parent.startswith("/") else "/dev/" + parent)
        raise RuntimeError("Cannot resolve selected partition's physical disk")

    parent = disk(os.path.realpath(luks))
    candidates = [path for path, node in by_path.items()
                  if node.get("type") == "part" and node.get("fstype") == "vfat"
                  and str(node.get("parttype", "")).lower() == ESP_TYPE and disk(path) == parent]
    if requested:
        requested = os.path.realpath(requested)
        if requested not in candidates:
            raise RuntimeError("ESP must be a FAT EFI System Partition on the selected LUKS disk")
        return requested
    if len(candidates) != 1:
        raise RuntimeError("Require an explicit ESP: selected disk has zero or multiple FAT EFI System Partitions")
    return candidates[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("luks")
    parser.add_argument("esp", nargs="?")
    args = parser.parse_args()
    inventory = subprocess.check_output(["lsblk", "--json", "--list", "--paths", "--output",
                                         "PATH,PKNAME,TYPE,FSTYPE,PARTTYPE"])
    try:
        print(select_esp(json.loads(inventory)["blockdevices"], args.luks, args.esp))
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
