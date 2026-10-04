"""Tests for the agent workflows' shared first and last steps (Story 4.4)."""

import io
import json
import zipfile
from datetime import UTC, datetime

import pytest

import agent_gate
from validate_contract import CONTRACTS, validate

FIXTURE = json.loads((CONTRACTS / "cap-count.fixture.json").read_text())
NOW = datetime(2026, 10, 4, 5, 0, tzinfo=UTC)  # 10:30 IST
REF = "arpanpandeygate6/poolbrain-qa/.github/workflows/draft-cases.yml@refs/heads/main"


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=[c["name"] for c in FIXTURE["cases"]])
def test_count_passes_the_shared_fixture(case):
    now = datetime.fromisoformat(case["now"])
    assert agent_gate.count_today(case["runs"], now, case["current_run_id"]) == case["expected"]


@pytest.mark.parametrize(
    "now, midnight",
    [
        ("2026-10-04T05:00:00+00:00", "2026-10-03T18:30:00+00:00"),
        ("2026-10-03T18:29:59+00:00", "2026-10-02T18:30:00+00:00"),
        ("2026-10-03T18:30:00+00:00", "2026-10-03T18:30:00+00:00"),
    ],
)
def test_ist_midnight(now, midnight):
    assert agent_gate.ist_midnight(datetime.fromisoformat(now)) == datetime.fromisoformat(midnight)


def test_workflow_name():
    assert agent_gate.workflow_name(REF) == "draft-cases"


@pytest.mark.parametrize(
    "caps, expected",
    [
        ('{"draft-cases": 20}', (20, "")),
        ('{"draft-cases": 0}', (0, "")),
        (None, (None, "AGENT_CAPS is missing or not valid JSON")),
        ("{oops", (None, "AGENT_CAPS is missing or not valid JSON")),
        ('{"triage": 2}', (None, "AGENT_CAPS has no daily limit for draft-cases")),
        ('{"draft-cases": "20"}', (None, "AGENT_CAPS has no daily limit for draft-cases")),
        ('{"draft-cases": true}', (None, "AGENT_CAPS has no daily limit for draft-cases")),
        ("[20]", (None, "AGENT_CAPS has no daily limit for draft-cases")),
    ],
)
def test_read_cap(caps, expected):
    assert agent_gate.read_cap(caps, "draft-cases") == expected


class FakeGitHub:
    def __init__(self, runs, outcomes=None):
        self.runs, self.outcomes, self.asked = runs, outcomes or {}, []

    def runs_since(self, workflow_file, since):
        self.asked.append((workflow_file, since))
        return self.runs

    def outcome(self, run_id):
        return self.outcomes.get(run_id)


@pytest.fixture
def actions(tmp_path, monkeypatch):
    """A GitHub Actions run: its environment and the files it writes."""
    for name in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
        (tmp_path / name).write_text("")
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_RUN_ID", "500")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", REF)
    monkeypatch.setenv("AGENT_ENABLED", "true")
    monkeypatch.setenv("AGENT_CAPS", '{"draft-cases": 2}')

    class Run:
        output = property(lambda self: (tmp_path / "GITHUB_OUTPUT").read_text())
        summary = property(lambda self: (tmp_path / "GITHUB_STEP_SUMMARY").read_text())
        outcome = property(lambda self: json.loads((tmp_path / "run-outcome.json").read_text())
                           if (tmp_path / "run-outcome.json").exists() else None)
    return Run()


def run(status, created="2026-10-04T01:00:00Z", run_id=1):
    return {"id": run_id, "created_at": created, "status": status}


def test_proceeds_under_the_limit(actions, capsys):
    github = FakeGitHub([run("completed", run_id=1), run("in_progress", run_id=500)], {1: "ok"})
    assert agent_gate.start("PM-1", github, NOW) == 0
    assert actions.output == "proceed=true\n"
    assert actions.outcome is None
    assert github.asked == [("draft-cases.yml", datetime(2026, 10, 3, 18, 30, tzinfo=UTC))]
    assert "1 of 2 runs used today" in capsys.readouterr().out


