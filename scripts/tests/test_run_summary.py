"""Tests for the run summary writer."""

import json

from run_summary import Counts, build_summary, count_results, main


def result(tmp_path, name, status, history="h1", stop=1):
    (tmp_path / f"{name}-result.json").write_text(json.dumps({"historyId": history, "status": status, "stop": stop}))


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


def test_passed_needs_success_results_and_no_failures():
    ok = {"API": Counts(passed=1), "UI": Counts(passed=1)}
    assert build_summary("uat-pr", "success", [], ok, "u")[1] == "passed"
    assert build_summary("uat-pr", "failure", [], ok, "u")[1] == "failed"
    assert build_summary("uat-pr", "success", [], {"API": Counts(failed=1)}, "u")[1] == "failed"
    assert build_summary("uat-pr", "success", [], {"API": None}, "u")[1] == "failed"


def test_summary_layout():
    text, _ = build_summary(
        "uat-pr", "success", [("Commit", "`abc`"), ("PR", "#7")], {"API": Counts(passed=2), "UI": None}, "https://x"
    )
    assert text.startswith("## uat-pr — PASSED")
    assert "| PR | #7 |" in text
    assert "| API | 2 | 0 | 0 | 0 |" in text
    assert "| UI | no results |" in text
    assert "[Allure report](https://x)" in text


def test_main_writes_summary_and_verdict(tmp_path, monkeypatch, capsys):
    results = tmp_path / "r"
    results.mkdir()
    result(results, "a", "passed")
    summary, output = tmp_path / "summary.md", tmp_path / "output"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    main(["--title", "mock-tests", "--outcome", "success", "--suite", f"API={results}"])
    assert "## mock-tests — PASSED" in summary.read_text()
    assert output.read_text() == "verdict=passed\n"


def test_nothing_ran(tmp_path):
    text, verdict = build_summary("uat-pr", "failure", [], {"API": None, "UI": None}, "")
    assert verdict == "failed"
    assert "no results" in text and "Allure report: no results" in text
