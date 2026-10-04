"""Tests for the draft-cases workflow's decisions (Story 4.5)."""

import json
import subprocess

import pytest

import agent_cases
import agent_gate
from case_lint import POINTER
from tests.test_case_lint import GOOD, INVENTORY, QUESTION, questions


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


# ---------------------------------------------------------------- generate-tests (Story 4.6)

@pytest.fixture
def merged(repo):
    """main with PM-1234's cases merged, an existing API test, a UI spec and the quarantine list."""
    write_cases(repo)
    (repo / "api-tests" / "tests").mkdir(parents=True)
    (repo / "api-tests" / "tests" / "test_old.py").write_text("def test_old():\n    assert True\n")
    (repo / "ui-tests" / "tests").mkdir(parents=True)
    (repo / "ui-tests" / "tests" / "old.spec.ts").write_text("test('old', async () => {});\n")
    (repo / "flows" / "quarantine.yaml").write_text("[]\n")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
    for command in (["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "merged"]):
        subprocess.run(["git", *command], cwd=repo, check=True)
    return repo


NEW_TEST = '''import pytest


@pytest.mark.regression
@pytest.mark.flow("job-creation")
def test_api_job_without_route_is_rejected(logged_in_api):
    """PM-1234-01: Job is rejected without a route."""


def test_api_job_with_route_is_saved(logged_in_api):
    """PM-1234-02: Job with a route is saved."""
'''


def test_tests_need_the_cases_on_main(run, repo):
    agent_cases.precheck("PM-1234", "repo", repo, find_pr=lambda branch: "", kind="tests")
    assert run.result == {"status": "blocked", "reason": "cases-not-merged", "pr_url": ""}
    assert ("### generate-tests\n\nResult: Blocked — cases for PM-1234 are not merged on `main` yet. "
            "Merge PR 1; this retries on its own after that.") in run.summary


def test_blocked_runs_do_not_count_toward_the_cap():
    assert "blocked" in agent_gate.EXCLUDED


def test_tests_go_on_when_merged_and_no_pr_2(run, merged):
    asked = []
    agent_cases.precheck("PM-1234", "repo", merged, find_pr=lambda branch: asked.append(branch) or "", kind="tests")
    assert asked == ["agent/PM-1234-tests"] and run.output == "go=true\n"


def test_pr_2_already_open(run, merged):
    agent_cases.precheck("PM-1234", "repo", merged, find_pr=lambda branch: "https://github.com/o/r/pull/3", kind="tests")
    assert run.result == {"status": "ok", "reason": "already-open", "pr_url": "https://github.com/o/r/pull/3"}
    assert "PR 2 for PM-1234 is already open" in run.summary


def no_problems(root):
    return []


def test_good_tests_go_on(run, merged):
    (merged / "api-tests" / "tests" / "test_route.py").write_text(NEW_TEST)
    (merged / "flows" / "inventory.yaml").write_text(INVENTORY + "# mapped\n")
    (merged / "api-tests" / "utils").mkdir()
    (merged / "api-tests" / "utils" / "api_client.py").write_text("class ApiClient: ...\n")
    assert agent_cases.check("PM-1234", merged, kind="tests", tools=no_problems) == 0
    assert run.output == "go=true\n" and run.result is None


@pytest.mark.parametrize(
    "change, reason, shown",
    [
        (lambda r: (r / ".github" / "workflows" / "ci.yml").write_text("name: changed\n"), "forbidden-change",
         "changes .github/workflows/ci.yml, which generate-tests must never change"),
        (lambda r: (r / "flows" / "quarantine.yaml").write_text("- test_id: x\n"), "forbidden-change",
         "changes flows/quarantine.yaml"),
        (lambda r: (r / "api-tests" / "tests" / "test_route.py").write_text(NEW_TEST.replace("@pytest.mark.regression", "@pytest.mark.skip")),
         "weakened-test", "adds skip, fixme or only: api-tests/tests/test_route.py: @pytest.mark.skip"),
        (lambda r: (r / "ui-tests" / "tests" / "old.spec.ts").write_text("test('old', async () => {});\ntest.fixme('later', async () => {});\n"),
         "weakened-test", "ui-tests/tests/old.spec.ts: test.fixme('later'"),
        (lambda r: (r / "ui-tests" / "tests" / "new.spec.ts").write_text("test.skip(!email, 'no accounts');\n"),
         "weakened-test", "test.skip(!email"),
        (lambda r: (r / "api-tests" / "tests" / "test_route.py").write_text("pytestmark = pytest.mark.xfail\n"),
         "weakened-test", "pytest.mark.xfail"),
    ],
)
def test_forbidden_or_weakened_opens_no_pr(run, merged, change, reason, shown):
    change(merged)
    agent_cases.check("PM-1234", merged, kind="tests", tools=no_problems)
    assert run.result == {"status": "error", "reason": reason, "pr_url": ""}
    assert shown in run.summary and run.output == "go=false\n"


def test_existing_skips_are_not_blamed_on_the_agent(run, merged):
    old = merged / "ui-tests" / "tests" / "old.spec.ts"
    old.write_text("test.skip(!email, 'no accounts');\n")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "existing guard"], cwd=merged, check=True)
    old.write_text("test.skip(!email, 'no accounts');\ntest('new', async () => {});\n")
    assert agent_cases.check("PM-1234", merged, kind="tests", tools=no_problems) == 0
    assert run.output == "go=true\n"


