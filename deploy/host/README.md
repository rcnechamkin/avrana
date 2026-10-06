# Host configuration

Representations of configuration that lives outside `/home/cody/avrana`. Nothing here is installed
automatically; `BOOTSTRAP.md` says what to do with each file.

| File | Live location | Kind |
|---|---|---|
| `owner-scripts/` | run with `sudo` | The root-only changes staged by Batch 3, each with rollback; see its README. |
| `avrana-ro` | `/usr/local/bin/avrana-ro` | Read-only wrapper for the `avrana-agent` account (installed by owner script 06). |
| `fstab` | `/etc/fstab` | Copy. Only the `/mnt/avrana_media` and `comics_merged` lines are reusable. |
| `daemon.json` | `/etc/docker/daemon.json` | Reconstruction. The live file is root-only; its single setting was read from `docker info`. |
| `netplan-br0.example.yaml` | `/etc/netplan/50-cloud-init.yaml` | Reconstruction from `networkctl`. |
| `sshd_config.d/00-avrana-pubkey-only.conf` | `/etc/ssh/sshd_config.d/` | Copy. |
| `backup-seal.sh`, `systemd/avrana-backup-seal.{service,path,timer}` | `/usr/local/sbin/avrana-backup-seal`, `/etc/systemd/system/` | Owner script 08 installs and enables them (bug hunt E5): completed backup runs become root-owned, retention moves to root. |
| `systemd/sabnzbd.service`, `systemd/mylar3.service` | `/etc/systemd/system/` | Copy. Their `require-array` drop-ins are in `deploy/storage/dropins/`; Docker's is `deploy/docker/docker-require-array.conf`. |
| `apt/50unattended-upgrades`, `apt/20auto-upgrades` | `/etc/apt/apt.conf.d/` | Copy. |
| `cloudflared/config.yml` | `/home/cody/.cloudflared/config.yml` | Copy. The tunnel credential file it names is a secret and is not here. |
| `packages-manual.txt` | output of `apt-mark showmanual` | List. Includes packages that are scheduled for retirement. |

`scripts/drift-check.py` compares the copies with the live files.
