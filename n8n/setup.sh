#!/bin/bash
# Creates n8n/.env with random database password and encryption key.
# Run once, before the first `docker compose up -d`. Never overwrites an existing .env.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  echo "n8n/.env already exists; leaving it unchanged."
  exit 0
fi

umask 077
cat > .env <<ENV
POSTGRES_USER=n8n
POSTGRES_PASSWORD=$(openssl rand -hex 24)
POSTGRES_DB=n8n
N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)
BACKUP_DIR=$HOME/n8n-backups
ENV

echo "Created n8n/.env (readable only by you)."
echo
echo "IMPORTANT: copy N8N_ENCRYPTION_KEY from n8n/.env into your password manager now."
echo "Without it, backups can be restored but their saved credentials can't be decrypted."
