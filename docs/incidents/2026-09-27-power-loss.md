# 2026-09-27 and 2026-09-28: six unclean power-offs

| Boot ended (PDT) | Next boot | Gap |
|---|---|---|
| Sep 27 12:12:03 | 12:13:48 | 1m45 |
| Sep 27 12:17:25 | 12:26:37 | 9m12 |
| Sep 28 17:19:02 | 17:20:25 | 1m23 |
| Sep 28 17:22:07 | 17:33:01 | 10m54 |
| Sep 28 17:37:00 | 17:39:09 | 2m09 |
| Sep 28 17:42:14 | 17:43:28 | 1m14 |

**Cause: the electrical breaker tripped** (owner, 2026-10-03). Every journal ends mid-activity with no
shutdown sequence, and no kernel, thermal, memory or disk fault precedes any of them. The events are not
related to the recovery work that was going on that week.

**Damage: none found.** Checked on 2026-10-03: 18 of 18 SQLite databases in that night's backup pass
`integrity_check`, the Authentik, BookStack and Tracearr dumps are complete, all archives pass
`zstd -t`, the manifest verifies, no container logged corruption, and Postgres performed normal crash
recovery. The SSD's SMART data counts 86 unexpected power losses over its life.

**Side effects.** The first reboot activated a pending kernel and was when the 20 GiB LVM recovery
snapshot was found full and invalid; the owner archived and removed it. Each cold boot left the two
health units failed against each other until that deadlock was fixed on 2026-10-03.

**Open.** There is no UPS. The array is a USB enclosure and Docker's data-root is on it, so an abrupt
power loss during a write remains a risk to the container store.