@pytest.mark.parametrize("value", [None, "false", "TRUE", " true", "yes"])
def test_kill_switch_stops_before_anything_else(actions, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("AGENT_ENABLED")
    else:
        monkeypatch.setenv("AGENT_ENABLED", value)
    github = FakeGitHub([])
    assert agent_gate.start("PM-1", github, NOW) == 0
    assert actions.output == "proceed=false\n"
    assert github.asked == []  # not even GitHub is asked
    assert actions.outcome["status"] == "disabled" and actions.outcome["ticket_key"] == "PM-1"
    assert "Result: Not run (agent is turned off)" in actions.summary
    validate("run-outcome", actions.outcome)


def test_capped_counts_outcomes(actions):
    runs = [run("completed", run_id=1), run("completed", run_id=2), run("completed", run_id=3), run("queued", run_id=4)]
    github = FakeGitHub(runs, {1: "ok", 2: "capped", 3: "error"})
    assert agent_gate.start("PM-1", github, NOW) == 0
    assert actions.output == "proceed=false\n"
    assert actions.outcome["status"] == "capped" and actions.outcome["reason"] == "daily-cap-reached"
    assert "Result: Waiting until tomorrow (daily limit reached)" in actions.summary
    assert "Today's limit of 2 is reached: 3 runs counted since 00:00 IST" in actions.summary


def test_broken_caps_fail_the_job_without_a_model_call(actions, monkeypatch):
    monkeypatch.setenv("AGENT_CAPS", '{"triage": 2}')
    github = FakeGitHub([])
    assert agent_gate.start("PM-1", github, NOW) == 1
    assert actions.output == "proceed=false\n" and github.asked == []
    assert actions.outcome["status"] == "error" and actions.outcome["reason"] == "caps-invalid"
    assert "AGENT_CAPS has no daily limit for draft-cases. No model was called." in actions.summary


def test_finish_writes_a_valid_outcome(actions):
    assert agent_gate.finish("PM-1", "ok", "", "https://github.com/o/r/pull/7") == 0
    outcome = actions.outcome
    assert next(iter(outcome)) == "schema_version"
    assert outcome["status"] == "ok" and outcome["run_id"] == 500 and outcome["workflow"] == "draft-cases"
    assert outcome["pr_url"] == "https://github.com/o/r/pull/7"
    assert "Result: Done" in actions.summary


def test_finish_keeps_the_first_steps_outcome(actions, monkeypatch):
    monkeypatch.setenv("AGENT_ENABLED", "false")
    agent_gate.start("PM-1", FakeGitHub([]), NOW)
    assert agent_gate.finish("PM-1", "error", "", "") == 0
    assert actions.outcome["status"] == "disabled"


def test_finish_rejects_an_invalid_outcome(actions, capsys):
    assert agent_gate.finish("PM-1", "blocked", "Cases Not Merged", "") == 1
    assert "run-outcome is not valid" in capsys.readouterr().out
    assert actions.outcome is None


def test_outcome_is_read_from_the_artifact_zip(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("run-outcome.json", json.dumps({"status": "blocked"}))
    responses = {
        "https://api.github.com/repos/o/r/actions/runs/9/artifacts?name=run-outcome":
            json.dumps({"artifacts": [{"expired": False, "archive_download_url": "https://dl/zip"}]}).encode(),
        "https://dl/zip": buffer.getvalue(),
    }
    github = agent_gate.GitHub("t", "o/r")
    monkeypatch.setattr(github, "_get", lambda url: responses[url])
    assert github.outcome(9) == "blocked"
    responses["https://api.github.com/repos/o/r/actions/runs/9/artifacts?name=run-outcome"] = b'{"artifacts": []}'
    assert github.outcome(9) is None


def test_token_is_not_sent_to_the_artifact_storage():
    request = None

    def capture(req, timeout):
        nonlocal request
        request = req
        raise StopIteration

    original = agent_gate.urllib.request.urlopen
    agent_gate.urllib.request.urlopen = capture
    try:
        with pytest.raises(StopIteration):
            agent_gate.GitHub("secret-token", "o/r")._get("https://api.github.com/x")
    finally:
        agent_gate.urllib.request.urlopen = original
    assert request.unredirected_hdrs == {"Authorization": "Bearer secret-token"}
    assert "Authorization" not in request.headers
