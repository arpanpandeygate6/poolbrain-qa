#!/bin/bash
# Sets up the audit log (Story 5.3): creates the audit table and the
# insert-and-select-only `audit_writer` database user, and adds the n8n
# credential "Audit log (Postgres)" that workflows use to write entries.
# Safe to run again. Needs n8n running (docker compose up -d).
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

[ -f .env ] || { echo "n8n/.env is missing; run ./setup.sh first"; exit 1; }
if ! grep -q '^AUDIT_DB_PASSWORD=' .env; then
  echo "AUDIT_DB_PASSWORD=$(openssl rand -hex 24)" >> .env
  echo "Added AUDIT_DB_PASSWORD to n8n/.env"
fi
set -a; . ./.env; set +a

psql() { docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"; }
psql < audit/schema.sql
psql -c "ALTER ROLE audit_writer PASSWORD '$AUDIT_DB_PASSWORD'"
echo "Audit table and audit_writer user are ready."

# The credential is imported inside the container so the password never appears in a file.
docker compose exec -T -e AUDIT_DB_PASSWORD -e POSTGRES_DB n8n sh -c '
  printf "[{\"id\":\"auditPostgres001\",\"name\":\"Audit log (Postgres)\",\"type\":\"postgres\",\"data\":{\"host\":\"postgres\",\"port\":5432,\"database\":\"%s\",\"user\":\"audit_writer\",\"password\":\"%s\",\"ssl\":\"disable\"}}]" \
    "$POSTGRES_DB" "$AUDIT_DB_PASSWORD" > /tmp/audit-cred.json
  n8n import:credentials --input=/tmp/audit-cred.json; status=$?
  rm -f /tmp/audit-cred.json; exit $status' | tail -1

# Install the shared "Audit: write entry" sub-workflow and publish it, so
# other workflows can call it. Re-importing the same ID updates it in place.
docker compose exec -T n8n sh -c 'cat > /tmp/audit-write-entry.json && n8n import:workflow --input=/tmp/audit-write-entry.json; s=$?; rm -f /tmp/audit-write-entry.json; exit $s' \
  < workflows/audit-write-entry.json 2>&1 | tail -1
docker compose run --rm --no-deps -T n8n publish:workflow --id=auditWriteEntry1 2>&1 | grep -i "publishing"
docker compose restart n8n >/dev/null
echo "Published 'Audit: write entry' and restarted n8n."
