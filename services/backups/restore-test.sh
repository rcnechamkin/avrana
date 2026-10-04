#!/usr/bin/env bash
# Prove an Avrana backup is actually restorable — a backup you have never restored is a
# hypothesis, not a backup. This boots a THROWAWAY Audiobookshelf from the restored database
# and metadata in a temp location (its own port, its own container, the real library mounted
# read-only) and asserts it comes up initialised with the library and users intact. It never
# touches the live ABS container, config, port, or database.
#
# Usage: restore-test.sh [BACKUP_DIR]   (defaults to the newest backup)
set -uo pipefail

DEST_ROOT="${AVRANA_BACKUP_ROOT:-/mnt/avrana_media/.backups/avrana}"
BACKUP="${1:-$(ls -1d "$DEST_ROOT"/*/ 2>/dev/null | grep -vi partial | sort | tail -1)}"
IMAGE="ghcr.io/advplyr/audiobookshelf@sha256:180acad33d69c99ed208676465d8edcb268fa46967735579a7810859885b1a8e"
NAME="abs-restore-test"
PORT="18378"
WORK="$(mktemp -d /tmp/abs-restore-test.XXXXXX)"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

pass() { echo "PASS  $*"; }
die()  { echo "FAIL  $*"; exit 1; }

[[ -n "$BACKUP" && -d "$BACKUP" ]] || die "no backup dir (looked in $DEST_ROOT)"
echo "restore-test: $BACKUP"

# 1. Verify the manifest checksums before trusting the bytes.
if [[ -f "$BACKUP/MANIFEST.txt" ]]; then
  ( cd "$BACKUP" && sha256sum -c --quiet MANIFEST.txt ) || die "manifest checksum mismatch"
  pass "manifest checksums verified"
fi

# 2. Reconstruct a config + metadata dir from the backup, exactly as a real recovery would.
mkdir -p "$WORK/config" "$WORK/metadata"
cp "$BACKUP/audiobookshelf/absdatabase.sqlite" "$WORK/config/absdatabase.sqlite" || die "restore DB copy"
zstd -dc "$BACKUP/audiobookshelf/metadata.tar.zst" 2>/dev/null | tar -C "$WORK/metadata" -xf - || die "restore metadata"
chmod -R u+rwX "$WORK"
pass "restored config + metadata from backup"

# 3. Assert the restored DB itself is sane before booting anything.
read -r items users < <(python3 - "$WORK/config/absdatabase.sqlite" <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
print(c.execute("SELECT count(*) FROM libraryItems").fetchone()[0],
      c.execute("SELECT count(*) FROM users").fetchone()[0])
PY
)
(( items > 0 )) || die "restored DB has no library items"
(( users > 0 )) || die "restored DB has no users"
pass "restored DB has $items library items and $users users"

# 4. Boot a throwaway ABS on the restored data — the real proof it will actually start.
docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" --user "1000:1000" \
  -e TZ=America/Los_Angeles \
  -v "$WORK/config:/config" -v "$WORK/metadata:/metadata" \
  -v /mnt/avrana_media/audiobooks:/audiobooks:ro \
  -p "127.0.0.1:$PORT:80" "$IMAGE" >/dev/null || die "could not start throwaway ABS"

# 5. Wait for health, then confirm it initialised from the restored DB (isInit=true means it
#    loaded a server DB that already has a root user — i.e. the restore, not a fresh install).
ok=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/healthcheck" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
(( ok )) || { docker logs "$NAME" 2>&1 | tail -20; die "throwaway ABS never became healthy"; }
pass "throwaway ABS booted and is healthy"

status="$(curl -fsS "http://127.0.0.1:$PORT/status" 2>/dev/null)"
echo "$status" | grep -q '"isInit":true' || die "server did not initialise from the restored DB ($status)"
pass "server reports isInit=true — restored users/library are live"

# 6. Radarr / Sonarr / Prowlarr. Restored into the throwaway work dir only — the live services
# are never stopped, never written to, and never pointed at these copies. Booting a throwaway
# *arr is not worth it (each would need its own port and would try to reach indexers), so the
# proof here is: the SQLite survives a full integrity check, the tables a restore actually needs
# are populated, and config.xml is well-formed XML carrying the fields the service needs to start.
for svc in radarr sonarr prowlarr; do
  sdir="$BACKUP/arr/$svc"
  [[ -d "$sdir" ]] || die "$svc missing from backup (expected $sdir)"
  mkdir -p "$WORK/arr/$svc"
  cp "$sdir/$svc.db" "$WORK/arr/$svc/$svc.db" || die "$svc: restore db copy"
  cp "$sdir/config.xml" "$WORK/arr/$svc/config.xml" || die "$svc: restore config.xml"

  # integrity_check is the real test of a SQLite copy; a truncated or torn file fails here.
  summary="$(python3 - "$WORK/arr/$svc/$svc.db" "$svc" <<'PY'
import sqlite3, sys
db, svc = sys.argv[1], sys.argv[2]
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
res = c.execute("PRAGMA integrity_check").fetchone()[0]
if res != "ok":
    print(f"INTEGRITY_FAIL {res}"); raise SystemExit(1)
