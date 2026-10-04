"""Tests for the triage workflow's decisions (Story 6.2)."""

import copy
import io
import json
import zipfile

import pytest

import agent_gate
import agent_triage
from validate_contract import CONTRACTS, validate

TRIAGE_INPUT = json.loads((CONTRACTS / "samples" / "triage-input.sample.json").read_text())
API_TEST = TRIAGE_INPUT["failures"][0]["test_id"]
UI_TEST = "ui:tests/login.spec.ts > Login > office admin signs in"


def triage_input(flaky_candidate=False, history=("passed",)):
    data = copy.deepcopy(TRIAGE_INPUT)
    data["failures"][0]["history"] = [{"nightly_run_id": 100 + i, "result": r} for i, r in enumerate(history)]
    data["failures"][0]["flaky_candidate"] = flaky_candidate
    data["failures"][0]["status"] = "passed-on-retry" if flaky_candidate else "failed"
    retry = copy.deepcopy(data["failures"][0])
    retry.update(test_id=UI_TEST, flaky_candidate=True, status="passed-on-retry", history=[])
    data["failures"].append(retry)
    return data


def row(test_id, cls, evidence="The API returned 500 on create.", bug_title=None):
    r = {"test_id": test_id, "class": cls, "evidence": evidence}
    if bug_title:
        r["bug_title"] = bug_title
    return r


# ---------------------------------------------------------------- precheck and setup

@pytest.mark.parametrize("value", ["37213558288", "1"])
def test_good_run_id(run, value):
    agent_triage.precheck(value)
    assert run.output == "go=true\n"


@pytest.mark.parametrize("value", ["", "0", "abc", "12; rm -rf", "-5", "1" * 21])
def test_bad_run_id(run, value):
    agent_triage.precheck(value)
    assert run.result == {"status": "error", "reason": "invalid-nightly-run-id", "pr_url": ""}


def test_setup_needs_only_the_claude_token(run, monkeypatch):
    agent_triage.setup_check()
    assert run.result["reason"] == "agent-not-set-up" and "CLAUDE_CODE_OAUTH_TOKEN" in run.summary
    assert "qa-agent" not in run.summary
    monkeypatch.setenv("HAS_CLAUDE_TOKEN", "true")
    (run.temp / "agent-result.json").unlink()
    agent_triage.setup_check()
    assert run.result is None and run.output.endswith("go=true\n")


# ---------------------------------------------------------------- fetch

class FakeArtifacts:
    def __init__(self, data):
        self.data = data

    def triage_input(self, run_id):
        return self.data


def test_fetch_saves_the_input(run):
    agent_triage.fetch(TRIAGE_INPUT["nightly_run_id"], FakeArtifacts(TRIAGE_INPUT))
    assert run.output == "go=true\n"
    assert json.loads((run.temp / "triage-input.json").read_text()) == TRIAGE_INPUT


def test_fetch_missing_input_is_blocked(run):
    agent_triage.fetch(5, FakeArtifacts(None))
    assert run.result == {"status": "blocked", "reason": "no-triage-input", "pr_url": ""}
    assert not (run.temp / "triage-input.json").exists()


@pytest.mark.parametrize(
    "change, shown",
    [
        (lambda d: d.update(schema_version=2), "unknown schema_version 2"),
        (lambda d: d.update(nightly_run_id=99), "triage-input is for nightly run 99, not"),
        (lambda d: d["failures"][0].update(screenshot="x.png"), "Additional properties are not allowed"),
    ],
)
def test_fetch_rejects_a_bad_input(run, change, shown):
    data = copy.deepcopy(TRIAGE_INPUT)
    change(data)
    agent_triage.fetch(TRIAGE_INPUT["nightly_run_id"], FakeArtifacts(data))
    assert run.result["reason"] == "invalid-triage-input" and shown in run.summary


