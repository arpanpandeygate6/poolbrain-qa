#!/bin/bash
# Restore drill (Story 5.1): restores a backup into a throwaway, offline copy
# of n8n and checks that workflows and credentials come back and decrypt.
# Does not touch the running n8n. Usage: ./restore-drill.sh [backup-file]
# (default: the newest backup in BACKUP_DIR).
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

set -a; . ./.env; set +a
backup="${1:-$(ls -t "$BACKUP_DIR"/n8n-*.dump 2>/dev/null | head -1)}"
[ -n "$backup" ] && [ -s "$backup" ] || { echo "No backup found in $BACKUP_DIR"; exit 1; }

pg_image=$(docker compose config --images | grep postgres)
n8n_image=$(docker compose config --images | grep n8n)
net="n8n-drill-$$"
db="n8n-drill-db-$$"
cleanup() { docker rm -f "$db" >/dev/null 2>&1 || true; docker network rm "$net" >/dev/null 2>&1 || true; }
trap cleanup EXIT

start=$(date +%s)
echo "Restoring $backup into a throwaway database..."
docker network create "$net" >/dev/null
docker run -d --name "$db" --network "$net" -e POSTGRES_USER=drill -e POSTGRES_PASSWORD=drill \
  -e POSTGRES_DB=n8n "$pg_image" >/dev/null
until docker exec "$db" pg_isready -U drill -d n8n >/dev/null 2>&1; do sleep 1; done
sleep 2
docker exec -i "$db" pg_restore -U drill -d n8n --no-owner --no-privileges < "$backup"

n8n_cli() {
  docker run --rm --network "$net" \
    -e DB_TYPE=postgresdb -e DB_POSTGRESDB_HOST="$db" -e DB_POSTGRESDB_DATABASE=n8n \
    -e DB_POSTGRESDB_USER=drill -e DB_POSTGRESDB_PASSWORD=drill \
    -e N8N_ENCRYPTION_KEY="$N8N_ENCRYPTION_KEY" -e N8N_DIAGNOSTICS_ENABLED=false \
    --entrypoint n8n "$n8n_image" "$@"
}

count() { docker exec "$db" psql -U drill -d n8n -tAc "select count(*) from $1"; }
workflows=$(count workflow_entity)
creds=$(count credentials_entity)
echo "Workflows restored: $workflows"
echo "Credentials restored: $creds"
if [ "$creds" -gt 0 ]; then
  # Exporting with --decrypted fails when the encryption key doesn't match.
  if n8n_cli export:credentials --all --decrypted --output=/tmp/check.json >/dev/null 2>&1; then
    echo "Credentials decrypt with the stored key: yes"
  else
    echo "Credentials could NOT be decrypted: check N8N_ENCRYPTION_KEY"; exit 1
  fi
else
  echo "Credentials decrypt with the stored key: nothing to check yet (no credentials saved)"
fi

echo "Restore drill PASSED in $(( $(date +%s) - start ))s on $(date -u +%Y-%m-%dT%H:%MZ)."
echo "Record the date, duration and result in docs/runbook.md."
