# Firmware: encryption, layout, and repack

Target: **DIR-1750 rev A1**, stock firmware (FW111B03-era image, `057` build,
`20191220` timestamp).

## Image format

```
+0x0000   D-Link header (116 bytes)
+0x0074   OpenSSL "Salted__" AES-256-CBC blob
          (decrypts to the actual payload)
```

The payload, once decrypted, is:

```
+0x000000   DTB (device tree blob)
+0x1A0000   squashfs (xz-compressed root filesystem)
```

## Key derivation

The AES key/IV are **not** a static string — they come from an HMAC over the
model name, then are fed to `openssl enc` in the usual password-KDF way:

```bash
# derive the passphrase (hex digest):
echo -n "DIR-1750" | openssl dgst -sha1 -hmac "MT7629B_DIR-1750-S1-1904"
# -> 8825167f33caba4fb71519db9313d6d41003121e
```

That hex digest is the `-k` passphrase for OpenSSL's AES-256-CBC with an MD5 KDF.

## Decrypt

```bash
# strip the 116-byte D-Link header, then decrypt:
dd if=firmware.bin bs=1 skip=116 of=enc.bin
openssl enc -d -aes-256-cbc -md md5 \
  -k 8825167f33caba4fb71519db9313d6d41003121e \
  -in enc.bin -out payload.bin
```

`binwalk payload.bin` then shows the DTB at 0 and the xz squashfs at `0x1A0000`.

## Repack

1. `unsquashfs` the root filesystem, edit it.
2. Rebuild to fit the **original region size** (pad with zeros to the exact
   original length so the header's length fields don't need editing):

   ```bash
   mksquashfs rootfs/ new.squashfs \
     -comp xz -b 262144 -all-root -Xbcj arm -noappend
   ```
3. Splice the new squashfs back at `0x1A0000` of the payload, zero-pad to the
   original payload length.
4. Re-encrypt with the same key and prepend the original 116-byte header:

   ```bash
   openssl enc -aes-256-cbc -md md5 \
     -k 8825167f33caba4fb71519db9313d6d41003121e \
     -in payload.bin -out enc.bin
   # prepend header bytes 0..115 from the original image, then flash.
   ```

Toolchain used: `binwalk` 3.1, `unblob`, `unsquashfs`/`mksquashfs` 4.7.

## Important: don't rely on reflashing to change `/etc`

See [root-access.md](root-access.md) — `/etc` is an OverlayFS and firmware
flashes do **not** clear the overlay. Changes to `/etc` made on a running build
persist and shadow whatever your new image ships. Edit `/etc` live over SSH
instead; factory reset to clear the overlay.
