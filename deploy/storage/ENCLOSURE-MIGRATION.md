# Runbook - USB-to-SATA adapter -> proper enclosure

The disk does not change. Only the bridge between it and the host does. That single fact drives the
whole procedure: **the filesystem UUID lives on the disk, so it survives the swap**, while the
device name (`/dev/sdb1` today, `/dev/sdc1` during the 2026-08-30 incident) does not and never will.

**Disk identity - the only identifier that matters:**

```
UUID=f2276a43-a56c-4e18-80a1-1845918243d4
```

Never key anything off `/dev/sdb1`. `fstab`, `verify-array.sh` and every check below use the UUID.

---

## What changed since the last swap

After the 2026-08-30 hardening, a bad boot now **fails loudly instead of quietly faking success**.
Expect this and do not treat it as a new fault:

- `docker.service` has `RequiresMountsFor=/mnt/avrana_media`. **If the array does not mount, Docker
  will refuse to start.** That is correct behaviour, not a regression. Previously it started and
  built an empty estate on the root LV.
- `sabnzbd.service` and `mylar3.service` get the same dependency (once their drop-ins are installed
  - see "Install the remaining drop-ins" below).
- `avrana-backup.sh` aborts with **exit 4** if `/mnt/avrana_media` is not a mount point, and writes
  nothing at all - including no `LAST_RUN.json`, so it cannot fake a successful backup.
- `avrana-boot-verify.timer` runs `boot-verify.sh` five minutes after every boot.

---

## BEFORE - while everything still works

```bash
bash deploy/storage/verify-array.sh        # must end ARRAY OK
bash deploy/docker/verify-baseline.sh      # note the count; must be your known-good number
bash scripts/services-health.sh
```

Record the results. You cannot tell whether the new enclosure broke something without knowing what
was true beforehand.

```bash
systemctl --user list-timers --all | grep avrana      # note the next backup time
df -h /mnt/avrana_media                               # note used/avail
```

Then take a backup and let it finish:

```bash
systemctl --user start avrana-backup.service
journalctl --user -u avrana-backup.service -f          # wait for "done: ok"
```

### Clean shutdown

Order matters - the 2026-08-30 damage came from the array vanishing under a running fleet with
40 databases open.

```bash
sudo systemctl stop docker docker.socket    # stops all 41 containers
sudo systemctl stop mylar3 sabnzbd          # the two bare-metal array consumers
systemctl --user stop avrana-backup.timer avrana-boot-verify.timer
sync
sudo systemctl stop mnt-avrana_media.mount  # unmount cleanly, do not skip this
findmnt /mnt/avrana_media || echo "unmounted cleanly"
sudo poweroff
```

Unmounting before shutdown is what flushes the write cache. The last incident's
`Synchronize Cache(10) failed` is exactly the failure this step prevents.

---

## HARDWARE

1. **Host fully powered off.** Not suspended. Confirm the fans/LEDs are off.
2. Remove the disk from the USB-to-SATA adapter.
3. Seat it in the new enclosure. Screws in - an 8 TB 3.5" disk that shifts in transit is the next
   incident.
4. **Connect enclosure power first. Power the enclosure ON and let it spin up** - listen for it, or
   watch its LED settle. A 3.5" disk takes several seconds to reach speed.
5. **Then** connect USB to the host.
6. **Then** power on the host.

Powering the enclosure before the host is the whole point: it guarantees the disk has enumerated
before systemd looks for the mount. The reverse order is how you get a boot where the array is
"absent" only because it was still spinning up.

Prefer a rear-panel USB 3 port directly on the mini-PC - no hub.

---

## AFTER BOOT

### 1. Did the disk enumerate at all?

```bash
lsusb                                                        # new bridge should be listed
lsblk -o NAME,SIZE,FSTYPE,UUID,MOUNTPOINT
ls -l /dev/disk/by-uuid/f2276a43-a56c-4e18-80a1-1845918243d4
```

The device letter may differ. That is fine and expected. The **UUID must be present**.

### 2. Storage preflight

```bash
bash deploy/storage/verify-array.sh
```

Must end `ARRAY OK`. It independently checks the mountpoint, the UUID, ext4, read-write (not
remounted ro), capacity ~7.2-7.3 TiB, the expected top-level directories, and - the check that
matters most - that Docker's data-root physically resides on the array and not the root LV.

### 3. Did the Docker mount dependency behave?

```bash
systemctl show docker.service -p RequiresMountsFor --value    # -> /mnt/avrana_media
systemctl is-active docker                                    # -> active
docker info --format '{{.DockerRootDir}}'                     # -> /mnt/avrana_media/docker
stat -c %d /mnt/avrana_media  ;  stat -c %d /                 # MUST differ
```

Those last two numbers being equal means the array is not mounted and Docker is on the root LV.
That is the 2026-08-30 fault; stop immediately.

### 4. Baseline and health

```bash
bash deploy/docker/verify-baseline.sh
bash scripts/services-health.sh
systemctl --user start avrana-boot-verify.service   # or just wait 5 min for the timer
```