@pytest.mark.parametrize(
    "change, problem",
    [
        (lambda r: (r / "README.md").write_text("x"), "unexpected change: README.md"),
        (lambda r: (r / "flows" / "inventory.yaml").write_text(INVENTORY + "#\n"), "no test was written"),
        (lambda r: (r / "cases" / "PM-1234.md").write_text(GOOD + "\n"), "unexpected change: cases/PM-1234.md"),
    ],
)
def test_other_changes_are_invalid(run, merged, change, problem):
    change(merged)
    agent_cases.check("PM-1234", merged, kind="tests", tools=no_problems)
    assert run.result["reason"] == "invalid-output" and problem in run.summary


def test_failing_tools_are_invalid(run, merged):
    (merged / "api-tests" / "tests" / "test_route.py").write_text(NEW_TEST)
    agent_cases.check("PM-1234", merged, kind="tests", tools=lambda root: ["type check failed: error TS2304"])
    assert run.result["reason"] == "invalid-output" and "type check failed: error TS2304" in run.summary


def test_tests_pr_body(merged):
    (merged / "api-tests" / "tests" / "test_route.py").write_text(NEW_TEST)
    (merged / "ui-tests" / "tests" / "old.spec.ts").write_text("test('old', async () => {});\ntest('new one', async () => {});\n")
    (merged / "flows" / "inventory.yaml").write_text(INVENTORY + "# mapped\n")
    title, body = agent_cases.tests_pr_body("PM-1234", merged)
    assert title == "[PM-1234] Tests: Job creation with empty route"
    assert "Tests for the merged cases in `cases/PM-1234.md` (3 tests)" in body
    assert "- `api-tests/tests/test_route.py`: 2 tests, flow `job-creation`" in body
    assert "- `ui-tests/tests/old.spec.ts`: 1 test, flow `job-creation`" in body
    assert "- `flows/inventory.yaml`: the new tests mapped to business rules" in body
    assert "UAT: **not run yet.** It runs only after a QA member reviews and starts it." in body
    assert "2. Actions → `uat-pr` → Run workflow → paste this PR's head commit SHA." in body


def test_tests_texts_point_to_the_right_command(run):
    agent_cases.agent_failed("PM-1234", "tests")
    assert "/generate-api-tests PM-1234" in run.summary and run.summary.startswith("### generate-tests")
    agent_cases.opened("PM-1234", "https://github.com/o/r/pull/4", "tests")
    assert "Next: review PR 2, then start `uat-pr` with its head commit SHA." in run.summary


def test_generate_tests_workflow_pushes_only_its_branch():
    text = (agent_cases.ROOT / ".github" / "workflows" / "generate-tests.yml").read_text()
    assert 'branch="agent/$TICKET-tests"' in text and '"HEAD:refs/heads/$branch"' in text
    assert "--kind tests" in text and "--kind cases" not in text
    assert "anthropics/claude-code-action@cab360f6565aa35a51d6ce9e43f1f4287c0a32ea" in text
    assert "secrets.UAT" not in text and "DB_PASSWORD" not in text
