"""Tests for the nightly failure list, with a fake Slack."""

import json

import pytest

import failure_list
from failure_list import build_message, failures_from, load_history, load_vocabulary, main, with_history

API = "api:tests/test_jobs.py::test_create"
UI = "ui:tests/jobs.spec.ts > Jobs > creates a job"
VOCAB = load_vocabulary()


def rec(test_id, status="passed", label="", attempts=1, flow="job-creation"):
    return {"test_id": test_id, "suite": "API", "status": status, "label": label, "attempts": attempts, "flow_id": flow}


RESULTS = [
    rec("api:tests/test_ok.py::test_ok"),
    rec(API, "failed", "FAILED", 2),
    rec(UI, "passed", "PASSED ON RETRY", 2),
    rec("api:tests/test_q.py::test_q", "failed", "QUARANTINED", 2, "login"),
]


def test_parametrized_cases_become_one_entry_per_test():
    # Test IDs leave out [parameter], so these are three cases of one test.
    cases = [rec(API, "failed", "FAILED", 2), rec(API, "failed", "FAILED", 3), rec(API, "passed", "PASSED ON RETRY", 2),
             rec(UI, "passed", "PASSED ON RETRY", 2), rec(UI, "passed", "PASSED ON RETRY", 2)]
    entries = failures_from(cases)
    assert [(e["test_id"], e["status"], e.get("cases"), e["attempts"], e["flaky_candidate"]) for e in entries] == [
        (API, "failed", 2, 3, False),
        (UI, "passed-on-retry", 2, 2, True),
    ]
    assert "cases" not in failures_from([rec(API, "failed", "FAILED", 2)])[0]
    _, blocks = build_message(load_vocabulary(), with_history(entries, []), "d", "", "", False)
    assert f"*FAILED*  `{API}`  (flow `job-creation`, 2 cases)" in blocks[1]["text"]["text"]


def test_header_names_where_the_tests_ran():
    _, blocks = build_message(load_vocabulary(), with_history(failures_from(RESULTS), []), "d", "", "", False, "pretend site")
    assert blocks[0]["text"]["text"] == "Nightly run failed: 2 tests (pretend site, d)"


def test_failures_from_picks_and_orders():
    entries = failures_from(RESULTS)
    assert [(e["test_id"], e["status"], e["flaky_candidate"]) for e in entries] == [
        (API, "failed", False),
        ("api:tests/test_q.py::test_q", "quarantined", False),
        (UI, "passed-on-retry", True),
    ]


