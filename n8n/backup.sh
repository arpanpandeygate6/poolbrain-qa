#!/bin/bash
# Backs up n8n's PostgreSQL database (workflows, credentials, executions, audit log)
# to BACKUP_DIR from n8n/.env, and deletes backups older than 30 days.
# The backup holds credentials only in encrypted form; the key is not in it.
#
# Run nightly (see docs/runbook.md). Exits non-zero and shows a macOS
# notification when the backup fails, so a failure is seen the next morning.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

fail() {
  echo "n8n backup FAILED: $1" >&2
  osascript -e "display notification \"$1\" with title \"n8n backup FAILED\"" 2>/dev/null || true
  exit 1
}
trap 'fail "unexpected error on line $LINENO"' ERR

[ -f .env ] || fail "n8n/.env is missing; run ./setup.sh"
set -a; . ./.env; set +a
[ -n "${BACKUP_DIR:-}" ] || fail "BACKUP_DIR is not set in n8n/.env"
mkdir -p "$BACKUP_DIR"

file="$BACKUP_DIR/n8n-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom > "$file" \
  || { rm -f "$file"; fail "pg_dump failed (is n8n running?)"; }
[ -s "$file" ] || { rm -f "$file"; fail "backup file is empty"; }

find "$BACKUP_DIR" -name 'n8n-*.dump' -mtime +30 -delete
echo "n8n backup OK: $file ($(du -h "$file" | cut -f1))"
