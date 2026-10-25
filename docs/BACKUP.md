# Backup and personal setup

FAI installs permanent SSH/Git identity and records KDBX setup metadata in
`~/.config/workstation/setup.json`. Borg repository/key references are in
`~/.config/borg/bootstrap.env`; Vorta setup instructions are in
`~/.config/borg/VORTA-FIRST-LOGIN.txt`. Configure the Borg passphrase in Vorta
after login; it is not stored by the installer.

Back up personal files, the KDBX database, Cryptomator vault ciphertext, and any
important Incus VM data. Test restores. Root snapshots share the disk and exclude
home/ESP, so they do not replace Borg or external recovery media.

chezmoi is manual: inspect the scaffold at
`/usr/local/share/workstation-bootstrap/chezmoi`, or initialize your own repository
using the recorded Repository/Branch metadata. Review `chezmoi diff` before
applying. Flatpak installation remains a separate retrying system timer, and
project runtime setup remains inside Incus VMs.