Compare against the numbers recorded BEFORE. Then re-arm what you stopped:

```bash
systemctl --user start avrana-backup.timer avrana-boot-verify.timer
```

Note: raw-TCP services (`wyoming-piper` :10200, `speech-to-phrase` :10300) speak the Wyoming
protocol, **not HTTP**. `curl` against them returns nothing and that is correct. `verify-baseline.sh`
deliberately does not probe them; if you ever add them, use its `t()` TCP helper, never `p()`.

---

## If the array does NOT mount

**Do not improvise. Do not run `docker compose up`.**

Running Compose against an absent array is how you manufacture a counterfeit stack: Compose will
happily create fresh containers and empty volumes on the root LV while 2.6 T of real data sits on
an unmounted disk. Nothing about the result will look obviously wrong.

With the hardening in place Docker should already have refused to start. Verify that rather than
assuming it:

```bash
systemctl status docker                    # expect inactive/failed on the mount dependency
systemctl status mnt-avrana_media.mount    # the real error is here
findmnt /mnt/avrana_media || echo "NOT MOUNTED - correct to leave Docker down"
```

Then work the hardware, in this order:

1. **Is it on the bus?** `lsusb`. If the bridge is not listed, it is power or cable - not
   filesystem. Re-seat power, then USB. Try a different port and a different cable before
   suspecting the disk.
2. **Is the block device there?** `lsblk`. Bridge present but no disk means the enclosure is not
   passing the drive through - check the disk is seated.
3. **Is the UUID there?** `ls -l /dev/disk/by-uuid/f2276a43-...`. Device present but no UUID means
   the partition table or superblock is unreadable. **Stop and do not write anything.**
4. **Only then** consider `sudo e2fsck -f /dev/disk/by-uuid/f2276a43-...` - by UUID, never by device
   letter, and only with the filesystem unmounted. Run it twice; the second pass must be clean with
   exit 0.

Once mounted, do not skip step 2 above. Mounting is not the same as mounting *the right thing*.

---

## Install the remaining drop-ins

Not yet installed as of 2026-08-30. Do this before the swap, not after:

```bash
sudo install -Dm644 /home/cody/avrana/deploy/storage/dropins/sabnzbd-require-array.conf \
  /etc/systemd/system/sabnzbd.service.d/require-array.conf
sudo install -Dm644 /home/cody/avrana/deploy/storage/dropins/mylar3-require-array.conf \
  /etc/systemd/system/mylar3.service.d/require-array.conf
sudo systemctl daemon-reload
for u in docker sabnzbd mylar3; do
  printf '%-10s %s\n' "$u" "$(systemctl show $u.service -p RequiresMountsFor --value)"
done
```

All three must print `/mnt/avrana_media`.

---

## Deferred - evaluate during the maintenance window, NOT before

### `chattr +i` on the mountpoint (defense in depth)

An immutable, empty `/mnt/avrana_media` cannot be written into when nothing is mounted on it. That
blocks the entire fault class at the filesystem layer, underneath systemd - if a dependency is ever
mis-edited or a service is started by hand, the write still fails. Once the array is mounted over
it, the flag is invisible and has no effect on the array's own contents.

**It must only be applied while the array is unmounted.** Applying it to a mounted `/mnt/avrana_media`
sets the flag on the *array's own root inode* instead, making the live array's top level immutable -
the opposite of what is wanted.

The swap already includes an unmounted window, which is the natural place to evaluate it:

```bash
# ONLY with the array unmounted - verify first:
findmnt /mnt/avrana_media && echo "STOP: still mounted" || sudo chattr +i /mnt/avrana_media
lsattr -d /mnt/avrana_media        # expect ----i---------
```

To reverse: `sudo chattr -i /mnt/avrana_media` (also only while unmounted).

Open question to settle before adopting: whether any legitimate tooling needs to create new
top-level directories on the array, since the flag has no effect once mounted but would block
recreating the mountpoint itself if it were ever removed.

### JMS578 / UAS quirk

The **old** adapter is a JMicron JMS578 bound to the `uas` driver, and
`Synchronize Cache(10) failed: hostbyte=DID_ERROR` followed by re-enumeration is that chipset's
classic drop-under-load signature. The mitigation is a kernel parameter forcing the slower, stabler
`usb-storage` driver:

```
usb-storage.quirks=152d:0578:u
```

**Deliberately not applied.** The new enclosure very likely uses a different bridge chip, which
would make this quirk both unnecessary and wrong - `152d:0578` is the JMS578's specific USB ID.
After the swap, record what the new bridge actually is:

```bash
lsusb | grep -i -v 'root hub'
ls -l /sys/block/sd*/device/../../../driver     # uas or usb-storage?
```

Only if the new enclosure also binds `uas` **and** shows the same symptom is the quirk worth
revisiting, with its own vendor:product ID. Cable and power were never excluded as causes of the
original disconnect.
