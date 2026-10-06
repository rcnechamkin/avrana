#!/usr/bin/env bash
# Restore the Mylar3 login (bug hunt A5). Run as root on avrana:
#
#     sudo bash /home/cody/avrana/deploy/host/owner-scripts/01-mylar3-login.sh
#
# Mylar rewrites config.ini when it stops, so the order is: stop, edit, start. You choose a new
# password at a hidden prompt; it is written only into config.ini (mode 600, owned by cody),
# which Mylar stores in plain text. Put it in 1Password. Nothing is printed or logged.
# Rollback: the saved config.ini in the batch directory, then `systemctl restart mylar3`.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
[[ -t 0 ]] || { echo "run in an interactive terminal"; exit 1; }
CONF=/home/cody/avrana/services/mylar3/config.ini
B=/mnt/avrana_media/.backups/batch3-20261006/rollback/mylar3
mkdir -p "$B" && chmod 700 "$B"
SAVED="$B/config.ini.$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$CONF" "$SAVED"

read -rsp "New Mylar3 password for user $(sed -n 's/^http_username = //p' "$CONF") (hidden): " PW; echo
read -rsp "Again: " PW2; echo
[[ -n "$PW" && "$PW" == "$PW2" ]] || { echo "empty or mismatched; nothing changed"; exit 1; }
[[ "$PW" != *$'\n'* ]] || { echo "newline in password; nothing changed"; exit 1; }

systemctl stop mylar3
export PW
python3 - "$CONF" <<'PY'
import os, pathlib, re, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text()
t, n1 = re.subn(r"(?m)^authentication = .*$", "authentication = 2", t)
t, n2 = re.subn(r"(?m)^http_password = .*$", "http_password = " + os.environ["PW"], t)
assert n1 == 1 and n2 == 1, (n1, n2)
p.write_text(t)
PY
unset PW PW2
chmod 600 "$CONF"; chown cody:cody "$CONF"
systemctl start mylar3
for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8090/home || true)
  [[ "$code" == 303 ]] && break; sleep 2
done
if [[ "$code" == 303 ]]; then
  echo "Mylar3 now redirects /home to its login (303). Store the password in 1Password."
  echo "The baseline check expects 303 from now on (authentication = 2)."
else
  echo "Mylar3 answered $code, not 303. Restoring the previous config and restarting."
  systemctl stop mylar3; cp -p "$SAVED" "$CONF"; systemctl start mylar3; exit 1
fi
