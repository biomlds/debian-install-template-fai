# LUKS temporary-to-permanent rotation

FAI lets setup-storage create LUKS2, then adds the removable-media bootstrap passphrase to a distinct PBKDF2 keyslot, verifies it, and removes setup-storage's generated key. Installation stops if fewer than two active slots exist before removal or verification fails.

First boot locates root with `findmnt`, device-mapper status, and block ancestry, verifies the LUKS UUID against installation metadata, and enumerates active LUKS2 keyslots from JSON metadata. It then:

1. Finds whether the permanent passphrase already matches a slot (resume path).
2. Adds it to an explicitly free PBKDF2 slot using the temporary key.
3. Tests the new slot with `cryptsetup open --test-passphrase`.
4. Records `permanent-verified` state.
5. Refuses removal unless at least two slots are active and permanent/temporary slots differ.
6. Removes the temporary slot using the verified permanent credential.
7. Tests the permanent slot again, then erases/removes the temporary key file.

Interruption before step 5 leaves both keys. Interruption after step 5 leaves the permanent key and a resumable journal. The operation never intentionally removes the final active slot.

Read-only status: `sudo workstation-firstboot status`. Non-disk test: `tests/test-luks-rotation-image.sh` creates a temporary regular file in `/dev/shm` and never opens/modifies a block device.
