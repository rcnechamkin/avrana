# Host configuration

Representations of configuration that lives outside `/home/cody/avrana`. Nothing here is installed
automatically; `BOOTSTRAP.md` says what to do with each file.

| File | Live location | Kind |
|---|---|---|
| `fstab` | `/etc/fstab` | Copy. Only the `/mnt/avrana_media` and `comics_merged` lines are reusable. |
| `daemon.json` | `/etc/docker/daemon.json` | Reconstruction. The live file is root-only; its single setting was read from `docker info`. |
| `netplan-br0.example.yaml` | `/etc/netplan/50-cloud-init.yaml` | Reconstruction from `networkctl`. |
| `sshd_config.d/00-avrana-pubkey-only.conf` | `/etc/ssh/sshd_config.d/` | Copy. |
| `systemd/sabnzbd.service`, `systemd/mylar3.service` | `/etc/systemd/system/` | Copy. Their `require-array` drop-ins are in `deploy/storage/dropins/`; Docker's is `deploy/docker/docker-require-array.conf`. |
| `apt/50unattended-upgrades`, `apt/20auto-upgrades` | `/etc/apt/apt.conf.d/` | Copy. |
| `cloudflared/config.yml` | `/home/cody/.cloudflared/config.yml` | Copy. The tunnel credential file it names is a secret and is not here. |
| `packages-manual.txt` | output of `apt-mark showmanual` | List. Includes packages that are scheduled for retirement. |

`scripts/drift-check.py` compares the copies with the live files.
