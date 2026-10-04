# Complete Series: 8085 (LAN)

> Promoted from the BookStack wiki on 2026-10-04 (page 20, "Complete Series", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Original: [archive](../../docs/archive/bookstack/raw/services/20-complete-series.md).

Stateless tool that scans Audiobookshelf for **incomplete series + missing books**. Container `completeseries`.
- Login needs the ABS `allowedOrigins` CORS fix (add `http://10.0.0.218:8085`): otherwise it looks like bad creds. See the ABS page.
- Open decision: keep it deployed? (It was removed from Homepage but still runs.)
