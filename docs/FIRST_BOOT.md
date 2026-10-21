# First boot

Run from the temporary `provision` account. `apply` defaults to KeePassXC; `--source yaml` selects the only alternative primary source. Interactive questions are used only when a required mapped field/attachment is missing, or during documented recovery. `--non-interactive` converts missing values into failures.

```bash
sudo workstation-firstboot validate-input --database /media/secure/Passwords.kdbx
sudo workstation-firstboot apply --database /media/secure/Passwords.kdbx
```

For YAML:

```bash
sudo workstation-firstboot validate-input --source yaml --config /media/secure/config.yaml
sudo workstation-firstboot apply --source yaml --config /media/secure/config.yaml
```

Completed stages are recorded in `/var/lib/workstation-firstboot/state.json`. Re-running with the same source skips completed stages. A changed non-secret configuration fingerprint is rejected unless reviewed and acknowledged with `--accept-config-change`.

After all stages pass, log out. Log in using the permanent account and verify sudo, SSH, desktop, and backups. Then run `sudo workstation-firstboot finalize`. Finalize refuses if any stage is incomplete, temporary LUKS material remains, GRUB checks fail, or it was not invoked through sudo by the permanent account. The old provisioning home is retained root-only for manual review.
