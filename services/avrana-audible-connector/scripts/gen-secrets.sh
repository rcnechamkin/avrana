#!/usr/bin/env bash
# Generate the connector's secret files (idempotent: won't overwrite existing ones).
# Run once before first `docker compose up`.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$here/secrets" "$here/data" "$here/profiles"

gen() {  # gen <file> <bytes>
  local f="$here/secrets/$1"
  if [[ -s "$f" ]]; then echo "keep  $1 (exists)"; return; fi
  head -c "$2" /dev/urandom | base64 | tr -d '\n=+/' > "$f"
  chmod 600 "$f"
  echo "write $1"
}

gen companion_token 48
gen session_key 48

# OIDC client secret is provided by Authentik when the provider is created; paste it in.
if [[ ! -s "$here/secrets/oidc_client_secret" ]]; then
  : > "$here/secrets/oidc_client_secret"
  chmod 600 "$here/secrets/oidc_client_secret"
  echo "write oidc_client_secret (EMPTY — paste the Authentik client secret here)"
fi
echo "Done. Secrets in $here/secrets (chmod 600)."
