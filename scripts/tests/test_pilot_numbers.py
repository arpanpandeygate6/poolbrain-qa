"""Tests for the pilot numbers (Story 8.1)."""

import json

import pytest

import pilot_numbers

START, END = "2026-10-12", "2026-10-25"


def pr(number, branch, state="closed", merged=True, labels=(), created="2026-10-13T05:00:00Z"):
    return {"number": number, "html_url": f"https://github.com/o/r/pull/{number}", "head": {"ref": branch}, "state": state,
            "merged_at": "2026-10-14T05:00:00Z" if merged and state == "closed" else None,
            "labels": [{"name": n} for n in labels], "created_at": created}


def test_acceptance_counts_agent_prs_in_the_pilot():
    prs = [
        pr(1, "agent/PM-1-cases"),
        pr(2, "agent/PM-1-tests", labels=["major-edits"]),
        pr(3, "agent/PM-2-cases", merged=False),
        pr(4, "agent/PM-3-cases", state="open"),
        pr(5, "agent/PM-4-tests"),
        pr(6, "story-4.7-healer"),  # not the agent's
        pr(7, "agent/PM-9-quarantine"),  # not PR 1 or PR 2
        pr(8, "agent/PM-5-cases", created="2026-10-02T05:00:00Z"),  # before the pilot
    ]
    m = pilot_numbers.acceptance(prs, START, END)
    assert m.value == 50.0 and m.met == "not met"
    assert m.counted[0] == "2 accepted without major edits, 1 with major edits, 1 rejected, of 4"
    assert m.listed == ["[#4](https://github.com/o/r/pull/4) `agent/PM-3-cases`: still open, not counted"]
    assert any("#3" in c and "rejected" in c for c in m.counted)


def test_acceptance_without_prs_is_no_data():
    assert pilot_numbers.acceptance([], START, END).met == "no data"


def decision(test, cls, reaction, run=7):
    return {"nightly_run_id": run, "test_id": test, "suggested_class": cls, "final_reaction": reaction}


def test_triage_agreement_rules():
    decisions = [
        decision("t1", "product_defect", "bug"),
        decision("t2", "flaky", "flaky"),
        decision("t3", "environment", "bug"),  # disagree
        decision("t4", "product_defect", "ignore"),  # 🙈 never matches
        decision("t5", "test_defect", None),  # QA marked agree
        decision("t6", "unknown", "environment"),  # QA marked disagree
        decision("t7", "unknown", None),  # no mark: listed
        decision("t8", "", "bug"),  # unclassified: listed
        decision("t9", "environment", None),  # no reaction: listed
    ]
    marks = [{"nightly_run_id": "7", "test_id": "t5", "agree": "yes"}, {"nightly_run_id": "7", "test_id": "t6", "agree": "no"}]
    m = pilot_numbers.agreement(decisions, marks)
    assert m.counted[0] == "3 of 6 agree" and m.value == 50.0
    assert len(m.listed) == 3
    assert any("t7" in item and "without a QA mark" in item for item in m.listed)
    assert any("t8" in item and "unclassified" in item for item in m.listed)
    assert any("t9" in item and "no reaction" in item for item in m.listed)


def test_time_saved():
    rows = [
        {"date": "2026-10-01", "recorder": "asha", "phase": "baseline", "minutes": "120"},
        {"date": "2026-10-05", "recorder": "asha", "phase": "baseline", "minutes": "100"},
        {"date": "2026-10-14", "recorder": "ravi", "phase": "pilot", "minutes": "40"},
        {"date": "2026-10-20", "recorder": "ravi", "phase": "pilot", "minutes": "60"},
        {"date": "2026-10-30", "recorder": "ravi", "phase": "pilot", "minutes": "200"},  # after the pilot
    ]
    m = pilot_numbers.time_saved(rows, START, END)
    assert m.value == 54.5 and m.met == "met"
    assert m.counted == ["baseline: 2 runs, 110 min average; pilot: 2 runs, 50 min average"]
    assert pilot_numbers.time_saved(rows[:2], START, END).met == "no data"


@pytest.fixture
def pilot_dir(tmp_path):
    d = tmp_path / "pilot"
    d.mkdir()
    (d / "pilot.yaml").write_text(f'start: "{START}"\nend: "{END}"\nmajor_edit_rule: "label major-edits"\nagreed_by: "QA lead"\n')
    (d / "manual-time.csv").write_text("date,recorder,phase,minutes,note\n2026-10-01,asha,baseline,100,\n2026-10-14,ravi,pilot,30,\n")
    (d / "triage-marks.csv").write_text("nightly_run_id,test_id,agree,marked_by,note\n")
    (d / "gaps.csv").write_text("from,to,what\n2026-10-15,2026-10-16,n8n down (Mac asleep)\n")
    (d / "decisions.json").write_text(json.dumps([decision("t1", "flaky", "flaky")]))
    return d


def test_report(pilot_dir, tmp_path, capsys):
    prs = tmp_path / "prs.json"
    prs.write_text(json.dumps([pr(1, "agent/PM-1-cases")]))
    out = tmp_path / "report.md"
    assert pilot_numbers.main(["--pilot-dir", str(pilot_dir), "--prs", str(prs), "--out", str(out)]) == 0
    text = out.read_text()
    assert text.startswith(f"# Pilot numbers: {START} to {END}")
    assert "| Cases and tests accepted without major edits | 100.0% | 70% or more | **met** |" in text
    assert "| Triage agreement | 100.0% | 80% or more | **met** |" in text
    assert "| Manual regression time saved on job creation | 70.0% | 50% or more | **met** |" in text
    assert "- 2026-10-15 to 2026-10-16: n8n down (Mac asleep)" in text


def test_dates_must_be_set_first(pilot_dir, capsys):
    (pilot_dir / "pilot.yaml").write_text('start: ""\nend: ""\n')
    assert pilot_numbers.main(["--pilot-dir", str(pilot_dir)]) == 1
    assert "needs the start and end dates" in capsys.readouterr().out


def test_the_repositorys_sheet_is_ready_to_fill():
    root = pilot_numbers.Path(__file__).resolve().parents[2] / "pilot"
    for name, header in (("manual-time.csv", "date,recorder,phase,minutes,note"),
                         ("triage-marks.csv", "nightly_run_id,test_id,agree,marked_by,note"), ("gaps.csv", "from,to,what")):
        assert (root / name).read_text().splitlines()[0] == header