def write_history(folder, runs):
    """runs: list of (run_id, created_at, records)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.json").write_text(json.dumps([{"id": i, "created_at": c} for i, c, _ in runs]))
    for run_id, _, records in runs:
        (folder / str(run_id)).mkdir()
        (folder / str(run_id) / "results.json").write_text(json.dumps(records))


def test_history_is_newest_first_capped_at_seven_and_marks_not_run(tmp_path):
    runs = [(100 + n, f"2026-09-{20 + n:02}T21:00:00Z", [rec(API, "failed", "FAILED")] if n % 2 else [rec(API)])
            for n in range(9)]
    runs.append((999, "2026-10-01T21:00:00Z", []))  # the current run is skipped
    runs.append((50, "2026-09-01T21:00:00Z", [rec(UI, "skipped")]))
    write_history(tmp_path, runs)
    nights = load_history(tmp_path, current_run_id=999)
    assert [run_id for run_id, _ in nights] == [108, 107, 106, 105, 104, 103, 102]
    [entry] = with_history([{"test_id": API}], nights)
    assert entry["history"][:3] == [
        {"nightly_run_id": 108, "result": "passed"},
        {"nightly_run_id": 107, "result": "failed"},
        {"nightly_run_id": 106, "result": "passed"},
    ]
    [ui] = with_history([{"test_id": UI}], nights)
    assert {h["result"] for h in ui["history"]} == {"not-run"}


def test_no_history_folder_means_empty_history(tmp_path):
    assert load_history(None, 1) == [] and load_history(tmp_path / "missing", 1) == []


def test_message_layout_uses_the_vocabulary():
    text, blocks = build_message(VOCAB, failures_from(RESULTS), "02 Oct 02:30 IST", "https://run", "https://allure", False)
    assert blocks[0]["text"]["text"] == "Nightly run failed: 2 tests (UAT, 02 Oct 02:30 IST)"
    body = blocks[1]["text"]["text"]
    assert f"*FAILED*  `{API}`  (flow `job-creation`)" in body
    assert "*QUARANTINED*  `api:tests/test_q.py::test_q`  (flow `login`)" in body
    assert f"Passed on retry:\n*PASSED ON RETRY*  `{UI}`" in body
    assert "classifying" not in body
    assert blocks[-1]["elements"][0]["text"] == "<https://run|Run> · <https://allure|Allure report>"
    assert text == "Nightly run failed: 2 tests (UAT, 02 Oct 02:30 IST). Check the run and the Allure report."


def test_triage_line_only_when_live():
    _, blocks = build_message(VOCAB, failures_from(RESULTS), "d", "", "", True)
    assert blocks[1]["text"]["text"].endswith("The agent is classifying these. Results appear in this thread.")


def test_long_lists_are_cut_to_ten():
    many = [rec(f"api:tests/t.py::test_{i:02}", "failed", "FAILED") for i in range(13)]
    _, blocks = build_message(VOCAB, failures_from(many), "d", "", "", False)
    body = blocks[1]["text"]["text"].splitlines()
    assert sum("*FAILED*" in line for line in body) == 10
    assert body[-1] == "and 3 more — see the run"


def test_retry_only_header():
    _, blocks = build_message(VOCAB, failures_from([rec(UI, "passed", "PASSED ON RETRY", 2)]), "d", "", "", False)
    assert blocks[0]["text"]["text"] == "Nightly run passed with 1 test passed on retry (UAT, d)"


@pytest.fixture
def results_file(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(json.dumps(RESULTS))
    return path


def run(tmp_path, results_file, *extra):
    out = tmp_path / "failure-list.json"
    code = main(["--results-json", str(results_file), "--run-id", "555", "--date", "d", "--out", str(out), *extra])
    return code, out


def test_nothing_posted_when_all_passed(tmp_path, monkeypatch, capsys):
    path = tmp_path / "ok.json"
    path.write_text(json.dumps([rec(API)]))
    monkeypatch.setattr(failure_list, "post_to_slack", lambda *a: pytest.fail("must not post"))
    code, out = run(tmp_path, path)
    assert code == 0 and not out.exists()
    assert "nothing posted" in capsys.readouterr().out


def test_without_slack_shows_a_preview_and_saves_nothing(tmp_path, results_file, monkeypatch, capsys):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    code, out = run(tmp_path, results_file)
    assert code == 0 and not out.exists()
    printed = capsys.readouterr().out
    assert "Slack is not set up yet" in printed and "> Nightly run failed: 2 tests" in printed


def test_posts_validates_and_saves(tmp_path, results_file, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL", "#qa")
    posted = []
    monkeypatch.setattr(failure_list, "post_to_slack", lambda *a: posted.append(a) or ("C123", "1790900000.000100"))
    code, out = run(tmp_path, results_file)
    assert code == 0 and len(posted) == 1
    saved = json.loads(out.read_text())
    assert next(iter(saved)) == "schema_version"
    assert (saved["nightly_run_id"], saved["slack_channel"], saved["slack_ts"]) == (555, "C123", "1790900000.000100")
    assert [f["status"] for f in saved["failures"]] == ["failed", "quarantined", "passed-on-retry"]


def test_slack_failure_fails_the_job_and_saves_nothing(tmp_path, results_file, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL", "#qa")

    def refuse(*a):
        raise RuntimeError("Slack refused the message: channel_not_found")

    monkeypatch.setattr(failure_list, "post_to_slack", refuse)
    code, out = run(tmp_path, results_file)
    assert code == 1 and not out.exists()
    assert "channel_not_found" in capsys.readouterr().out


def test_invalid_list_fails_the_job(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([rec("not-a-test-id", "failed", "FAILED")]))
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL", "#qa")
    monkeypatch.setattr(failure_list, "post_to_slack", lambda *a: ("C1", "1.2"))
    code, out = run(tmp_path, bad)
    assert code == 1 and not out.exists()
    assert "INVALID" in capsys.readouterr().out
