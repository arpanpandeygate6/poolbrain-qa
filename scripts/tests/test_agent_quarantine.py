"""Tests for the quarantine workflow (Story 6.5)."""

import json
import shutil

import pytest
import yaml

import agent_quarantine
from run_summary import load_quarantine
from validate_contract import CONTRACTS

SAMPLE = json.loads((CONTRACTS / "samples" / "quarantine-request.sample.json").read_text())
REAL_FILE = agent_quarantine.ROOT / "flows" / "quarantine.yaml"


def request_file(tmp_path, data):
    path = tmp_path / "request.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


@pytest.fixture
def flows(tmp_path):
    """A repository root with a copy of the real flows/quarantine.yaml (comments and an empty list)."""
    (tmp_path / "flows").mkdir()
    shutil.copy(REAL_FILE, tmp_path / "flows" / "quarantine.yaml")
    return tmp_path


def test_precheck_accepts_the_sample(run, tmp_path):
    agent_quarantine.precheck(request_file(tmp_path, SAMPLE), "PM-5679")
    assert run.output == "go=true\n" and run.result is None


@pytest.mark.parametrize(
    "data, key, shown",
    [
        ("{not json", "PM-5679", "Expecting property name"),
        ({**SAMPLE, "schema_version": 2}, "PM-5679", "unknown schema_version 2"),
        ({k: v for k, v in SAMPLE.items() if k != "owner"}, "PM-5679", "'owner' is a required property"),
        ({**SAMPLE, "deadline": "15 Oct"}, "PM-5679", "at deadline"),
        (SAMPLE, "PM-1", "its jira_key PM-5679 does not match the jira_key input"),
    ],
)
def test_precheck_rejects_bad_requests(run, tmp_path, data, key, shown):
    agent_quarantine.precheck(request_file(tmp_path, data), key)
    assert run.result == {"status": "error", "reason": "invalid-request", "pr_url": ""}
    assert shown in run.summary


def test_already_quarantined_or_already_open(run, flows):
    agent_quarantine.add_entry(SAMPLE, flows)
    agent_quarantine.repo_check(SAMPLE, flows, find_pr=lambda branch: "")
    assert run.result["reason"] == "already-quarantined" and run.output == "go=false\n"
    other = {**SAMPLE, "test_id": "api:tests/test_x.py::test_y"}
    asked = []
    agent_quarantine.repo_check(other, flows, find_pr=lambda branch: asked.append(branch) or "https://github.com/o/r/pull/8")
    assert asked == ["agent/PM-5679-quarantine"]
    assert run.result == {"status": "ok", "reason": "already-open", "pr_url": "https://github.com/o/r/pull/8"}


def test_nothing_in_the_way(run, flows):
    agent_quarantine.repo_check(SAMPLE, flows, find_pr=lambda branch: "")
    assert run.output == "go=true\n"


def test_setup_needs_only_the_app(run, monkeypatch):
    monkeypatch.setenv("HAS_APP_ID", "true")
    agent_quarantine.setup_check()
    assert run.result["reason"] == "agent-not-set-up" and "QA_AGENT_PRIVATE_KEY" in run.summary
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in run.summary


def test_add_entry_to_the_empty_list_keeps_the_comments(flows):
    before = REAL_FILE.read_text()
    agent_quarantine.add_entry(SAMPLE, flows)
    after = (flows / "flows" / "quarantine.yaml").read_text()
    comments = [line for line in before.splitlines() if line.startswith("#")]
    assert [line for line in after.splitlines() if line.startswith("#")] == comments
    assert yaml.safe_load(after) == [{"test_id": SAMPLE["test_id"], "owner": "ravi", "jira": "PM-5679", "deadline": "2026-10-19"}]
    # What the nightly reads: the test now counts as QUARANTINED.
    assert load_quarantine(flows / "flows" / "quarantine.yaml") == {SAMPLE["test_id"]}


def test_add_entry_appends_to_a_list(flows):
    agent_quarantine.add_entry(SAMPLE, flows)
    second = {**SAMPLE, "test_id": 'api:tests/test_jobs.py::test_route "sort": by time', "jira_key": "PM-6000", "owner": "asha: QA"}
    agent_quarantine.add_entry(second, flows)
    entries = yaml.safe_load((flows / "flows" / "quarantine.yaml").read_text())
    assert [e["test_id"] for e in entries] == [SAMPLE["test_id"], second["test_id"]]
    assert entries[1]["owner"] == "asha: QA" and entries[1]["jira"] == "PM-6000"


def test_pr_body():
    request = {**SAMPLE, "slack_thread": "https://slack.example/archives/C1/p1"}
    title, body = agent_quarantine.pr_body(request)
    assert title == "[PM-5679] Quarantine: ui:tests/routes.spec.ts > Routes > sorts by time"
    assert body.startswith("## Summary\nPassed on retry tonight; failed 3 of the last 7 nights with the same timeout. "
                           "A QA member (asha@gate6.com) marked it Flaky.")
    assert "owner ravi, Jira PM-5679, deadline 19 Oct 2026" in body
    assert "The test still runs every night but no longer blocks the gate." in body
    assert "2. Merge. Until then, the test keeps gating." in body
    assert body.rstrip().endswith("Jira PM-5679 · [Slack thread](https://slack.example/archives/C1/p1) · "
                                  "[Run](https://github.com/arpanpandeygate6/poolbrain-qa/actions/runs/37213558288)")


def test_opened(run, tmp_path):
    agent_quarantine.main(["opened", "--request-file", str(request_file(tmp_path, SAMPLE)), "--pr-url", "https://github.com/o/r/pull/9"])
    assert run.result == {"status": "ok", "reason": "", "pr_url": "https://github.com/o/r/pull/9"}
    assert "Until then, the test keeps gating." in run.summary


def test_workflow_changes_only_the_quarantine_list_and_calls_no_model():
    text = (agent_quarantine.ROOT / ".github" / "workflows" / "quarantine.yml").read_text()
    assert "git add flows/quarantine.yaml" in text and "git add -A" not in text
    assert "claude-code-action" not in text and "CLAUDE_CODE_OAUTH_TOKEN" not in text
    assert 'branch="agent/$JIRA_KEY-quarantine"' in text and '"HEAD:refs/heads/$branch"' in text
    assert "run-name: quarantine ${{ inputs.jira_key }}" in text
