# Avrana custom CWA image = upstream v4.0.6 + a tiny build-time patch that makes Kindle
# personal-document titles clean (MIME attachment filename = "{title}.epub", no author).
#
# Update-safe by construction: the patch (avrana-patch/apply_avrana_patches.py) replaces exact
# code fragments and asserts each matched once, so a version bump that changes those fragments
# fails THIS BUILD rather than silently regressing. Upgrade procedure in avrana-patch/README.md.
#
# Pinned to the same version the compose file deploys. Bump both together, on purpose.
FROM crocodilestick/calibre-web-automated:v4.0.6

# python3 is guaranteed present (CWA is a Python app); no extra packages, no `patch`/`git`.
COPY avrana-patch/apply_avrana_patches.py /tmp/avrana/apply_avrana_patches.py
RUN python3 /tmp/avrana/apply_avrana_patches.py \
 && python3 -m py_compile \
      /app/calibre-web-automated/cps/tasks/mail.py \
      /app/calibre-web-automated/cps/helper.py \
      /app/calibre-web-automated/cps/tasks/convert.py \
      /app/calibre-web-automated/cps/usermanagement.py \
      /app/calibre-web-automated/scripts/cwa_db.py \
 && rm -rf /tmp/avrana
