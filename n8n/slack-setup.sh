#!/bin/bash
# Installs the shared "Slack: post message" sub-workflow and the W0 error
# handler (Story 5.3), points the other workflows' errors at W0, and installs
# the workflows that post to Slack: the gate check (Story 5.6) and the
# Ready-for-QA notice (Story 5.7).
#
# Slack is optional. Without it, every message becomes a preview you can read
# in the n8n execution, and nothing is sent. To turn Slack on later:
#   1. Put the channel ID in n8n/.env:   SLACK_CHANNEL=C0123456789
#   2. Run with the bot token (it is stored only in the n8n credential, never in a file):
#        SLACK_BOT_TOKEN=xoxb-... ./slack-setup.sh
# Safe to run again. Running without SLACK_BOT_TOKEN keeps the stored token.
# Needs n8n running (docker compose up -d) and ./audit-setup.sh done.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

[ -f .env ] || { echo "n8n/.env is missing; run ./setup.sh first"; exit 1; }
SLACK_BOT_TOKEN_GIVEN="${SLACK_BOT_TOKEN:-}"
set -a; . ./.env; set +a
SLACK_CHANNEL="${SLACK_CHANNEL:-}"

# The "QA Bot (Slack)" credential. A placeholder token is stored the first
# time so the workflow can be installed before the Slack app exists; a real
# token replaces it whenever one is given.
exists=$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
  "SELECT count(*) FROM credentials_entity WHERE id = 'slackQaBot000001'")
if [ -n "$SLACK_BOT_TOKEN_GIVEN" ] || [ "$exists" = "0" ]; then
  docker compose exec -T -e TOKEN="${SLACK_BOT_TOKEN_GIVEN:-xoxb-not-set}" n8n sh -c '
    printf "[{\"id\":\"slackQaBot000001\",\"name\":\"QA Bot (Slack)\",\"type\":\"slackApi\",\"data\":{\"accessToken\":\"%s\"}}]" \
      "$TOKEN" > /tmp/slack-cred.json
    n8n import:credentials --input=/tmp/slack-cred.json; status=$?
    rm -f /tmp/slack-cred.json; exit $status' | tail -1
  [ -n "$SLACK_BOT_TOKEN_GIVEN" ] && echo "Stored the Slack bot token." || echo "Stored a placeholder Slack token."
fi

install() {  # install <file> <id>: import (updating in place) and publish
  docker compose exec -T n8n sh -c 'cat > /tmp/w.json && n8n import:workflow --input=/tmp/w.json; s=$?; rm -f /tmp/w.json; exit $s' \
    < "$1" 2>&1 | tail -1
  docker compose run --rm --no-deps -T n8n publish:workflow --id="$2" 2>&1 | grep -i "publishing" || true
}

# The channel lives only in the sub-workflow's Settings node; empty means preview.
jq --arg ch "$SLACK_CHANNEL" \
  '(.nodes[] | select(.name == "Settings") | .parameters.assignments.assignments[0].value) = $ch' \
  workflows/slack-post-message.json > /tmp/slack-post-message.json
install /tmp/slack-post-message.json slackPostMsg0001
rm -f /tmp/slack-post-message.json
install workflows/w0-error-handler.json w0ErrorHandler1
# The kill-switch and daily-cap check every AI action calls first (Story 5.6).
install workflows/gate-check.json gateCheck0000001

# Workflows that report their errors to W0 (settings.errorWorkflow in their
# files). Re-importing turns a workflow off, so each is published again.
install workflows/w5-heartbeat.json w5Heartbeat00001
install workflows/audit-record-github-runs.json runRecorder00001
install workflows/ready-for-qa-notice.json readyNotice00001

docker compose restart n8n >/dev/null 2>&1
if [ -n "$SLACK_CHANNEL" ]; then
  echo "Done. Slack messages go to channel $SLACK_CHANNEL."
else
  echo "Done. Slack is not set up: messages are previews only (see each execution in n8n)."
fi
