# Incidents

| Date | What happened | Record |
|---|---|---|
| 2026-08-29 | A Docker address-pool change took the whole fleet down; rollback was incomplete; relapse after reboot. | [2026-08-29-docker-address-pools.md](2026-08-29-docker-address-pools.md) |
| 2026-08-30 | The USB array dropped; Docker started on an empty data-root; Komga served an empty library for days. | [2026-08-30-array-disconnect.md](2026-08-30-array-disconnect.md) |
| 2026-09-20 | Most of `/home/cody` was deleted by an agent session; recovery from the nightly backup and an LVM snapshot. | [2026-09-20-home-directory-deletion.md](2026-09-20-home-directory-deletion.md), [recovery record](../findings/2026-09-20-recovery.md), [follow-up](../findings/2026-09-27-recovery-followup.md) |
| 2026-09-27/28 | Six unclean power-offs in two clusters; no damage found. | [2026-09-27-power-loss.md](2026-09-27-power-loss.md) |

Audits written after the August incidents are in [`../audits/`](../audits/). The October 2026 assessment,
bug hunt and remediation ledgers are kept by the owner outside this repository.
