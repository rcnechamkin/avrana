#!/usr/bin/env bash
# One-time, interactive setup of the encrypted off-host backup destination (Backblaze B2).
#
# Run as cody in a terminal on avrana:
#
#     bash /home/cody/avrana/services/backups/offhost-setup.sh
#
# Have these open in 1Password first:
#   - B2 bucket name                    (not secret)
#   - B2 keyID and applicationKey       (bucket-scoped application key)
#   - rclone crypt password and salt
#
# Every secret is read at a hidden prompt. Nothing is echoed, exported, placed on a command
# line, logged or written to shell history. The two crypt values are obscured by rclone itself,
# reading them from a pipe. The result is services/backups/rclone.conf, mode 0600, which Git
# ignores. Running the script again replaces that file after saving the old one beside it.
#
# It then checks that the bucket is reachable and that both encrypted tiers can be listed.
# It uploads nothing.
set -euo pipefail
umask 077

REPO="${AVRANA_REPO:-/home/cody/avrana}"
CONF="${AVRANA_RCLONE_CONF:-$REPO/services/backups/rclone.conf}"
IMAGE="rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548"

[[ -t 0 ]] || { echo "Run this in an interactive terminal."; exit 1; }
[[ "$(id -un)" == cody ]] || { echo "Run as cody (no sudo)."; exit 1; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "The pinned rclone image is not present locally."; exit 1; }

read -rp  "B2 bucket name: " BUCKET
[[ "$BUCKET" =~ ^[A-Za-z0-9-]{6,63}$ ]] || { echo "That does not look like a B2 bucket name. Nothing changed."; exit 1; }
read -rsp "B2 keyID (input hidden): " KEY_ID; echo
read -rsp "B2 applicationKey (input hidden): " APP_KEY; echo
read -rsp "rclone crypt password (input hidden): " CRYPT_PW; echo
read -rsp "rclone crypt password again: " CRYPT_PW2; echo
read -rsp "rclone crypt salt (input hidden): " CRYPT_SALT; echo
read -rsp "rclone crypt salt again: " CRYPT_SALT2; echo

[[ -n "$KEY_ID" && -n "$APP_KEY" && -n "$CRYPT_PW" && -n "$CRYPT_SALT" ]] || { echo "A value was empty. Nothing changed."; exit 1; }
[[ "$CRYPT_PW" == "$CRYPT_PW2" && "$CRYPT_SALT" == "$CRYPT_SALT2" ]] || { echo "The repeated values did not match. Nothing changed."; exit 1; }
[[ "$CRYPT_PW" != "$CRYPT_SALT" ]] || { echo "Password and salt must differ. Nothing changed."; exit 1; }
for value in "$KEY_ID" "$APP_KEY"; do
  [[ "$value" != *$'\n'* && "$value" != *" "* ]] || { echo "A key contains whitespace. Nothing changed."; exit 1; }
done
unset CRYPT_PW2 CRYPT_SALT2

obscure() { printf '%s' "$1" | docker run --rm -i --pull never "$IMAGE" obscure -; }
OBSCURED_PW="$(obscure "$CRYPT_PW")"
OBSCURED_SALT="$(obscure "$CRYPT_SALT")"
unset CRYPT_PW CRYPT_SALT
[[ -n "$OBSCURED_PW" && -n "$OBSCURED_SALT" ]] || { echo "rclone could not obscure the values. Nothing changed."; exit 1; }

if [[ -f "$CONF" ]]; then
  cp -p "$CONF" "$CONF.previous"
  echo "Existing configuration saved as $CONF.previous"
fi
TMP="$CONF.tmp"
{
  printf '# Avrana off-host backup. Created by offhost-setup.sh on %s. Never commit this file.\n' "$(date -u +%F)"
  printf '[avrana-b2]\ntype = b2\naccount = %s\nkey = %s\nhard_delete = false\n\n' "$KEY_ID" "$APP_KEY"
  for tier in daily pinned; do
    printf '[avrana-offsite-%s]\ntype = crypt\nremote = avrana-b2:%s/%s\n' "$tier" "$BUCKET" "$tier"
    printf 'filename_encryption = standard\ndirectory_name_encryption = true\n'
    printf 'password = %s\npassword2 = %s\n\n' "$OBSCURED_PW" "$OBSCURED_SALT"
  done
} > "$TMP"
unset KEY_ID APP_KEY OBSCURED_PW OBSCURED_SALT
chmod 600 "$TMP"
mv "$TMP" "$CONF"
echo "Wrote $CONF (mode $(stat -c %a "$CONF"))."

run() { docker run --rm --pull never --user "$(id -u):$(id -g)" -e XDG_CACHE_HOME=/tmp \
          -e RCLONE_CONFIG=/config/rclone.conf -v "$CONF:/config/rclone.conf:ro" "$IMAGE" "$@"; }

echo; echo "1/2  reaching the bucket"
if run lsf --max-depth 1 "avrana-b2:$BUCKET" >/dev/null 2>"$CONF.err"; then
  echo "     bucket $BUCKET is reachable with this key"
else
  echo "     FAILED to reach the bucket. Reason (no secrets are printed by rclone here):"
  tail -3 "$CONF.err" | sed 's/^/       /'
  rm -f "$CONF.err"
  echo "     The configuration file was written; fix the key or bucket name and run this again."
  exit 1
fi
rm -f "$CONF.err"

echo "2/2  listing both encrypted tiers"
python3 "$REPO/services/backups/offhost-backup.py" --check

echo
echo "Done. Nothing was uploaded. Tell Claude the setup step finished; do not paste any values."
