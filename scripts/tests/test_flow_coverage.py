"""Tests for the coverage report, one per rule in Story 2.5."""

import json

from flow_coverage import build_report, flow_status, main

API = "api:tests/test_jobs.py::test_create"
UI = "ui:tests/jobs.spec.ts > Jobs > creates a job"


def flow(rules, flow_id="job-creation"):
    return {"id": flow_id, "rules": rules}


def entry(test_id, flow_id="job-creation", status=""):
    return {"test_id": test_id, "suite": test_id[:2], "flows": [flow_id], "status": status}


TESTS = [entry(API), entry(UI)]


def test_automated_when_every_rule_has_a_test_that_ran():
    rules = [{"id": "JOB-1", "tests": [API]}, {"id": "JOB-2", "tests": [API, UI]}]
    assert flow_status(flow(rules), TESTS, ran={API}, quarantined=set()) == []


def test_rule_without_tests_is_not_covered():
    rules = [{"id": "JOB-1", "tests": [API]}, {"id": "JOB-2", "tests": []}]
    assert flow_status(flow(rules), TESTS, ran={API}, quarantined=set()) == ["rule `JOB-2` has no test"]


def test_rule_whose_tests_did_not_run_is_not_covered():
    rules = [{"id": "JOB-1", "tests": [UI]}]
    assert flow_status(flow(rules), TESTS, ran={API}, quarantined=set()) == ["rule `JOB-1`: no mapped test ran"]


def test_quarantined_test_makes_the_flow_not_covered_even_though_it_ran():
    rules = [{"id": "JOB-1", "tests": [API]}]
    assert flow_status(flow(rules), TESTS, ran={API, UI}, quarantined={UI}) == [f"test quarantined: `{UI}`"]


def test_skipped_or_fixme_test_makes_the_flow_not_covered():
    rules = [{"id": "JOB-1", "tests": [API]}]
    tests = [entry(API), entry(UI, status="fixme")]
    assert flow_status(flow(rules), tests, ran={API}, quarantined=set()) == [f"test fixme: `{UI}`"]
    tests = [entry(API), entry(UI, status="skipped")]
    assert flow_status(flow(rules), tests, ran={API}, quarantined=set()) == [f"test skipped: `{UI}`"]


def test_mapped_test_that_no_longer_exists():
    rules = [{"id": "JOB-1", "tests": ["api:tests/gone.py::test_old", API]}]
    reasons = flow_status(flow(rules), TESTS, ran={API}, quarantined=set())
    assert reasons == ["mapped test not found: `api:tests/gone.py::test_old`"]


def test_other_flows_tests_do_not_count():
    rules = [{"id": "LOGIN-1", "tests": [API]}]
    tests = [entry(API, "login"), entry(UI, "job-creation", status="skipped")]
    assert flow_status(flow(rules, "login"), tests, ran={API}, quarantined=set()) == []


def test_report_counts_and_table():
    inventory = {"flows": [flow([{"id": "JOB-1", "tests": [API]}]), flow([{"id": "L-1", "tests": []}], "login")]}
    report = build_report(inventory, TESTS, [{"test_id": API, "status": "failed"}], set())
    assert report.startswith("### Coverage: 1 of 2 regression flows automated (50%)")
    assert "| `job-creation` | automated |  |" in report
    assert "| `login` | not covered | rule `L-1` has no test |" in report


def test_zero_flows_does_not_divide_by_zero():
    assert build_report({"flows": []}, [], [], set()).startswith("### Coverage: 0 of 0 regression flows automated (0%)")


def test_main_reads_files(tmp_path, capsys):
    (tmp_path / "inventory.yaml").write_text(f"flows:\n  - id: job-creation\n    rules:\n      - id: JOB-1\n        tests: ['{API}']\n")
    (tmp_path / "q.yaml").write_text("[]\n")
    (tmp_path / "tests.json").write_text(json.dumps(TESTS))
    (tmp_path / "results.json").write_text(json.dumps([{"test_id": API, "status": "passed"}]))
    main([
        "--inventory", str(tmp_path / "inventory.yaml"), "--quarantine", str(tmp_path / "q.yaml"),
        "--tests-json", str(tmp_path / "tests.json"), "--results-json", str(tmp_path / "results.json"),
    ])
    assert "Coverage: 1 of 1 regression flows automated (100%)" in capsys.readouterr().out
