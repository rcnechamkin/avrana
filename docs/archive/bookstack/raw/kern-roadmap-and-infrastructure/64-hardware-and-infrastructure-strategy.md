---
bookstack_page_id: 64
title: "Hardware and Infrastructure Strategy"
shelf: "Kern"
book: "Kern: Roadmap and Infrastructure"
chapter: ""
created: 2026-08-18 01:48:59
updated: 2026-08-21 00:15:58
last_editor: "Cody"
revisions: 5
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-08-21; exported 2026-10-04. Classified ARCHIVE. Kern project design.

# Hardware and Infrastructure Strategy
# Hardware and Infrastructure Strategy

**Status: current measurements plus agreed policy.**

## No new hardware is required to start

The existing M700 is expected to be sufficient for the early phases of Kern.

Measured on the host, 2026-08-17:

| | |
|---|---|
| CPU | Intel i3-6100T @ 3.20GHz, 4 threads |
| RAM | 31 GB |
| Media array | 7.3 TB total, **5.9 TB available** (15% used) |
| Root filesystem | 57 GB total, 22 GB available |
| Running containers | 28 |

RAM is comfortable. Storage is comfortable. CPU is the constrained resource, and it is not
currently constrained *by Kern*, which does not exist.

Expected to run acceptably on this hardware:

- Home Assistant,
- fast local HA voice workloads such as Speech-to-Phrase and Piper,
- Kern API and services,
- lightweight databases and queues,
- webhooks and event handling,
- cloud-backed LLM calls (network-bound, not CPU-bound).

## Buy in this order

**1. UPS / power protection: first.**
Ahead of any speculative compute upgrade. The host runs 28 containers and several SQLite
databases; an unclean shutdown mid-write is the realistic way to lose data, and no amount of CPU
prevents it. This is the highest-value hardware purchase available today.

**2. Storage resilience: justified by failure tolerance, not capacity.**
With 5.9 TB free, capacity is not the argument. The argument is what happens when a disk fails,
and whether backups are genuinely off-host. Buy resilience when the answer is unacceptable, not
when the disk looks full.

See [Backups & Recovery](http://10.0.0.218:6875/books/infrastructure/page/backups-recovery).

**3. Compute: only on measured contention.**
Upgrade when there is evidence, for example Jellyfin transcoding starving other services, or
local speech processing being unacceptably slow in practice. "Kern exists now" is not evidence.
Measure first, and prefer removing the cause (direct play instead of transcode) over buying
silicon.

**4. Local LLM compute: a separate decision entirely.**
This is accelerator/GPU-shaped, not CPU-shaped.

> **Do not buy an intermediate CPU-only mini-PC merely because Kern exists.** It would not run
> local models usefully and would not fix a bottleneck that has not been demonstrated. If local
> inference is eventually wanted, buy for that workload specifically, once its requirements are
> known.

## Open decisions

- UPS model and runtime target, and which devices it must cover.
- Whether Home Assistant runs on the existing host or its own appliance.
- Off-host backup destination.
- Whether local inference is ever worth it, versus staying cloud-backed with the isolation that
  makes providers replaceable.
