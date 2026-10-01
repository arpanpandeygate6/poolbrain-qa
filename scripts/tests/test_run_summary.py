"""Tests for the run summary writer."""

import json

from run_summary import (
    Counts,
    RunResult,
    build_summary,
    canonical_id,
    count_results,
    load_quarantine,
    load_results,
    main,
)


def result(folder, name, status, history="h1", stop=1, **extra):
    (folder / f"{name}-result.json").write_text(json.dumps({"historyId": history, "status": status, "stop": stop, **extra}))


def pytest_labels(package):
    return [{"name": "framework", "value": "pytest"}, {"name": "package", "value": package}]


def t(test_id, status="passed", suite="API", **kw):
    return RunResult(test_id=test_id, suite=suite, status=status, attempts=1, **kw)


def test_counts_final_attempt_and_passed_on_retry(tmp_path):
    result(tmp_path, "a", "passed", "t1")
    result(tmp_path, "b1", "failed", "t2", stop=1)
    result(tmp_path, "b2", "passed", "t2", stop=2)
    result(tmp_path, "c1", "failed", "t3", stop=1)
    result(tmp_path, "c2", "broken", "t3", stop=2)
    result(tmp_path, "d", "skipped", "t4")
    assert count_results(tmp_path) == Counts(passed=1, failed=1, passed_on_retry=1, skipped=1)


def test_no_results(tmp_path):
    assert count_results(tmp_path) is None
    assert count_results(tmp_path / "missing") is None


def test_canonical_ids_from_allure_results():
    assert (
        canonical_id({"fullName": "tests.test_jobs#test_create", "labels": pytest_labels("tests.test_jobs")})
        == "api:tests/test_jobs.py::test_create"
    )
    assert (
        canonical_id({"fullName": "tests.test_jobs.TestJobs#test_create[2]", "labels": pytest_labels("tests.test_jobs")})
        == "api:tests/test_jobs.py::TestJobs::test_create"
    )
    playwright = [{"name": "framework", "value": "playwright"}]
    assert (
        canonical_id({"fullName": "sub/jobs.spec.ts › Jobs › creates a job", "labels": playwright})
        == "ui:tests/sub/jobs.spec.ts > Jobs > creates a job"
    )
    assert canonical_id({"fullName": "x", "labels": []}) == ""


def test_load_results_uses_test_ids_and_attempts(tmp_path):
    labels = pytest_labels("tests.test_jobs")
    result(tmp_path, "a1", "failed", "h", stop=1, fullName="tests.test_jobs#test_a", labels=labels)
    result(tmp_path, "a2", "passed", "h", stop=2, fullName="tests.test_jobs#test_a", labels=labels)
    [test] = load_results(tmp_path, "API")
    assert (test.test_id, test.status, test.attempts, test.passed_on_retry) == (
        "api:tests/test_jobs.py::test_a",
        "passed",
        2,
        True,
    )


def test_passed_needs_success_results_and_no_failures():
    ok = {"API": [t("a")], "UI": [t("b", suite="UI")]}
    assert build_summary("x", "success", [], ok, "u")[1] == "passed"
    assert build_summary("x", "failure", [], ok, "u")[1] == "failed"
    assert build_summary("x", "success", [], {"API": [t("a", "failed")]}, "u")[1] == "failed"
    assert build_summary("x", "success", [], {"API": []}, "u")[1] == "failed"
    assert build_summary("x", "success", [], {"API": [t("a")], "UI": []}, "u")[1] == "failed"


def test_quarantined_failure_does_not_turn_the_run_red():
    suites = {"API": [t("a"), t("q", "failed", quarantined=True)]}
    text, verdict = build_summary("nightly", "failure", [], suites, "u")
    assert verdict == "passed"
    assert "| API | 1 | 0 | 0 | 1 | 0 |" in text
    assert "| **QUARANTINED** | `q` | - |" in text


def test_failures_table_orders_and_cuts_to_ten():
    tests = [t(f"f{i:02}", "failed", flow_id="job-creation") for i in range(11)]
    tests += [t("r", passed_on_retry=True), t("q", "failed", quarantined=True)]
    text, verdict = build_summary("nightly", "failure", [], {"API": tests}, "u", ["A red nightly blocks UAT sign-off."])
    assert verdict == "failed"
    rows = [line for line in text.splitlines() if line.startswith("| **")]
    assert len(rows) == 10 and all("**FAILED**" in r for r in rows)
    assert "| **FAILED** | `f00` | job-creation |" in rows
    assert "and 3 more — see the run" in text
    assert text.rstrip().endswith("A red nightly blocks UAT sign-off.")


def test_summary_layout():
    text, _ = build_summary(
        "uat-pr", "success", [("Commit", "`abc`"), ("PR", "#7")], {"API": [t("a"), t("b")], "UI": []}, "https://x"
    )
    assert text.startswith("## uat-pr — FAILED")
    assert "| PR | #7 |" in text
    assert "| API | 2 | 0 | 0 | 0 | 0 |" in text
    assert "| UI | no results |" in text
    assert "[Allure report](https://x)" in text


def test_nothing_ran():
    text, verdict = build_summary("uat-pr", "failure", [], {"API": [], "UI": []}, "")
    assert verdict == "failed"
    assert "no results" in text and "Allure report: no results" in text


def test_load_quarantine(tmp_path):
    q = tmp_path / "quarantine.yaml"
    q.write_text("# comment\n[]\n")
    assert load_quarantine(q) == set()
    q.write_text("- test_id: api:tests/x.py::test_a\n  owner: someone\n  jira: PM-1\n  deadline: 2026-10-15\n")
    assert load_quarantine(q) == {"api:tests/x.py::test_a"}
    assert load_quarantine(tmp_path / "missing.yaml") == set()


def test_main_end_to_end(tmp_path, monkeypatch):
    results = tmp_path / "r"
    results.mkdir()
    labels = pytest_labels("tests.test_jobs")
    result(results, "a", "passed", "h1", fullName="tests.test_jobs#test_a", labels=labels)
    result(results, "b", "failed", "h2", fullName="tests.test_jobs#test_b", labels=labels)
    (tmp_path / "q.yaml").write_text("- test_id: api:tests/test_jobs.py::test_b\n")
    (tmp_path / "tests.json").write_text(
        json.dumps([{"test_id": "api:tests/test_jobs.py::test_b", "suite": "api", "flows": ["job-creation"], "status": ""}])
    )
    summary, output, records = tmp_path / "summary.md", tmp_path / "output", tmp_path / "results.json"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    main([
        "--title", "nightly", "--outcome", "failure", "--suite", f"API={results}",
        "--quarantine", str(tmp_path / "q.yaml"), "--tests-json", str(tmp_path / "tests.json"),
        "--results-json", str(records),
    ])
    assert "## nightly — PASSED" in summary.read_text()
    assert output.read_text() == "verdict=passed\n"
    saved = {r["test_id"]: r for r in json.loads(records.read_text())}
    assert saved["api:tests/test_jobs.py::test_b"]["label"] == "QUARANTINED"
    assert saved["api:tests/test_jobs.py::test_b"]["flow_id"] == "job-creation"
