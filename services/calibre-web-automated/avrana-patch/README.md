# Avrana CWA patch — clean Kindle titles

Custom Calibre-Web-Automated image = upstream `crocodilestick/calibre-web-automated:v4.0.8`
plus one small build-time patch.

## What it fixes

Amazon derives a **personal document's displayed title from the attachment filename** of the
email it receives. Stock Calibre-Web sends the book under its on-disk name — Calibre's
`"<title> - <author>.epub"` — so a book lands on the Kindle titled *"Cibola Burn - James S. A.
Corey"*. This patch makes the sender pass a clean **`"<title>.epub"`** (no author) as the MIME
attachment name, while:

- the **physical file read from disk** and the **canonical Calibre library file are untouched**,
- the EPUB's **embedded** title / author / cover metadata is unchanged,
- the change applies to **manual**, **auto**, and **converted-file** sends.

The clean name is produced by CWA's own `get_valid_filename(title)` (with
`config_unicode_filename=0` it **preserves Unicode** and only strips filesystem-unsafe
characters), then `+ ".<ext>"`.

## How it's applied

`avrana-patch/apply_avrana_patches.py` runs at image build (see `../Dockerfile`). It does exact
string replacements against three files and **asserts each fragment matches exactly once**:

| File | Change |
|---|---|
| `cps/tasks/mail.py` | `TaskEmail` gains `attachment_name`; MIME filename + mimetype guess use it, `attachment` still names the file to READ. |
| `cps/helper.py` | `send_mail()` computes `get_valid_filename(title)+ext` and passes it as `attachment_name`. |
| `cps/tasks/convert.py` | post-conversion send does the same for the converted file. |
| `cps/usermanagement.py` | `verify_password()` (OPDS/API Basic auth): in LDAP login mode, fall back to the LOCAL password for existing local accounts. Upstream only tries an LDAP bind, so local service accounts not in the directory (the read-only Homepage dashboard user, break-glass admin) get a 401. Guarded by a non-empty local hash, so LDAP-managed users can't bypass LDAP. |

> The `usermanagement.py` fix is unrelated to Kindle titles — it repairs the Homepage
> Calibre-Web widget (and any local-account OPDS/API access) that broke when LDAP login mode was
> enabled. Kept in this same patch layer since it's the same custom image.

If a fragment isn't found (or matches more than once), the **build fails** — the deliberate
signal that upstream changed.

## Upgrade procedure (bumping CWA)

1. Change the tag and digest in **both** `Dockerfile` (`CWA_BASE_IMAGE`) and `docker-compose.yml`
   (`image:` comment / build context) to the new version.
2. `docker compose build calibre-web-automated`.
3. If the build **fails** at `apply_avrana_patches.py`, the upstream source moved. Pull the new
   `cps/tasks/mail.py`, `cps/helper.py`, `cps/tasks/convert.py`, update the `old`/`new`
   fragments in `apply_avrana_patches.py` to match, and rebuild. (Check upstream first — if CWA
   ever adds a native outgoing-filename template, drop this patch and use that instead.)
4. `docker compose up -d calibre-web-automated`, then re-run the tests in `../tests/`.

## Idempotency

The applier is idempotent: if a fragment is already patched it skips it, so a rebuild on the
same base is safe.
