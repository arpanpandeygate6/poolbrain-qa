#!/usr/bin/env python3
"""Checks n8n's heartbeat for the heartbeat-watch workflow (Story 5.4).

n8n's W5 workflow sets the repository variable N8N_HEARTBEAT_AT to the current
UTC time every hour. If the value is more than 2 hours old, missing or not a
valid timestamp, n8n is treated as down and the S15 alert is raised.

The alert is the job summary plus a failed run (GitHub emails the repository
owner about failed scheduled runs). When SLACK_WEBHOOK_URL is set, it is also
posted to Slack. An outage is alerted at most once every 6 hours: pass
--alerted-recently when this workflow already failed in the last 6 hours.

Usage:
    python scripts/heartbeat_check.py --value "$N8N_HEARTBEAT_AT" [--alerted-recently]
Exit code 1 means "alert now"; 0 means healthy, or stale but already alerted.
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime, timedelta, timezone

STALE_AFTER = timedelta(hours=2)
IST = timezone(timedelta(hours=5, minutes=30))


def check(value: str, now: datetime) -> tuple[bool, str]:
    """Return (healthy, last_seen) where last_seen is an IST time, 'never' or 'unreadable'."""
    value = (value or "").strip()
    if not value:
        return False, "never"
    try:
        seen = datetime.fromisoformat(value)
    except ValueError:
        return False, "unreadable"
    if seen.tzinfo is None:
        return False, "unreadable"
    last_seen = seen.astimezone(IST).strftime("%d %b %Y %H:%M IST")
    return now - seen <= STALE_AFTER, last_seen


def alert_text(last_seen: str) -> str:
    when = f"Last seen {last_seen} (over 2 hours ago)." if last_seen[0].isdigit() else f"Last seen: {last_seen}."
    return (
        f"*Alert: n8n heartbeat is stale.* {when}\n"
        "Waiting until n8n is back: Slack posts and Jira filing.\n"
        "Still running: all GitHub test workflows.\n"
        "Action for the n8n maintainer: check that Docker Desktop and n8n are running "
        "(`cd n8n && docker compose ps`), then start them with `docker compose up -d`.\n"
        "Tickets catch up on their own when it is back."
    )


def post_to_slack(webhook_url: str, text: str) -> None:
    body = json.dumps({"text": text}).encode()
    request = urllib.request.Request(webhook_url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30):
        pass


def _summary(text: str) -> None:
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check n8n's heartbeat.")
    parser.add_argument("--value", default="", help="value of the N8N_HEARTBEAT_AT variable")
    parser.add_argument("--alerted-recently", action="store_true", help="already alerted in the last 6 hours")
    args = parser.parse_args(argv)

    healthy, last_seen = check(args.value, now or datetime.now(UTC))
    if healthy:
        _summary(f"## heartbeat-watch — OK\n\nn8n last seen {last_seen}.")
        return 0
    if args.alerted_recently:
        _summary(f"## heartbeat-watch — still stale\n\nLast seen: {last_seen}. Already alerted in the last 6 hours.")
        return 0

    text = alert_text(last_seen)
    _summary("## heartbeat-watch — ALERT\n\n" + text)
    if webhook := os.environ.get("SLACK_WEBHOOK_URL"):
        post_to_slack(webhook, text)
    return 1


if __name__ == "__main__":
    sys.exit(main())