have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
# Tables whose absence would mean the restore is useless for that service.
need = {"radarr":   ["QualityProfiles", "CustomFormats", "Movies"],
        "sonarr":   ["QualityProfiles", "Series"],
        "prowlarr": ["Indexers"]}[svc]
missing = [t for t in need if t not in have]
if missing:
    print(f"TABLES_MISSING {','.join(missing)}"); raise SystemExit(1)
counts = ", ".join(f"{t}={c.execute(f'SELECT count(*) FROM {t}').fetchone()[0]}" for t in need)
print(f"OK {counts}")
PY
)" || die "$svc: $summary"
  pass "$svc db integrity ok (${summary#OK })"

  # config.xml holds the API key and bind settings and cannot be rebuilt from the DB. Validate it
  # parses and carries the required elements. Values are never printed -- ApiKey is a secret.
  python3 - "$WORK/arr/$svc/config.xml" <<'PY' || die "$svc: config.xml invalid"
import sys, xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
missing = [t for t in ("ApiKey", "Port", "UrlBase", "AuthenticationMethod")
           if root.find(t) is None]
# UrlBase is legitimately empty on a default install; only its absence is a problem.
if missing:
    print("missing elements:", ",".join(missing), file=sys.stderr); raise SystemExit(1)
key = (root.findtext("ApiKey") or "").strip()
if len(key) < 16:
    print("ApiKey missing or implausibly short", file=sys.stderr); raise SystemExit(1)
PY
  pass "$svc config.xml well-formed, required elements present (values not printed)"
done

# 7. Home Assistant (Kern HQ). Not booted: HA would try to reach the real ESPHome devices and
# Alexa cloud on startup. The proof that matters is that the archive contains the files that
# CANNOT be regenerated -- the auth store and the ESPHome pairing keys -- because a host-side
# tar as `cody` silently omits exactly those (root-owned 0600) while still producing a
# plausible archive. That failure mode is the reason this check exists.
hadir="$BACKUP/home-assistant"
[[ -d "$hadir" ]] || die "home-assistant missing from backup (expected $hadir)"
entries="$(zstd -dc "$hadir/ha-config.tar.zst" 2>/dev/null | tar -tf - 2>/dev/null)" \
  || die "home-assistant: config archive unreadable"
for f in config/.storage/auth config/.storage/core.config config/.storage/core.entity_registry \
         config/.storage/esphome.encryption_keys config/configuration.yaml; do
  grep -qxF "$f" <<<"$entries" || die "home-assistant: $f absent from the archive"
done
pass "home-assistant archive carries auth store, registries and ESPHome keys ($(wc -l <<<"$entries") entries)"

# The recorder is SQLite in WAL mode; integrity_check is the real test of the online copy.
recsum="$(python3 - "$hadir/home-assistant_v2.db" <<'PYEOF'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
    print("INTEGRITY_FAIL"); raise SystemExit(1)
have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
missing = [t for t in ("states", "events", "statistics") if t not in have]
if missing:
    print("TABLES_MISSING " + ",".join(missing)); raise SystemExit(1)
print("OK states=%d" % c.execute("SELECT count(*) FROM states").fetchone()[0])
PYEOF
)" || die "home-assistant recorder: $recsum"
pass "home-assistant recorder integrity ok (${recsum#OK })"

# 8. Tracearr. Postgres runs inside the app container, so the artifact is a plain-text pg_dump.
# Not restored into a throwaway postgres for the same reason the *arr are not booted: it would
# need its own container and port for no additional confidence. Validate the dump structurally.
trdir="$BACKUP/tracearr"
[[ -d "$trdir" ]] || die "tracearr missing from backup (expected $trdir)"
dump="$(zstd -dc "$trdir/tracearr.pgdump.zst" 2>/dev/null)" || die "tracearr: dump unreadable"
grep -q "^-- PostgreSQL database dump" <<<"$dump" || die "tracearr: not a pg_dump"
grep -q "^-- PostgreSQL database dump complete" <<<"$dump" \
  || die "tracearr: dump is TRUNCATED (no completion marker)"
for t in libraries users; do
  grep -qE "^CREATE TABLE public\.$t " <<<"$dump" || die "tracearr: table $t missing from dump"
done
pass "tracearr pg_dump complete and well-formed ($(grep -c '^CREATE TABLE' <<<"$dump") tables)"

# 9. The systemd layer. Containers are only half a rebuild: SABnzbd, mylar3, the health API and
# the tunnels are units, and the mergerfs union Komga depends on is an fstab line.
sysdir="$BACKUP/systemd"
[[ -d "$sysdir" ]] || die "systemd missing from backup (expected $sysdir)"
for u in system/sabnzbd.service system/mylar3.service user/health_api.service; do
  [[ -s "$sysdir/$u" ]] || die "systemd: $u missing from backup"
done
grep -q mergerfs "$sysdir/fstab" 2>/dev/null || die "systemd: fstab missing the mergerfs union"
pass "systemd layer captured ($(ls "$sysdir/system" | wc -l) system + $(ls "$sysdir/user" | wc -l) user units, fstab, enablement state)"

echo "RESTORE TEST PASSED — $BACKUP is recoverable."
