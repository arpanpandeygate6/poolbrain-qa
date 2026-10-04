"""Tests for the contract validator."""

import copy
import json

import pytest

from validate_contract import CONTRACTS, ContractError, main, validate

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
