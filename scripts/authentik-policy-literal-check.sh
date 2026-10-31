#!/usr/bin/env bash
# AVR-791: is any key-like literal stored in an Authentik expression? Read-only. Prints name, length and counts, NEVER
# the text, so the output is safe to paste into a report. Exit 1 if any count is not 0.
#
# Usage: scripts/authentik-policy-literal-check.sh [postgres container, default authentik-postgresql]
# Columns: name, chars, hex runs of 32 or more, credential-named fields assigned a quoted literal of 12 or more
# characters, reads a key file (t/f). Also run in CI by tests/authentik_enrollment_live.sh, against a throwaway database.
# Runbook: docs/runbooks/rc3-policy-secret-rotation.md.
set -euo pipefail

container=${1:-authentik-postgresql}
rows=$(docker exec -i "$container" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At -F " "' <<'QUERY'
SELECT name, length(expression),
       (SELECT count(*) FROM regexp_matches(expression, '[0-9a-fA-F]{32,}', 'g')),
       (SELECT count(*) FROM regexp_matches(expression,
          '(token|api[-_]?key|authorization|password|secret)["'']?\s*[:=]\s*["''][^"''[:space:]]{12,}["'']', 'gi')),
       position('/run/avrana-policy-secrets/' IN expression) > 0
FROM (SELECT p.name, e.expression
        FROM authentik_policies_expression_expressionpolicy e
        JOIN authentik_policies_policy p ON p.policy_uuid = e.policy_ptr_id
      UNION ALL
      SELECT name, expression FROM authentik_core_propertymapping) AS expressions
ORDER BY 1;
QUERY
)
echo "$rows" | grep '^avrana-' || true
total=$(echo "$rows" | grep -c . || true)
bad=$(echo "$rows" | awk 'NF && ($(NF-2) != 0 || $(NF-1) != 0)' | wc -l)
echo "expressions checked: $total, with a key-like literal: $bad"
[ "$total" -gt 0 ] && [ "$bad" = 0 ]
