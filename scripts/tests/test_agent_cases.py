"""Tests for the draft-cases workflow's decisions (Story 4.5)."""

import json
import subprocess

import pytest

import agent_cases
import agent_gate
from case_lint import POINTER
from tests.test_case_lint import GOOD, INVENTORY, QUESTION, questions


@pytest.fixture
def run(tmp_path, monkeypatch):
    """A workflow run: RUNNER_TEMP, GITHUB_OUTPUT and GITHUB_STEP_SUMMARY."""
    temp = tmp_path / "temp"
    temp.mkdir()
    for name in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
        (temp / name).write_text("")
        monkeypatch.setenv(name, str(temp / name))
    monkeypatch.setenv("RUNNER_TEMP", str(temp))

    class Run:
        output = property(lambda self: (temp / "GITHUB_OUTPUT").read_text())
        summary = property(lambda self: (temp / "GITHUB_STEP_SUMMARY").read_text())
        result = property(lambda self: json.loads((temp / "agent-result.json").read_text())
                          if (temp / "agent-result.json").exists() else None)
    r = Run()
    r.temp = temp
    return r


@pytest.fixture
def repo(tmp_path):
    """A checkout of main: the inventory and an empty cases/ folder, committed."""
    root = tmp_path / "repo"
    (root / "flows").mkdir(parents=True)
    (root / "flows" / "inventory.yaml").write_text(INVENTORY)
    (root / "cases").mkdir()
    (root / "cases" / "README.md").write_text("# Test cases\n")
    for command in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "main"]):
        subprocess.run(["git", *command], cwd=root, check=True)
    return root


def write_cases(root, text=GOOD, qs=None):
    (root / "cases" / "PM-1234.md").write_text(text)
    (root / "cases" / "PM-1234.questions.json").write_text(qs if qs is not None else questions())


# ---------------------------------------------------------------- precheck

@pytest.mark.parametrize("ticket", ["PM-1234", "QA2-1"])
def test_good_key_goes_on(run, ticket):
    assert agent_cases.precheck(ticket, "key") == 0
    assert run.output == "go=true\n" and run.result is None


@pytest.mark.parametrize("ticket, shown", [("pm-1234", "pm-1234"), ("PM-12 34", "PM-12?34"), ("PM-1`rm -rf`", "PM-1?rm?-rf?")])
def test_bad_key_stops_before_anything_else(run, ticket, shown):
    agent_cases.precheck(ticket, "key")
    assert run.output == "go=false\n"
    assert run.result == {"status": "error", "reason": "invalid-ticket-key", "pr_url": ""}
    assert f"`{shown}` is not a Jira key like PM-1234" in run.summary


def test_cases_already_on_main(run, repo):
    write_cases(repo)
    agent_cases.precheck("PM-1234", "repo", repo, find_pr=lambda branch: "")
    assert run.result["status"] == "blocked" and run.result["reason"] == "cases-already-on-main"
    assert run.output == "go=false\n"


def test_pr_already_open_gives_no_second_pr(run, repo):
    asked = []
    agent_cases.precheck("PM-1234", "repo", repo, find_pr=lambda branch: asked.append(branch) or "https://github.com/o/r/pull/9")
    assert asked == ["agent/PM-1234-cases"]
    assert run.result == {"status": "ok", "reason": "already-open", "pr_url": "https://github.com/o/r/pull/9"}
    assert run.output == "go=false\n"


def test_nothing_in_the_way(run, repo):
    agent_cases.precheck("PM-1234", "repo", repo, find_pr=lambda branch: "")
    assert run.output == "go=true\n" and run.result is None


# ---------------------------------------------------------------- setup and failures

def test_setup_check(run, monkeypatch):
    monkeypatch.setenv("HAS_CLAUDE_TOKEN", "true")
    monkeypatch.setenv("HAS_APP_ID", "false")
    agent_cases.setup_check("PM-1234")
    assert run.result["reason"] == "agent-not-set-up" and run.output == "go=false\n"
    assert "the qa-agent app ID QA_AGENT_APP_ID; the qa-agent private key QA_AGENT_PRIVATE_KEY missing" in run.summary
    assert "/draft-cases PM-1234" in run.summary


def test_setup_complete(run, monkeypatch):
    for name in ("HAS_CLAUDE_TOKEN", "HAS_APP_ID", "HAS_APP_KEY"):
        monkeypatch.setenv(name, "true")
    agent_cases.setup_check("PM-1234")
    assert run.output == "go=true\n" and run.result is None


