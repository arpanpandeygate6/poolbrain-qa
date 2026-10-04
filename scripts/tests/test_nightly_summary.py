"""Tests for the nightly summary (Story 7.1)."""

import json

import pytest

from nightly_summary import build, main
from validate_contract import validate

INVENTORY = {"flows": [
    {"id": "login", "rules": [{"id": "LOGIN-1", "tests": ["api:tests/test_login.py::test_login"]}]},
    {"id": "job-creation", "rules": [{"id": "JOB-1", "tests": ["api:tests/test_jobs.py::test_create"]}]},
]}
TESTS = [
    {"test_id": "api:tests/test_login.py::test_login", "flows": ["login"], "status": ""},
    {"test_id": "api:tests/test_jobs.py::test_create", "flows": ["job-creation"], "status": ""},
]


def result(test, status, label=""):
    return {"test_id": f"api:tests/{test}", "status": status, "label": label, "flow_id": "login", "attempts": 1}


ARGS = {"run_id": 7, "event": "schedule", "started_at": "2026-10-03T21:00:12Z", "tests_result": "success",
        "run_url": "https://github.com/o/r/actions/runs/7", "report_url": ""}


def test_passed_night():
    results = [result("test_login.py::test_login", "passed"), result("test_jobs.py::test_create", "passed")]
    summary = build(results, TESTS, INVENTORY, [], **ARGS)
    validate("nightly-summary", summary)
    assert summary["status"] == "passed"
    assert summary["counts"] == {"passed": 2, "failed": 0, "passed_on_retry": 0, "quarantined": 0, "skipped": 0}
    assert summary["coverage"] == {"automated": 2, "total": 2}
    assert summary["failures"] == [] and summary["quarantine"] == []


def test_failed_night_with_retry_and_quarantine():
    results = [
        result("test_login.py::test_login", "passed", "PASSED ON RETRY"),
        result("test_jobs.py::test_create", "failed", "QUARANTINED"),
        result("test_jobs.py::test_other", "failed", "FAILED"),
        result("test_jobs.py::test_skip", "skipped"),
    ]
    quarantine = [{"test_id": "api:tests/test_jobs.py::test_create", "owner": "ravi", "jira": "PM-5679", "deadline": "2026-10-15"}]
    summary = build(results, TESTS, INVENTORY, quarantine, **ARGS)
    validate("nightly-summary", summary)
    assert summary["status"] == "failed"
    assert summary["counts"] == {"passed": 0, "failed": 1, "passed_on_retry": 1, "quarantined": 1, "skipped": 1}
    assert summary["coverage"] == {"automated": 1, "total": 2}  # job-creation's only test is quarantined
    assert [f["status"] for f in summary["failures"]] == ["failed", "quarantined", "passed-on-retry"]
    assert summary["quarantine"] == quarantine


def test_only_quarantined_failures_pass_the_gate():
    results = [result("test_jobs.py::test_create", "failed", "QUARANTINED")]
    assert build(results, TESTS, INVENTORY, [], **ARGS)["status"] == "passed"


@pytest.mark.parametrize("tests_result", ["failure", "cancelled"])
def test_a_tests_job_that_did_not_succeed_is_failed(tests_result):
    results = [result("test_login.py::test_login", "passed")]
    assert build(results, TESTS, INVENTORY, [], **{**ARGS, "tests_result": tests_result})["status"] == "failed"


def test_no_results_is_not_run():
    summary = build([], TESTS, INVENTORY, [], **ARGS)
    validate("nightly-summary", summary)
    assert summary["status"] == "not-run" and summary["coverage"] == {"automated": 0, "total": 2}


def test_failures_are_capped_at_50():
    results = [result(f"test_jobs.py::test_{i:03d}", "failed", "FAILED") for i in range(60)]
    summary = build(results, TESTS, INVENTORY, [], **{**ARGS, "tests_result": "failure"})
    assert len(summary["failures"]) == 50 and summary["counts"]["failed"] == 60
    validate("nightly-summary", summary)


def write(path, data):
    path.write_text(json.dumps(data))
    return str(path)


def test_main_saves_and_rejects(tmp_path, capsys):
    results = write(tmp_path / "results.json", [result("test_login.py::test_login", "passed")])
    tests = write(tmp_path / "tests.json", TESTS)
    out = tmp_path / "nightly-summary.json"
    common = ["--results-json", results, "--tests-json", tests, "--run-id", "7", "--started-at", "2026-10-03T21:00:12Z",
              "--tests-result", "success", "--run-url", "https://github.com/o/r/actions/runs/7", "--out", str(out)]
    assert main(common + ["--event", "schedule"]) == 0
    assert json.loads(out.read_text())["status"] == "passed"
    assert "Saved nightly-summary: passed" in capsys.readouterr().out
    out.unlink()
    assert main(common + ["--event", "pull_request"]) == 1
    assert not out.exists()
    assert "nightly-summary is not valid, nothing saved" in capsys.readouterr().out
