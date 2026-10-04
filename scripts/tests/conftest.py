"""Fixtures shared by the agent workflow tests (draft-cases, generate-tests, triage)."""

import json
import subprocess

import pytest

from tests.test_case_lint import INVENTORY


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