def test_agent_failed_gives_the_laptop_hint(run):
    agent_cases.agent_failed("PM-1234")
    assert run.result == {"status": "error", "reason": "agent-failed", "pr_url": ""}
    assert "Claude Max limit may be reached or the token may have expired" in run.summary
    assert "A QA member can run `/draft-cases PM-1234` in Claude Code on a laptop instead." in run.summary


# ---------------------------------------------------------------- check

def test_good_output_goes_on(run, repo):
    write_cases(repo)
    assert agent_cases.check("PM-1234", repo) == 0
    assert run.output == "go=true\n" and run.result is None


def test_agent_stop_is_blocked(run, repo):
    (run.temp / "agent-stop.json").write_text(json.dumps({"reason": "no-matching-flow", "message": "Billing has no flow."}))
    agent_cases.check("PM-1234", repo)
    assert run.result["status"] == "blocked" and run.result["reason"] == "no-matching-flow"
    assert "Result: Blocked (no-matching-flow). Billing has no flow." in run.summary


def test_odd_stop_reason_is_replaced(run, repo):
    (run.temp / "agent-stop.json").write_text(json.dumps({"reason": "Nope!! <b>", "message": ""}))
    agent_cases.check("PM-1234", repo)
    assert run.result["reason"] == "agent-stopped"


@pytest.mark.parametrize(
    "change, problem",
    [
        (lambda root: (root / "flows" / "inventory.yaml").write_text(INVENTORY + "\n# edited\n"), "unexpected change: flows/inventory.yaml"),
        (lambda root: (root / "notes.txt").write_text("x"), "unexpected change: notes.txt"),
        (lambda root: (root / "cases" / "PM-1234.md").write_text(GOOD.replace("[job-creation]", "[nope]")), "unknown flow 'nope'"),
        (lambda root: (root / "cases" / "PM-1234.questions.json").write_text(questions(items=[QUESTION])), POINTER),
    ],
)
def test_bad_output_opens_no_pr(run, repo, change, problem):
    write_cases(repo)
    change(repo)
    agent_cases.check("PM-1234", repo)
    assert run.result == {"status": "error", "reason": "invalid-output", "pr_url": ""}
    assert problem in run.summary and run.output == "go=false\n"


def test_missing_case_file(run, repo):
    agent_cases.check("PM-1234", repo)
    assert "cases/PM-1234.md was not written" in run.summary


# ---------------------------------------------------------------- PR

def test_pr_body(repo):
    with_questions = GOOD.replace("(acceptance criteria 1–2)\n", f"(acceptance criteria 1–2)\n\n{POINTER}\n")
    write_cases(repo, with_questions, questions(items=[QUESTION]))
    title, body = agent_cases.pr_body("PM-1234", repo)
    assert title == "[PM-1234] Cases: Job creation with empty route"
    assert "- `cases/PM-1234.md`: 2 cases, flows `job-creation`" in body
    assert "- `cases/PM-1234.questions.json`: 1 clarification question\n" in body
    assert "Clarification questions were posted to Slack for QA approval." in body
    assert "2. Merge to accept the cases. Tests are generated only after this merge." in body


def test_opened_then_finish_writes_ok_with_the_link(run, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "500")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", "o/r/.github/workflows/draft-cases.yml@refs/heads/main")
    agent_cases.opened("PM-1234", "https://github.com/o/r/pull/12")
    assert agent_gate.finish("PM-1234", "error", "", "") == 0  # the recorded result wins over the job status
    outcome = json.loads((run.temp / "run-outcome.json").read_text())
    assert outcome["status"] == "ok" and outcome["pr_url"] == "https://github.com/o/r/pull/12"
    assert outcome["workflow"] == "draft-cases"


def test_finish_with_an_invalid_key_records_no_key(run, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "500")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", "o/r/.github/workflows/draft-cases.yml@refs/heads/main")
    agent_cases.precheck("pm 1", "key")
    assert agent_gate.finish("pm 1", "ok", "", "") == 0
    outcome = json.loads((run.temp / "run-outcome.json").read_text())
    assert outcome["ticket_key"] == "" and outcome["status"] == "error" and outcome["reason"] == "invalid-ticket-key"


def test_workflow_never_pushes_to_main_and_pins_its_actions():
    text = (agent_cases.ROOT / ".github" / "workflows" / "draft-cases.yml").read_text()
    assert '"HEAD:refs/heads/$branch"' in text and 'branch="agent/$TICKET-cases"' in text
    assert "anthropics/claude-code-action@cab360f6565aa35a51d6ce9e43f1f4287c0a32ea" in text
    assert "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1" in text
    assert "if: github.ref == 'refs/heads/main'" in text
    assert 'show_full_output: "false"' in text
    for tool in ("WebFetch", "WebSearch"):
        assert tool in text.split("--disallowedTools", 1)[1].splitlines()[0]
