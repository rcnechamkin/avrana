# Avrana custom CWA image = upstream v4.0.8 + a tiny build-time patch that makes Kindle
# personal-document titles clean (MIME attachment filename = "{title}.epub", no author).
#
# Update-safe by construction: the patch (avrana-patch/apply_avrana_patches.py) replaces exact
# code fragments and asserts each matched once, so a version bump that changes those fragments
# fails THIS BUILD rather than silently regressing. Upgrade procedure in avrana-patch/README.md.
#
# Pinned, by digest, to the same version the compose file deploys. Bump both together, on purpose.
# v4.0.7 carries the access-control fixes; docs/runbooks/rc3-upstream-upgrades.md. The build arg is only for
# .github/workflows/rc3-upstream-proof.yml, which builds the previous version as the before-the-fix control.
ARG CWA_BASE_IMAGE=crocodilestick/calibre-web-automated:v4.0.8@sha256:5e00373854247750cc3e4479b492ae09293ff5e06ed10177f226634d97888679
FROM ${CWA_BASE_IMAGE}

# python3 is guaranteed present (CWA is a Python app); no extra packages, no `patch`/`git`.
COPY avrana-patch/apply_avrana_patches.py /tmp/avrana/apply_avrana_patches.py
RUN python3 /tmp/avrana/apply_avrana_patches.py \
 && python3 -m py_compile \
      /app/calibre-web-automated/cps/tasks/mail.py \
      /app/calibre-web-automated/cps/helper.py \
      /app/calibre-web-automated/cps/tasks/convert.py \
      /app/calibre-web-automated/cps/usermanagement.py \
      /app/calibre-web-automated/scripts/cwa_db.py \
      /app/calibre-web-automated/scripts/kindle_epub_fixer.py \
 && rm -rf /tmp/avrana
