#!/bin/bash
# Starts the pretend PoolBrain on a laptop: MySQL in Docker, then the web app.
# Leave it running in its own terminal; press Ctrl+C to stop the app
# (MySQL keeps running: `cd mock-poolbrain && docker compose stop` stops it).
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

if [ ! -f .env ]; then
  (umask 077; echo "MOCK_DB_ROOT_PASSWORD=$(openssl rand -hex 16)" > .env)
  echo "Created mock-poolbrain/.env with a random MySQL root password."
fi

docker compose up -d --wait mysql
exec ../api-tests/.venv/bin/python app.py
