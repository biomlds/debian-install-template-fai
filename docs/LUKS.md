# LUKS2

setup-storage creates LUKS2 with Argon2id. `10-luks-key` adds the permanent KDBX
passphrase into a distinct Argon2id slot, verifies it, and only then removes the
setup-storage slot. It refuses to remove a last slot and verifies the removed key
no longer unlocks. The remaining permanent slot is checked again.

`FAI_KEEP_CRYPTKEYFILE=1` preserves the generated setup key only until this
transition; the script deletes it and writes a passphrase-only crypttab:

```text
cryptroot UUID=<LUKS UUID> none luks
```

No temporary LUKS credential is copied to the target for first boot. UKIs embed
the LUKS UUID and mapper name, never a passphrase. TPM auto-unlock is disabled.

Back up the LUKS header to private external storage after installation. To change
the passphrase use cryptsetup's verified key-management workflow, update KDBX,
and test an unlock before removing any old slot. Do not remove the last working
credential. A lost passphrase and absent recovery slot cannot be repaired by an
OS snapshot, Secure Boot key, or firmware reset.
