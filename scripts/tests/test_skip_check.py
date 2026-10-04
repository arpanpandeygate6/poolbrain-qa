"""Tests for the skip and healer check, and the healer setup (Story 4.7)."""

import json
import subprocess

import pytest

import skip_check

ROOT = skip_check.ROOT


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path):
    """A base branch with an existing UI spec (including the account guard) and an API test."""
    (tmp_path / "ui-tests" / "tests").mkdir(parents=True)
    (tmp_path / "ui-tests" / "tests" / "login.spec.ts").write_text("test.skip(!email, 'OFFICE_ADMIN_EMAIL is not set');\n")
    (tmp_path / "api-tests" / "tests").mkdir(parents=True)
    (tmp_path / "api-tests" / "tests" / "test_jobs.py").write_text("def test_jobs():\n    pass\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "switch", "-qc", "change")
    return tmp_path


def problems_after(repo, path, text):
    file = repo / path
    file.write_text(file.read_text() + text if file.exists() else text)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "change")
    return skip_check.skip_problems(skip_check.added_lines("main", repo))


@pytest.mark.parametrize(
    "path, text",
    [
        ("ui-tests/tests/login.spec.ts", "test.fixme('broken', async () => {});\n"),
        ("ui-tests/tests/login.spec.ts", "test.describe.skip('group', () => {});\n"),
        ("ui-tests/tests/new.spec.ts", "test.skip(true, 'later');\n"),
        ("api-tests/tests/test_jobs.py", "@pytest.mark.skip(reason='flaky')\ndef test_new():\n    pass\n"),
        ("api-tests/tests/test_jobs.py", "@pytest.mark.xfail\ndef test_new():\n    pass\n"),
        ("api-tests/tests/test_jobs.py", "def test_new():\n    pytest.skip('not ready')\n"),
    ],
)
def test_added_skip_without_a_jira_key_fails(git_repo, path, text):
    [problem] = problems_after(git_repo, path, text)
    assert problem.startswith(f"{path}:") and "without a Jira key" in problem


@pytest.mark.parametrize(
    "path, text",
    [
        ("ui-tests/tests/login.spec.ts", "test.fixme('broken', async () => {}); // PM-5678: total shows 0\n"),
        ("ui-tests/tests/login.spec.ts", "test.fixme(\n  'Defect PM-5678: total shows 0',\n"),
        ("api-tests/tests/test_jobs.py", "@pytest.mark.skip(reason='PM-5678 route sort is broken')\ndef test_new():\n    pass\n"),
        ("api-tests/tests/test_jobs.py", "def test_new():\n    assert 'skip' != 'fixme'\n"),
    ],
)
def test_skip_with_a_jira_key_or_no_skip_passes(git_repo, path, text):
    assert problems_after(git_repo, path, text) == []


def test_existing_skips_are_not_counted(git_repo):
    assert problems_after(git_repo, "ui-tests/tests/login.spec.ts", "test('another', async () => {});\n") == []


def test_no_workflow_may_run_the_healer(git_repo):
    assert skip_check.healer_problems(git_repo) == []
    (git_repo / ".github" / "workflows" / "heal.yml").write_text("run: npx playwright init-agents --loop=claude\n")
    [problem] = skip_check.healer_problems(git_repo)
    assert problem == ".github/workflows/heal.yml: runs the Playwright healer; healing is for laptops only, never in CI"


def test_the_repositorys_workflows_do_not_run_the_healer():
    assert skip_check.healer_problems() == []


# ---------------------------------------------------------------- the healer setup

HEALER = (ROOT / ".claude" / "agents" / "playwright-test-healer.md").read_text()


def test_healer_can_only_edit_existing_files_and_follows_the_house_rules():
    tools = next(line for line in HEALER.splitlines() if line.startswith("tools:"))
    names = [t.strip() for t in tools.removeprefix("tools:").split(",")]
    assert "Write" not in names and "Bash" not in names and "Edit" in names
    assert all(not t.startswith("mcp__") or t.startswith("mcp__playwright-test__") for t in names)
    for rule in ("Change only page objects in `ui-tests/pages/`", "Never weaken a test",
                 "Never add `test.fixme`, `test.skip` or `test.only`", "When the feature itself is broken, stop"):
        assert rule in HEALER
    assert "mark this test as test.fixme()" not in HEALER  # the generated advice that broke the house rules


def test_mcp_config_uses_the_installed_playwright_and_only_that_server_is_allowed():
    mcp = json.loads((ROOT / ".mcp.json").read_text())
    assert list(mcp["mcpServers"]) == ["playwright-test"]
    assert mcp["mcpServers"]["playwright-test"]["command"] == "ui-tests/node_modules/.bin/playwright"
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    assert settings["enabledMcpjsonServers"] == ["playwright-test"]
    assert settings["enableAllProjectMcpServers"] is False and settings["disableClaudeAiConnectors"] is True
    deny = settings["permissions"]["deny"]
    assert "mcp__*" not in deny and {"mcp__claude_ai_*", "mcp__plugin_*", "WebSearch", "WebFetch"} <= set(deny)
    assert not any(d.startswith("mcp__playwright") for d in deny)


def test_only_the_healer_was_committed():
    agents = sorted(p.name for p in (ROOT / ".claude" / "agents").glob("*.md"))
    assert agents == ["playwright-test-healer.md"]
    assert not (ROOT / "ui-tests" / "tests" / "seed.spec.ts").exists()
