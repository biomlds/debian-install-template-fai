#!/usr/bin/env python3
"""Shared installer/signing input. Never print captured secret-tool output."""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import resource
import shutil
import shlex
import stat
import struct
import subprocess
import sys
import termios
import uuid
from pathlib import Path

PREFIX = "Workstation Bootstrap"
MEDIA = Path("/run/fai/kdbx")
SECRETS = Path("/run/fai/workstation-secrets")
EFI = Path("/sys/firmware/efi/efivars")


def validate_ssh_key(private_key, public_key):
    """Check an encrypted OpenSSH envelope and its public key without decrypting.

    OpenSSH stores the public key outside the encrypted section. A failed empty
    password probe alone cannot distinguish an encrypted key from a corrupt file.
    """
    try:
        lines = private_key.read_bytes().strip().splitlines()
        if lines[0] != b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----" or lines[-1] != b"-----END OPENSSH PRIVATE KEY-----":
            raise ValueError("Require OpenSSH private-key format")
        data = base64.b64decode(b"".join(lines[1:-1]), validate=True)
        magic = b"openssh-key-v1\x00"
        if not data.startswith(magic):
            raise ValueError("Invalid OpenSSH magic")
        offset = len(magic)

        def field():
            nonlocal offset
            size = struct.unpack_from(">I", data, offset)[0]
            offset += 4
            end = offset + size
            if end > len(data):
                raise ValueError("Truncated OpenSSH field")
            value = data[offset:end]
            offset = end
            return value

        cipher, kdf, options = field(), field(), field()
        if cipher == b"none" or kdf != b"bcrypt" or len(options) < 9:
            raise ValueError("SSH key must be passphrase-protected using bcrypt")
        salt_size = struct.unpack_from(">I", options)[0]
        if salt_size == 0 or len(options) != salt_size + 8 or struct.unpack_from(">I", options, salt_size + 4)[0] == 0:
            raise ValueError("Invalid bcrypt options")
        count = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        if count != 1:
            raise ValueError("Require one SSH identity")
        embedded_public = field()
        encrypted = field()
        if not encrypted or offset != len(data):
            raise ValueError("Invalid encrypted SSH payload")
        public = public_key.read_bytes().split()
        if len(public) < 2 or base64.b64decode(public[1], validate=True) != embedded_public:
            raise ValueError("SSH private/public key mismatch")
    except (ValueError, IndexError, struct.error) as error:
        raise RuntimeError(f"Invalid protected SSH key: {error}") from None
    run(["ssh-keygen", "-l", "-f", public_key])


def borg_environment(repository):
    if not Path(repository).is_absolute() or "\n" in repository or "\r" in repository or "\x00" in repository:
        raise RuntimeError("Borg Repository must be an absolute local USB mount path, not SSH/URL")
    return "BORG_REPO=" + shlex.quote(repository) + "\n"


