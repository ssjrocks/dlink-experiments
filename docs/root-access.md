# Root access and the OverlayFS gotcha

The stock firmware is a rebadged OpenWrt: `dropbear`, `uci`, `opkg` and LuCI are
all present, just hidden behind the D-Link web UI. Getting a root shell is
mostly about enabling and reaching dropbear.

## SSH: key-only, RSA required

The device's dropbear is **old and only supports `ssh-rsa`**. An ed25519 key is
rejected outright. Generate an RSA key and tell your client to offer the legacy
algorithms:

```
# ~/.ssh/config
Host dir1750
    HostName 192.168.1.254          # whatever static address you give it
    User root
    IdentityFile ~/.ssh/id_dir1750  # RSA-4096
    HostKeyAlgorithms +ssh-rsa
    PubkeyAcceptedAlgorithms +ssh-rsa
```

This dropbear reads **`/etc/dropbear/authorized_keys`** (OpenWrt patch location,
not `~/.ssh/authorized_keys`). Put your public key there.

Config touched to lock it down:
- `/etc/config/dropbear`: enabled, password auth off (key-only).
- Restore the original stock root password hash if you added a temporary one
  during bring-up.

## The OverlayFS gotcha (cost 3 needless reflashes)

`/etc` is an **OverlayFS**: a writable jffs2 `/overlay` layer on top of a
read-only squashfs `/rom`. Two consequences:

1. **Firmware flashes do not clear the overlay.** Any file you wrote to `/etc`
   on a running build will still be there after you flash a *different* image,
   and it **shadows** the `/rom` version your new image ships. A stale
   `authorized_keys` written during an early experiment kept shadowing every
   rebuilt image's copy — so reflashing to "fix" the key never worked.

2. **To change persisted `/etc` config, edit it live over SSH.** That takes
   effect instantly. Rebuilding and reflashing to change `/etc` is the wrong
   tool.

3. A **factory reset** clears the overlay back to `/rom` defaults — the only
   clean way to undo accumulated `/etc` changes.

## Making it a quiet wired lab host

To experiment with Wi-Fi without the shell dropping (Wi-Fi toggles,
ATE/RF-test, crash-reboots), move access onto the wire and keep the device from
interfering with your real LAN:

- Static IP outside your DHCP pool (`/etc/config/network`), gateway + DNS set so
  it still has internet.
- **DHCP server off** (`dhcp.lan.ignore=1`), RA/DHCPv6 disabled, WAN disabled —
  so it's a silent host, not a rogue DHCP server on your LAN.
- Plug a LAN port into your switch. Now `ssh dir1750` is independent of the
  radio, and anything you do to `ra0*`/`rax0*` can't drop you.

Keep backups of `network`/`dhcp` on the device before the cutover.
