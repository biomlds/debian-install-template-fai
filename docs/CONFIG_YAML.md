# config.yaml schema

`config/config.yaml.example` is complete and maps to the same internal model as KeePassXC. Secret nodes accept exactly one of:

```yaml
password:
  value: "literal used only from protected removable/encrypted media"
```

or, preferably:

```yaml
password:
  file: "/media/secure/password-file"
```

The YAML and every referenced secret/key file must be a regular file owned by root or the invoking user and have no group/world permissions. Mount FAT/removable media with `umask=0077`, or use an encrypted Linux filesystem. `--allow-insecure-input-permissions` is a recovery-only override and produces a warning boundary; it is not the normal workflow.

Do not commit a populated file. The example contains placeholders only. Borg and Cryptomator passphrases are not first-boot inputs; enter them in Vorta/Cryptomator after login.
