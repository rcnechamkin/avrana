#!/usr/bin/env bash
# Prove that the off-host secrets stored in 1Password are the ones that unlock the data in B2.
#
# Run as cody in a terminal on avrana, with the 1Password entry open:
#
#     bash /home/cody/avrana/services/backups/offhost-verify-secrets.sh
#
# It asks for the bucket name, the B2 keyID and applicationKey, and the rclone crypt password and
# salt, all at hidden prompts, exactly as offhost-setup.sh does. It builds a throwaway rclone
# configuration from those values in a private temporary directory, lists the newest remote run
# through it, and reports whether the run's file names decrypt and its completion marker is
# visible. Wrong B2 keys cannot list the bucket; a wrong crypt password or salt cannot decrypt a
# single name. The production rclone.conf is not read, written or compared. Nothing is uploaded or
# downloaded except directory listings. The temporary configuration is shredded on exit.
set -euo pipefail
umask 077

IMAGE="rclone/rclone@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548"
[[ -t 0 ]] || { echo "Run this in an interactive terminal."; exit 1; }
[[ "$(id -un)" == cody ]] || { echo "Run as cody (no sudo)."; exit 1; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "The pinned rclone image is not present locally."; exit 1; }

WORK="$(mktemp -d /dev/shm/offhost-verify.XXXXXX 2>/dev/null || mktemp -d)"
chmod 700 "$WORK"
cleanup() { [[ -f "$WORK/rclone.conf" ]] && shred -u "$WORK/rclone.conf" 2>/dev/null; rm -rf "$WORK"; }
trap cleanup EXIT

read -rp  "B2 bucket name: " BUCKET
[[ "$BUCKET" =~ ^[A-Za-z0-9-]{6,63}$ ]] || { echo "That does not look like a B2 bucket name."; exit 1; }
read -rsp "B2 keyID (input hidden): " KEY_ID; echo
read -rsp "B2 applicationKey (input hidden): " APP_KEY; echo
read -rsp "rclone crypt password (input hidden): " CRYPT_PW; echo
read -rsp "rclone crypt salt (input hidden): " CRYPT_SALT; echo
[[ -n "$KEY_ID" && -n "$APP_KEY" && -n "$CRYPT_PW" && -n "$CRYPT_SALT" ]] || { echo "A value was empty."; exit 1; }

obscure() { printf '%s' "$1" | docker run --rm -i --pull never "$IMAGE" obscure -; }
OBSCURED_PW="$(obscure "$CRYPT_PW")"
OBSCURED_SALT="$(obscure "$CRYPT_SALT")"
unset CRYPT_PW CRYPT_SALT
{
  printf '[b2]\ntype = b2\naccount = %s\nkey = %s\nhard_delete = false\n\n' "$KEY_ID" "$APP_KEY"
  printf '[daily]\ntype = crypt\nremote = b2:%s/daily\nfilename_encryption = standard\n' "$BUCKET"
  printf 'directory_name_encryption = true\npassword = %s\npassword2 = %s\n' "$OBSCURED_PW" "$OBSCURED_SALT"
} > "$WORK/rclone.conf"
unset KEY_ID APP_KEY OBSCURED_PW OBSCURED_SALT
chmod 600 "$WORK/rclone.conf"

run() { docker run --rm --pull never --user "$(id -u):$(id -g)" -e XDG_CACHE_HOME=/tmp \
          -e RCLONE_CONFIG=/config/rclone.conf -v "$WORK/rclone.conf:/config/rclone.conf:ro" "$IMAGE" "$@"; }

echo; echo "1/3  B2 keys: listing the bucket"
if ! run lsf --max-depth 1 "b2:$BUCKET" >"$WORK/raw.txt" 2>"$WORK/err.txt"; then
  echo "     FAIL: the bucket cannot be listed with these keys:"; tail -2 "$WORK/err.txt" | sed 's/^/       /'; exit 1
fi
grep -qx 'daily/' "$WORK/raw.txt" || { echo "     FAIL: the bucket has no daily/ prefix; is this the right bucket?"; exit 1; }
echo "     ok"

echo "2/3  crypt password and salt: decrypting the run names"
if ! run lsf --dirs-only daily: >"$WORK/runs.txt" 2>"$WORK/err.txt"; then
  echo "     FAIL:"; tail -2 "$WORK/err.txt" | sed 's/^/       /'; exit 1
fi
newest="$(grep -E '^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}Z/$' "$WORK/runs.txt" | sort | tail -1 | tr -d /)"
[[ -n "$newest" ]] || { echo "     FAIL: no run name decrypts. The crypt password or salt is wrong."; exit 1; }
echo "     ok: newest remote run $newest"

echo "3/3  completion marker visible through these values"
if run lsf --files-only "daily:$newest/" 2>/dev/null | grep -qx 'OFFHOST-COMPLETE.json'; then
  echo "     ok"
else
  echo "     FAIL: $newest lists, but its completion marker is not visible."; exit 1
fi
echo; echo "VERIFIED: the values you entered unlock the off-host data. Nothing on the host was changed."
