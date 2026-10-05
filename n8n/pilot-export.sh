#!/bin/bash
# Exports the pilot's triage decisions for scripts/pilot_numbers.py (Story 8.1):
# every failure message W3 posted between <start> and <end> (YYYY-MM-DD, UTC
# days, inclusive), its suggested class, and its final reaction after any undo
# (the live decision), as JSON. Reads n8n's database; changes nothing.
#   n8n/pilot-export.sh 2026-10-12 2026-10-25 > pilot/decisions.json
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
[ $# -eq 2 ] || { echo "usage: n8n/pilot-export.sh <start YYYY-MM-DD> <end YYYY-MM-DD>" >&2; exit 2; }
for d in "$1" "$2"; do [[ "$d" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "not a date: $d" >&2; exit 2; }; done
docker compose exec -T -e START="$1" -e END="$2" postgres sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v start="$START" -v end="$END"' <<'SQL'
SELECT coalesce(json_agg(json_build_object(
         'nightly_run_id', m.nightly_run_id, 'test_id', m.test_id, 'suggested_class', m.class,
         'posted_at', to_char(m.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
         'final_reaction', d.action, 'decided_by', d.actor_email) ORDER BY m.id), '[]')
FROM audit.message_map m
LEFT JOIN audit.reaction_decisions d ON d.map_id = m.id AND d.undone_at IS NULL AND d.state = 'handled'
WHERE m.kind = 'failure' AND m.created_at >= :'start'::date AND m.created_at < :'end'::date + 1;
SQL
