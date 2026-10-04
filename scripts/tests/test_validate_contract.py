"""Tests for the contract validator."""

import copy
import json
import re

import pytest

from validate_contract import CONTRACTS, ContractError, main, validate, validate_csv

SAMPLE = json.loads((CONTRACTS / "samples" / "failure-list.sample.json").read_text())


def test_sample_is_valid():
    validate("failure-list", copy.deepcopy(SAMPLE))


def test_all_samples_pass(capsys):
    assert main(["--samples"]) == 0
    assert "OK: failure-list.sample.json follows failure-list" in capsys.readouterr().out


def broken(change):
    data = copy.deepcopy(SAMPLE)
    change(data)
    return data


@pytest.mark.parametrize(
    "data, message",
    [
        (broken(lambda d: d.update(schema_version=2)), "unknown schema_version 2 (this contract is version 1)"),
        ({"nightly_run_id": 1, **{k: v for k, v in SAMPLE.items() if k != "nightly_run_id"}},
         "'schema_version' must be the first field"),
        (broken(lambda d: d.pop("slack_ts")), "'slack_ts' is a required property"),
        (broken(lambda d: d.update(slack_ts="not-a-ts")), "at slack_ts"),
        (broken(lambda d: d["failures"][0].update(test_id="test_create")), "at failures/0/test_id"),
        (broken(lambda d: d["failures"][0].update(status="broken")), "at failures/0/status"),
        (broken(lambda d: d["failures"][0].update(extra=1)), "Additional properties are not allowed"),
        (broken(lambda d: d["failures"][0]["history"].extend([{"nightly_run_id": 1, "result": "passed"}] * 7)),
         "at failures/0/history"),
        (broken(lambda d: d.update(nightlyRunId=1)), "Additional properties are not allowed"),
    ],
)
def test_invalid_files_are_rejected(data, message):
    with pytest.raises(ContractError, match=message.replace("(", r"\(").replace(")", r"\)")):
        validate("failure-list", data)


def test_unknown_contract():
    with pytest.raises(ContractError, match="no contract named 'nope'"):
        validate("nope", {"schema_version": 1})


def test_cli_reports_invalid_file(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(broken(lambda d: d.update(schema_version=9))))
    assert main(["failure-list", str(bad)]) == 1
    assert "FAILED: failure-list: unknown schema_version 9" in capsys.readouterr().out
    bad.write_text("{not json")
    assert main(["failure-list", str(bad)]) == 1


# ---------------------------------------------------------------- CSV contracts (audit-export, Story 7.2)


HEADER = "ts,actor,actor_type,action,target,link\r\n"
ROW = "2026-09-30T04:00:03Z,n8n:w4-daily-update,n8n,daily-update-posted,nightly 7,\r\n"


def test_csv_sample_and_header_only_file_are_valid():
    validate_csv("audit-export", (CONTRACTS / "samples" / "audit-export.sample.csv").read_text())
    validate_csv("audit-export", HEADER)


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "the header row must be exactly: ts,actor,actor_type,action,target,link"),
        ("ts,actor,action,actor_type,target,link\r\n", "the header row must be exactly"),
        (HEADER + "2026-09-30T04:00:03Z,n8n:w4,n8n,x,y\r\n", "line 2 has 5 fields, expected 6"),
        (HEADER + ROW.replace("2026-09-30T04:00:03Z", "2026-09-30 04:00"), "line 2, ts: '2026-09-30 04:00' does not match"),
        (HEADER + ROW.replace(",n8n,daily", ",robot,daily"), "line 2, actor_type: 'robot' is not one of"),
        (HEADER + ROW.replace("n8n:w4-daily-update", "W4"), "line 2, actor: 'W4' does not match"),
        (HEADER + ROW.replace("daily-update-posted", ""), "line 2, action"),
        (HEADER + '2026-09-30T04:00:03Z,n8n:x,n8n,a,"unclosed,\r\n', "not valid CSV"),
    ],
)
def test_csv_problems_are_named(text, message):
    with pytest.raises(ContractError, match=re.escape(message)):
        validate_csv("audit-export", text)


def test_json_contract_is_not_a_csv_contract():
    with pytest.raises(ContractError, match="failure-list: not a CSV contract"):
        validate_csv("failure-list", HEADER)
