# Backup and personal setup

FAI installs permanent SSH/Git identity and records KDBX setup metadata in
`~/.config/workstation/setup.json`. The local USB Borg repository path is in
`~/.config/borg/bootstrap.env`; Vorta setup instructions are in
`~/.config/borg/VORTA-FIRST-LOGIN.txt`. Configure the Borg passphrase in Vorta
after login; it is not stored by the installer.

Use an absolute local path such as `/media/alex/Backup/borg-repo`. Remote SSH/URL
repositories are not accepted. No Borg SSH key is installed; `bootstrap.env`
contains only `BORG_REPO`, never `BORG_RSH` or the passphrase.

Mount the USB filesystem before using Vorta. Use a stable mount point (for
example filesystem UUID with `nofail` in fstab). Confirm it is actually mounted
before initializing a repository, so a missing USB does not create a repository
on the system disk instead. Automatic USB mounting is not configured by FAI.

For a new Borg 1.x repository, choose encrypted `repokey-blake2` or another
supported encrypted mode and a strong passphrase. Existing repositories retain
their original mode. Save the passphrase in daily KeePassXC or enter it in Vorta,
and export a private Borg key backup separately from the USB repository. Do not
write `BORG_PASSPHRASE` into installer files or shell startup files. KeePassXC's
SSH-agent integration is unrelated to this local backup. Disconnect the USB drive
when not backing up and test restores.

Back up personal files, the KDBX database, Cryptomator vault ciphertext, and any
important Incus VM data. Test restores. Root snapshots share the disk and exclude
home/ESP, so they do not replace Borg or external recovery media.

chezmoi is manual: inspect the scaffold at
`/usr/local/share/workstation-bootstrap/chezmoi`, or initialize your own repository
using the recorded Repository/Branch metadata. Review `chezmoi diff` before
applying. Flatpak installation remains a separate retrying system timer, and
project runtime setup remains inside Incus VMs.