def run(args, data=None):
    result = subprocess.run([str(x) for x in args], input=data, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{Path(str(args[0])).name} failed (output suppressed)")
    return result.stdout


def write(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(data if isinstance(data, bytes) else data.encode())


def write_replacing_symlink(path, data, mode=0o644):
    """Replace a shipped config symlink (write() refuses symlinks)."""
    path = Path(path)
    if path.is_symlink() or path.exists():
        path.unlink()
    write(path, data, mode)


def safe_database(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise RuntimeError("Database path may not contain symlinks")
    info = path.stat()
    owners = {0, os.getuid(), int(os.environ.get("SUDO_UID", os.getuid()))}
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid not in owners:
        raise RuntimeError("Database must be a private regular file owned by root or invoking user")
    return path


def mount_media():
    sources = run(["blkid", "-t", "LABEL=WORKSTATION-KDBX", "-o", "device"]).decode().splitlines()
    if len(sources) != 1:
        raise RuntimeError("Require exactly one WORKSTATION-KDBX filesystem")
    source = Path(sources[0]).resolve()
    if run(["blkid", "-s", "TYPE", "-o", "value", source]).strip() != b"ext4":
        raise RuntimeError("KDBX media must be ext4")
    MEDIA.mkdir(parents=True, exist_ok=True)
    mounted = subprocess.run(["mountpoint", "-q", str(MEDIA)]).returncode == 0
    if not mounted:
        run(["mount", "-o", "ro,nosuid,nodev,noexec", source, MEDIA])
    actual = Path(run(["findmnt", "-rn", "-o", "SOURCE", "--target", MEDIA]).decode().strip()).resolve()
    options = run(["findmnt", "-rn", "-o", "OPTIONS", "--target", MEDIA]).decode().strip().split(",")
    if actual != source or not {"ro", "nosuid", "nodev", "noexec"}.issubset(options):
        raise RuntimeError("Unexpected KDBX mount source/options")
    if sorted(p.name for p in MEDIA.glob("*.kdbx")) != ["Workstation.kdbx"]:
        raise RuntimeError("Require exactly Workstation.kdbx on media")
    return safe_database(MEDIA / "Workstation.kdbx")


def normalize_guid(path):
    """Rewrite a GUID file as canonical 36-char text (no trailing newline).

    sbctl's uuid.Parse rejects the trailing newline that validate_keys(, which
    strips, tolerates."""
    parsed = uuid.UUID(path.read_bytes().strip().decode())
    path.write_bytes(str(parsed).encode())
    os.chmod(path, 0o600)


def validate_keys(root):
    for name in ("PK", "KEK", "db"):
        key = root / "keys" / name / f"{name}.key"
        cert = root / "keys" / name / f"{name}.pem"
        private_pub = run(["openssl", "pkey", "-in", key, "-pubout"])
        public_pub = run(["openssl", "x509", "-in", cert, "-pubkey", "-noout"])
        if private_pub != public_pub:
            raise RuntimeError(f"SecureBoot {name} key/certificate mismatch")
        run(["openssl", "x509", "-in", cert, "-checkend", "0", "-noout"])
    uuid.UUID((root / "GUID").read_text().strip())


def firmware_mode(root):
    variables = list(EFI.glob("SetupMode-*"))
    if len(variables) != 1:
        raise RuntimeError("UEFI variables unavailable")
    if variables[0].read_bytes()[4:5] == b"\x01":
        return "setup"
    for name in ("PK", "KEK", "db"):
        cert = run(["openssl", "x509", "-in", root / "keys" / name / f"{name}.pem", "-outform", "DER"])
        enrolled = list(EFI.glob(f"{name}-*"))
        if len(enrolled) != 1 or cert not in enrolled[0].read_bytes()[4:]:
            raise RuntimeError("Firmware keys differ from KDBX; enter Setup Mode before installing")
    return "enrolled"


def extract(database, root, *, identity=True, console=False):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    database = safe_database(database)
    if run(["findmnt", "-n", "-o", "FSTYPE", "--target", root.parent]).strip() != b"tmpfs":
        raise RuntimeError("Secret directory must reside on tmpfs")
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(root, 0o700)
    master = bytearray()
    try:
        if console:
            terminal_path = None
            for candidate in ("/dev/console", "/dev/tty0", "/dev/tty1", "/dev/ttyS0", "/dev/tty"):
                if os.path.exists(candidate):
                    try:
                        if os.stat(candidate).st_mode & 0o0020000:
                            terminal_path = candidate
                            break
                    except OSError:
                        continue
            if terminal_path is None:
                for candidate in ("/dev/console", "/dev/tty0", "/dev/tty1", "/dev/ttyS0", "/dev/tty"):
                    if os.path.exists(candidate):
                        terminal_path = candidate
                        break
            if terminal_path is None:
                raise RuntimeError("No installer console available for password input")
            fd = None
            try:
                try:
                    fd = os.open(terminal_path, os.O_RDWR | os.O_NOCTTY)
                except OSError as error:
                    raise RuntimeError(f"Cannot open installer console {terminal_path} for password input: {error}") from None
                try:
                    try:
                        settings = termios.tcgetattr(fd)
                    except termios.error as error:
                        raise RuntimeError(f"Console {terminal_path} is not a TTY; cannot disable echo for password input: {error}") from None
                    private = settings.copy()
                    private[3] &= ~termios.ECHO
                    try:
                        try:
                            termios.tcsetattr(fd, termios.TCSAFLUSH, private)
                        except termios.error as error:
                            raise RuntimeError(f"Failed to disable echo on console {terminal_path}: {error}") from None
                        try:
                            os.write(fd, b"KeePassXC master password: ")
                        except OSError as error:
                            raise RuntimeError(f"Failed to write prompt to console {terminal_path}: {error}") from None
                        data = bytearray()
                        while True:
                            try:
                                chunk = os.read(fd, 1)
                            except OSError as error:
                                raise RuntimeError(f"Failed to read from console {terminal_path}: {error}") from None
                            if not chunk:
                                break
                            if chunk in (b"\n", b"\r"):
                                break
                            data.extend(chunk)
                        if not data:
                            raise RuntimeError("Empty password or no input from installer console")
                        master.extend(bytes(data))
                    finally:
                        try:
                            termios.tcsetattr(fd, termios.TCSAFLUSH, settings)
                        except Exception:
                            pass
                        try:
                            os.write(fd, b"\n")
                        except Exception:
                            pass
                finally:
                    if fd is not None:
                        os.close(fd)
                        fd = None
            except RuntimeError:
                raise
            except Exception as error:
                raise RuntimeError(f"Cannot read master password from installer console: {error}") from None
        else:
            if not hasattr(sys.stdin, 'seekable') or not sys.stdin.seekable():
                terminal_path = None
                for candidate in ("/dev/console", "/dev/tty0", "/dev/tty1", "/dev/ttyS0", "/dev/tty"):
                    if os.path.exists(candidate):
                        try:
                            if os.stat(candidate).st_mode & 0o0020000:
                                terminal_path = candidate
                                break
                        except OSError:
                            continue
                if terminal_path is None:
                    for candidate in ("/dev/console", "/dev/tty0", "/dev/tty1", "/dev/ttyS0", "/dev/tty"):
                        if os.path.exists(candidate):
                            terminal_path = candidate
                            break
                if terminal_path is None:
                    raise RuntimeError("No console available for password input")
                fd = None
                try:
                    try:
                        fd = os.open(terminal_path, os.O_RDWR | os.O_NOCTTY)
                    except OSError as error:
                        raise RuntimeError(f"Cannot open console {terminal_path}: {error}") from None
                    try:
                        try:
                            settings = termios.tcgetattr(fd)
                        except termios.error as error:
                            raise RuntimeError(f"Console {terminal_path} is not a TTY: {error}") from None
                        private = settings.copy()
                        private[3] &= ~termios.ECHO
                        try:
                            termios.tcsetattr(fd, termios.TCSAFLUSH, private)
                            os.write(fd, b"KeePassXC master password: ")
                            data = bytearray()
                            while True:
                                try:
                                    chunk = os.read(fd, 1)
                                except OSError as error:
                                    raise RuntimeError(f"Failed to read from console: {error}") from None
                                if not chunk:
                                    break
                                if chunk in (b"\n", b"\r"):
                                    break
                                data.extend(chunk)
                            if not data:
                                raise RuntimeError("Empty password or no input from console")
                            master.extend(bytes(data))
                        finally:
                            try:
                                termios.tcsetattr(fd, termios.TCSAFLUSH, settings)
                            except Exception:
                                pass
                            try:
                                os.write(fd, b"\n")
                            except Exception:
                                pass
                    finally:
                        if fd is not None:
                            os.close(fd)
                            fd = None
                except RuntimeError:
                    raise
                except Exception as error:
                    raise RuntimeError(f"Cannot read master password from console: {error}") from None
            else:
                try:
                    master.extend(getpass.getpass("KeePassXC master password: ").encode())
                except Exception:
                    terminal_path = None
                    for candidate in ("/dev/console", "/dev/tty0", "/dev/tty1", "/dev/ttyS0", "/dev/tty"):
                        if os.path.exists(candidate):
                            terminal_path = candidate
                            break
                    if terminal_path is None:
                        raise RuntimeError("No console available for password input")
                    fd = None
                    try:
                        fd = os.open(terminal_path, os.O_RDWR | os.O_NOCTTY)
                        try:
                            settings = termios.tcgetattr(fd)
                            private = settings.copy()
                            private[3] &= ~termios.ECHO
                            try:
                                termios.tcsetattr(fd, termios.TCSAFLUSH, private)
                                os.write(fd, b"KeePassXC master password: ")
                                data = bytearray()
                                while True:
                                    chunk = os.read(fd, 1)
                                    if not chunk:
                                        break
                                    if chunk in (b"\n", b"\r"):
                                        break
                                    data.extend(chunk)
                                if not data:
                                    raise RuntimeError("Empty password or no input from console")
                                master.extend(bytes(data))
                            finally:
                                try:
                                    termios.tcsetattr(fd, termios.TCSAFLUSH, settings)
                                except Exception:
                                    pass
                                try:
                                    os.write(fd, b"\n")
                                except Exception:
                                    pass
                        finally:
                            if fd is not None:
                                os.close(fd)
                                fd = None
                    except RuntimeError:
                        raise
                    except Exception as error:
                        raise RuntimeError(f"Cannot read master password from console: {error}") from None
        if not master:
            raise RuntimeError("Empty database master password")

        def cli(*args):
            return run(["keepassxc-cli", *args], bytes(master) + b"\n")

        def attr(entry, name, default=None):
            try:
                value = cli("show", "-q", "-s", "-a", name, database, f"{PREFIX}/{entry}").decode().rstrip("\r\n")
            except RuntimeError:
                if default is None:
                    raise RuntimeError(f"Missing KDBX field: {entry}.{name}") from None
                value = ""
            value = value or default
            if value is None or "\n" in value or "\r" in value or "\x00" in value:
                raise RuntimeError(f"Invalid KDBX field: {entry}.{name}")
            return value

        def attachment(entry, name, destination, optional=False):
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                cli("attachment-export", "-q", database, f"{PREFIX}/{entry}", name, destination)
                if not destination.is_file() or not destination.stat().st_size:
                    raise RuntimeError("Empty attachment")
                os.chmod(destination, 0o600)
            except RuntimeError:
                destination.unlink(missing_ok=True)
                if not optional:
                    raise RuntimeError(f"Missing KDBX attachment: {entry}/{name}") from None

        for name in ("PK", "KEK", "db"):
            for suffix in ("key", "pem"):
                attachment("SecureBoot", f"{name}.{suffix}", root / "keys" / name / f"{name}.{suffix}")
        attachment("SecureBoot", "GUID", root / "GUID")
        normalize_guid(root / "GUID")
        validate_keys(root)
        if not identity:
            return
        fields = {
            "username": ("Identity", "Username"), "full_name": ("Identity", "FullName"),
            "hostname": ("Identity", "Hostname"), "timezone": ("Identity", "Timezone", "America/Edmonton"),
            "locale": ("Identity", "Locale", "en_CA.UTF-8"), "groups": ("Login", "Groups", "sudo,audio,video,render,input,plugdev,incus-admin"),
            "git_name": ("Git", "Name"), "git_email": ("Git", "Email"),
            "chezmoi_repo": ("Chezmoi", "Repository"), "chezmoi_branch": ("Chezmoi", "Branch", "main"),
            "borg_repository": ("Borg", "Repository"), "vorta_profile": ("Vorta", "ProfileName", "Personal files"),
            "vorta_sources": ("Vorta", "SourcePaths", "~"), "vault": ("Cryptomator", "VaultPath"),
        }
        model = {key: attr(*spec) for key, spec in fields.items()}
        borg_environment(model["borg_repository"])
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", model["username"]) or model["username"] in {"root", "provision"}:
            raise RuntimeError("Invalid permanent username")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,62}", model["hostname"]) or ":" in model["full_name"]:
            raise RuntimeError("Invalid hostname/full name")
        groups = model["groups"].split(",")
        if "sudo" not in groups or any(not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", g) for g in groups):
            raise RuntimeError("Invalid groups or missing sudo")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+_[A-Za-z0-9_.@-]+", model["locale"]):
            raise RuntimeError("Invalid locale")
        if "@" not in model["git_email"]:
            raise RuntimeError("Invalid Git email")
        vault = model["vault"].replace("$HOME", "~", 1)
        if vault.startswith("~/"):
            vault = vault[2:]
        if vault != "~" and (Path(vault).is_absolute() or ".." in Path(vault).parts):
            raise RuntimeError("Cryptomator path must be relative to permanent user's home")
        zone = (Path("/usr/share/zoneinfo") / model["timezone"]).resolve()
        if not zone.is_relative_to("/usr/share/zoneinfo") or not zone.is_file():
            raise RuntimeError("Invalid timezone")
        for entry, name, minimum in (("Login", "login", 12), ("LUKS", "luks", 16)):
            value = attr(entry, "Password")
            if len(value) < minimum or (entry == "Login" and ":" in value):
                raise RuntimeError(f"Invalid {entry} credential")
            write(root / name, value)
        for entry, name, destination, optional in (
            ("SSH", "id_ed25519", "ssh-private", False), ("SSH", "id_ed25519.pub", "ssh-public", False),
            ("SSH", "config", "ssh-config", True),
            ("Vorta", "excludes.txt", "vorta-excludes", True),
        ):
            attachment(entry, name, root / destination, optional)
        validate_ssh_key(root / "ssh-private", root / "ssh-public")
        write(root / "identity.json", json.dumps(model))
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    finally:
        for index in range(len(master)):
            master[index] = 0


def install_identity(target, root=SECRETS):
    model = json.loads((root / "identity.json").read_text())
    user = model["username"]

    def chroot(*args, data=None):
        return run(["chroot", target, *args], data)

    if subprocess.run(["chroot", str(target), "id", user], capture_output=True).returncode:
        chroot("useradd", "-m", "-s", "/bin/bash", "-c", model["full_name"], user)
    for group in model["groups"].split(","):
        if subprocess.run(["chroot", str(target), "getent", "group", group], capture_output=True).returncode == 0:
            chroot("usermod", "-aG", group, user)
    chroot("chpasswd", data=user.encode() + b":" + (root / "login").read_bytes() + b"\n")
    uid = int(chroot("id", "-u", user))
    gid = int(chroot("id", "-g", user))
    home = target / "home" / user
    for source, dest, mode in (("ssh-private", ".ssh/id_ed25519", 0o600), ("ssh-public", ".ssh/id_ed25519.pub", 0o644),
                               ("ssh-public", ".ssh/authorized_keys", 0o600), ("ssh-config", ".ssh/config", 0o600),
                                ("vorta-excludes", ".config/borg/vorta-excludes.txt", 0o600)):
        if (root / source).is_file():
            write(home / dest, (root / source).read_bytes(), mode)
    os.chmod(home / ".ssh", 0o700)
    write(home / ".config/workstation/setup.json", json.dumps(model, indent=2))
    write(home / ".config/borg/bootstrap.env", borg_environment(model["borg_repository"]))
    write(home / ".config/borg/VORTA-FIRST-LOGIN.txt",
          f"Repository: {model['borg_repository']}\nProfile: {model['vorta_profile']}\nSources: {model['vorta_sources']}\nMount the USB drive before backup. Configure local repository encryption/passphrase in Vorta after login. No SSH is used.\n")
    vault = model["vault"].replace("$HOME", "~", 1)
    vault = "" if vault == "~" else vault.removeprefix("~/")
    (home / vault).mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in [home, *home.rglob("*")]:
        if not path.is_symlink():
            os.chown(path, uid, gid)
    for field in ("name", "email"):
        chroot("runuser", "-u", user, "--", "git", "config", "--global", f"user.{field}", model[f"git_{field}"])
    # write() uses O_NOFOLLOW. Debian can ship etc/default/locale as a symlink
    # to locale.conf, so replace symlinks for these non-secret target files.
    write_replacing_symlink(target / "etc/hostname", model["hostname"] + "\n")
    hosts = target / "etc/hosts"
    lines = [line for line in hosts.read_text().splitlines() if not line.startswith("127.0.1.1")]
    write_replacing_symlink(hosts, "\n".join([*lines, f"127.0.1.1 {model['hostname']}", ""]))
    write_replacing_symlink(target / "etc/locale.gen", f"{model['locale']} UTF-8\n")
    write_replacing_symlink(target / "etc/default/locale", f"LANG={model['locale']}\n")
    (target / "etc/localtime").unlink(missing_ok=True)
    (target / "etc/localtime").symlink_to("/usr/share/zoneinfo/" + model["timezone"])
    write_replacing_symlink(target / "etc/timezone", model["timezone"] + "\n")
    chroot("locale-gen")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("mount", "preflight", "identity", "cleanup"))
    parser.add_argument("--target", type=Path, default=Path("/target"))
    args = parser.parse_args()
    if os.geteuid():
        raise RuntimeError("Run as root")
    if args.action == "mount":
        mount_media()
    elif args.action == "preflight":
        database = mount_media()
        if SECRETS.exists():
            shutil.rmtree(SECRETS)
        extract(database, SECRETS, console=True)
        try:
            firmware_mode(SECRETS)
        except BaseException:
            shutil.rmtree(SECRETS)
            raise
    elif args.action == "identity":
        install_identity(args.target)
    else:
        shutil.rmtree(SECRETS, ignore_errors=True)
        if subprocess.run(["mountpoint", "-q", str(MEDIA)]).returncode == 0:
            run(["umount", MEDIA])


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print(f"Workstation input failed: {error}", file=sys.stderr)
        sys.exit(1)
