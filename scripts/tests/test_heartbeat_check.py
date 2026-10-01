"""Tests for the n8n heartbeat check."""

from datetime import UTC, datetime

import pytest

import heartbeat_check
from heartbeat_check import alert_text, check, main

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "value, healthy, last_seen",
    [
        ("2026-10-01T11:00:00Z", True, "01 Oct 2026 16:30 IST"),
        ("2026-10-01T10:00:00Z", True, "01 Oct 2026 15:30 IST"),  # exactly 2 hours
        ("2026-10-01T09:59:00Z", False, "01 Oct 2026 15:29 IST"),
        ("2026-10-01T09:00:00+00:00", False, "01 Oct 2026 14:30 IST"),
        ("", False, "never"),
        ("   ", False, "never"),
        ("yesterday", False, "unreadable"),
        ("2026-10-01T11:00:00", False, "unreadable"),  # no time zone
    ],
)
def test_check(value, healthy, last_seen):
    assert check(value, NOW) == (healthy, last_seen)


def test_alert_wording():
    text = alert_text("01 Oct 2026 14:30 IST")
    assert text.startswith("*Alert: n8n heartbeat is stale.* Last seen 01 Oct 2026 14:30 IST (over 2 hours ago).")
    assert "Tickets catch up on their own when it is back." in text
    assert "Last seen: never." in alert_text("never")


def test_healthy_exits_0(monkeypatch, capsys):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert main(["--value", "2026-10-01T11:30:00Z"], now=NOW) == 0
    assert "heartbeat-watch — OK" in capsys.readouterr().out


def test_stale_alerts_and_posts_to_slack(monkeypatch, capsys):
    posted = []
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.invalid/x")
    monkeypatch.setattr(heartbeat_check, "post_to_slack", lambda url, text: posted.append(text))
    assert main(["--value", "2026-10-01T08:00:00Z"], now=NOW) == 1
    assert "heartbeat-watch — ALERT" in capsys.readouterr().out
    assert len(posted) == 1


def test_stale_without_slack_still_fails(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert main(["--value", ""], now=NOW) == 1


def test_already_alerted_does_not_repeat(monkeypatch, capsys):
    posted = []
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.invalid/x")
    monkeypatch.setattr(heartbeat_check, "post_to_slack", lambda url, text: posted.append(text))
    assert main(["--value", "2026-10-01T08:00:00Z", "--alerted-recently"], now=NOW) == 0
    assert "still stale" in capsys.readouterr().out
    assert posted == []
