"""Tests for the case-file check (Story 4.2)."""

import json

import pytest

from case_lint import POINTER, find_problems, main

INVENTORY = """qa_lead: TBD
flows:
  - id: job-creation
    name: Job creation
    owner: TBD
    layers: [api, db, ui]
    rules:
      - id: JOB-1
        description: A job is saved.
        tests: []
"""

GOOD = """---
ticket: PM-1234
flows: [job-creation]
priority: high
layer: api
---

# PM-1234 — Job creation with empty route

Source: Jira PM-1234 (acceptance criteria 1–2)

## PM-1234-01 — Job is rejected without a route
Business rule: a job needs a route.
Preconditions: seeded testing company; logged in as office admin.
Steps: create a job with no route via the API.
Expected: the request is rejected with a clear error.

## PM-1234-02 — Job with a route is saved
**Business rule:** a job with a route is saved.
**Preconditions:** seeded testing company.
**Steps:**
1. Create a job with a route.
**Expected result:** the job is saved.
"""


def questions(key="PM-1234", items=()):
    return json.dumps({"schema_version": 1, "ticket": key, "questions": list(items)})


QUESTION = {"number": 1, "question": "Can a job be scheduled on a Sunday?", "about": "AC 2"}


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "inventory.yaml").write_text(INVENTORY)
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "README.md").write_text("# not a case file")
    return tmp_path


def problems(repo, text=GOOD, key="PM-1234", qs=None):
    (repo / "cases" / f"{key}.md").write_text(text)
    if qs is not False:
        (repo / "cases" / f"{key}.questions.json").write_text(qs if qs is not None else questions(key))
    return find_problems(repo / "cases", repo / "inventory.yaml")


def test_good_file_passes(repo, capsys):
    assert problems(repo) == []
    assert main(["--cases", str(repo / "cases"), "--inventory", str(repo / "inventory.yaml")]) == 0
    assert "OK: 1 case file follows the case format." in capsys.readouterr().out


def test_no_case_files_is_fine(repo):
    assert find_problems(repo / "cases", repo / "inventory.yaml") == []


@pytest.mark.parametrize(
    "change, expected",
    [
        (lambda t: t.split("---\n", 2)[2], "missing front matter"),
        (lambda t: t.replace("ticket: PM-1234", "ticket: PM-9"), "ticket 'PM-9' does not match the file name PM-1234"),
        (lambda t: t.replace("[job-creation]", "[job-create]"), "unknown flow 'job-create'"),
        (lambda t: t.replace("[job-creation]", "[]"), "'flows' must list at least one flow"),
        (lambda t: t.replace("layer: api", "layer: e2e"), "layer 'e2e' must be api, db or ui"),
        (lambda t: t.replace("priority: high", "priority: urgent"), "priority 'urgent' must be one of"),
        (lambda t: t.replace("# PM-1234 — Job", "# Job"), "the title must be '# PM-1234 — <ticket title>'"),
        (lambda t: t.replace("Source: Jira PM-1234", "From the ticket"), "needs a 'Source:' line naming PM-1234"),
        (lambda t: t.replace("## PM-1234-02", "## PM-1234-03"), "case 2 heading '## PM-1234-03 — Job with a route is saved' must start '## PM-1234-02 — '"),
        (lambda t: t.replace("Preconditions: seeded testing company; logged", "Setup: logged"), "PM-1234-01 has no 'Preconditions:' line"),
        (lambda t: t.replace("**Expected result:**", "**Result:**"), "PM-1234-02 has no 'Expected result:' line"),
        (lambda t: t.replace("layer: api", "layer: [api, ui]"), "PM-1234-01 needs a 'Layer:' line"),
        (lambda t: t.split("## PM-1234-01")[0], "has no cases"),
    ],
)
def test_problems_are_named(repo, change, expected):
    found = problems(repo, change(GOOD))
    assert any(expected in p for p in found), found


def test_layer_lines_with_several_layers(repo):
    text = GOOD.replace("layer: api", "layer: [api, ui]")
    text = text.replace("Business rule: a job needs", "Layer: api\nBusiness rule: a job needs")
    text = text.replace("**Business rule:** a job with", "**Layer:** db\n**Business rule:** a job with")
    assert problems(repo, text) == ["cases/PM-1234.md: PM-1234-02 layer 'db' is not one of the file's layers (api, ui)"]


def test_bad_yaml_and_bad_file_name(repo):
    assert "not valid YAML" in problems(repo, GOOD.replace("flows: [job-creation]", "flows: [job-creation"))[0]
    (repo / "cases" / "PM-1234.md").unlink()
    (repo / "cases" / "PM-1234.questions.json").unlink()
    assert problems(repo, GOOD, key="notes") == ["cases/notes.md: the file name must be the Jira key, for example PM-1234.md"]


def test_questions_file(repo):
    assert problems(repo, qs=False) == [
        "cases/PM-1234.questions.json: missing (write it with an empty 'questions' list when there are none)"
    ]
    assert "questions: at ticket" in problems(repo, qs=questions("pm-1"))[0]
    assert problems(repo, qs=questions("PM-1")) == ["cases/PM-1234.questions.json: ticket 'PM-1' does not match PM-1234"]
    assert problems(repo, qs=questions(items=[{**QUESTION, "number": 2}])) == [
        "cases/PM-1234.questions.json: questions must be numbered 1, 2, 3, … in order",
        f"cases/PM-1234.md: has questions, so it needs the line '{POINTER}'",
    ]
    with_pointer = GOOD.replace("(acceptance criteria 1–2)\n", f"(acceptance criteria 1–2)\n\n{POINTER}\n")
    assert problems(repo, with_pointer, qs=questions(items=[QUESTION])) == []
    assert problems(repo, with_pointer) == [f"cases/PM-1234.md: says '{POINTER}' but cases/PM-1234.questions.json has no questions"]


def test_orphan_questions_file(repo):
    (repo / "cases" / "PM-7.questions.json").write_text(questions("PM-7"))
    assert find_problems(repo / "cases", repo / "inventory.yaml") == ["cases/PM-7.questions.json: has no case file next to it"]


def test_main_reports_failures(repo, capsys):
    problems(repo, GOOD.replace("[job-creation]", "[nope]"))
    assert main(["--cases", str(repo / "cases"), "--inventory", str(repo / "inventory.yaml")]) == 1
    assert "FAILED: cases/PM-1234.md: unknown flow 'nope'" in capsys.readouterr().out