def test_artifacts_reads_only_triage_input(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("triage-input.json", json.dumps(TRIAGE_INPUT))
    asked = []
    responses = {
        "https://api.github.com/repos/o/r/actions/runs/7/artifacts?name=triage-input":
            json.dumps({"artifacts": [{"expired": False, "archive_download_url": "https://dl/zip"}]}).encode(),
        "https://dl/zip": buffer.getvalue(),
    }
    github = agent_triage.Artifacts("t", "o/r")
    monkeypatch.setattr(github, "_get", lambda url: asked.append(url) or responses[url])
    assert github.triage_input(7) == TRIAGE_INPUT
    assert asked[0].endswith("artifacts?name=triage-input")


# ---------------------------------------------------------------- the flaky rule and the checks

@pytest.mark.parametrize(
    "flaky_candidate, history, kept",
    [
        (True, ("passed",) * 7, True),
        (False, ("passed", "failed", "passed"), True),
        (False, ("passed-on-retry",), True),
        (False, ("passed",) * 7, False),
        (False, ("not-run", "quarantined"), False),
        (False, (), False),
    ],
)
def test_flaky_needs_rerun_evidence(flaky_candidate, history, kept):
    data = triage_input(flaky_candidate, history)
    triage = {"failures": [row(API_TEST, "flaky", "Timed out once."), row(UI_TEST, "flaky", "Passed on retry tonight.")]}
    out, problems = agent_triage.finalize(triage, data)
    assert problems == []
    first = out["failures"][0]
    assert first["class"] == ("flaky" if kept else "unknown")
    if not kept:
        assert first["evidence"].startswith(agent_triage.DOWNGRADED)
    assert out["failures"][1]["class"] == "flaky"  # passed on retry tonight
    validate("triage", out)


@pytest.mark.parametrize(
    "rows, problem",
    [
        ([row(API_TEST, "test_defect")], f"missing: {UI_TEST}"),
        ([row(API_TEST, "test_defect"), row(UI_TEST, "unknown"), row(UI_TEST, "unknown")], f"listed 2 times: {UI_TEST}"),
        ([row(API_TEST, "test_defect"), row(UI_TEST, "unknown"), row("api:tests/x.py::test_y", "unknown")],
         "not in the input: api:tests/x.py::test_y"),
        ([row(API_TEST, "product_defect"), row(UI_TEST, "unknown")], "'bug_title' is a required property"),
        ([row(API_TEST, "test_defect", bug_title="A title for a test"), row(UI_TEST, "unknown")], "should not be valid"),
        ([row(API_TEST, "broken"), row(UI_TEST, "unknown")], "'broken' is not one of"),
        ([row(API_TEST, "unknown", "two\nlines here"), row(UI_TEST, "unknown")], "does not match"),
    ],
)
def test_bad_classifications_are_named(rows, problem):
    _, problems = agent_triage.finalize({"failures": rows}, triage_input())
    assert any(problem in p for p in problems), problems


def write(run, triage):
    (run.temp / "triage-input.json").write_text(json.dumps(triage_input()))
    if triage is not None:
        (run.temp / "triage.json").write_text(triage if isinstance(triage, str) else json.dumps(triage))


def test_check_saves_a_valid_triage(run, repo):
    write(run, {"failures": [row(API_TEST, "product_defect", bug_title="Job create returns 500 on save"),
                             row(UI_TEST, "flaky", "Passed on retry tonight.")]})
    assert agent_triage.check(repo) == 0
    saved = json.loads((run.temp / "triage.json").read_text())
    assert next(iter(saved)) == "schema_version" and saved["nightly_run_id"] == TRIAGE_INPUT["nightly_run_id"]
    assert run.result == {"status": "ok", "reason": "", "pr_url": ""}
    assert "- Flaky (suggested): 1" in run.summary and "- Product defect (suggested): 1" in run.summary


@pytest.mark.parametrize("triage, problem", [(None, "the agent wrote no triage.json"), ("{oops", "triage.json is not valid JSON")])
def test_check_without_a_usable_file(run, repo, triage, problem):
    write(run, triage)
    agent_triage.check(repo)
    assert run.result["reason"] == "invalid-triage" and problem in run.summary


def test_check_fails_when_the_repository_changed(run, repo):
    write(run, {"failures": [row(API_TEST, "unknown"), row(UI_TEST, "unknown")]})
    (repo / "cases" / "README.md").write_text("changed by the agent")
    agent_triage.check(repo)
    assert run.result["reason"] == "invalid-triage" and "changed a repository file: cases/README.md" in run.summary


def test_blocked_triage_is_not_counted_and_the_workflow_is_locked_down():
    assert "blocked" in agent_gate.EXCLUDED
    text = (agent_triage.ROOT / ".github" / "workflows" / "triage.yml").read_text()
    assert '--allowedTools "Read,Write"' in text
    assert '--disallowedTools "Bash,Edit,WebFetch,WebSearch"' in text
    assert "run-name: triage ${{ inputs.nightly_run_id }}" in text
    assert "actions: read" in text and "contents: write" not in text and "QA_AGENT" not in text
