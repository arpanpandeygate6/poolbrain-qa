"""Tests for the sanitizer, the masking patterns and the n8n hash check (Story 6.1)."""

import json
import shutil
import subprocess

import pytest

import check_masking_hash
from sanitize import PATTERNS, build, load_patterns, main, mask
from validate_contract import validate

RAW = json.loads(PATTERNS.read_text(encoding="utf-8"))

# One fixture per pattern: fake values that must never reach the output. A new
# pattern without a fixture here fails test_every_pattern_has_a_fixture.
FIXTURES = {
    "private-key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANfakeKEY\n-----END PRIVATE KEY-----",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJxYS11c2VyIn0.c2lnbmF0dXJlLWZha2UtMTIz",
    "known-token": "ghp_FAKEfakeFAKEfakeFAKEfake1234",
    "auth-header": "Bearer qa.fake-session_token",
    "secret-value": "password=PoolPass#2026",
    "url-credentials": "//qa_readonly:Sup3rSecret@",
    "email": "maria.lopez@sunnypools.com",
    "street-address": "4821 Coral Ridge Dr",
    "card-like-number": "4000 0566 5566 5556",
    "phone-number": "(954) 555-0199",
    "long-hex-secret": "a3f5c9e1b7d2468f0a1b2c3d4e5f60718293a4b5",
}


def test_every_pattern_has_a_fixture():
    assert {p["name"] for p in RAW["patterns"]} == set(FIXTURES)


@pytest.mark.parametrize("pattern", RAW["patterns"], ids=[p["name"] for p in RAW["patterns"]])
def test_pattern_masks_its_examples_and_keeps_safe_text(pattern):
    patterns = load_patterns()
    for example in pattern["examples"] + [FIXTURES[pattern["name"]]]:
        masked = mask(f"before {example} after", patterns)
        assert example not in masked
        assert masked.startswith("before ") and masked.endswith(" after")
    for keep in pattern.get("keeps", []):
        assert mask(keep, patterns) == keep


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_javascript_masks_exactly_like_python():
    """n8n W1 applies the same patterns in JavaScript; both must give the same text."""
    samples = [ex for p in RAW["patterns"] for ex in p["examples"] + p.get("keeps", [])] + list(FIXTURES.values())
    script = f"""
const raw = {json.dumps(RAW)};
const out = {json.dumps(samples)}.map((text) => raw.patterns.reduce(
  (t, p) => t.replace(new RegExp(p.pattern, 'g' + (p.flags || '')), () => p.replacement), text));
console.log(JSON.stringify(out));
"""
    js = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    patterns = load_patterns()
    assert js == [mask(s, patterns) for s in samples]


# ---------------------------------------------------------------- build

SECRETS = " ".join(FIXTURES.values())


def allure_result(name, status, start, message="", trace="", steps=None):
    return {
        "uuid": f"{name}-{start}",
        "historyId": f"h-{name}",
        "fullName": f"tests.test_jobs#{name}",
        "labels": [{"name": "framework", "value": "pytest"}, {"name": "package", "value": "tests.test_jobs"}],
        "status": status,
        "statusDetails": {"message": message, "trace": trace},
        "steps": steps or [],
        "attachments": [{"name": "screenshot", "source": "shot-attachment.png", "type": "image/png"}],
        "start": start,
        "stop": start + 1,
    }


def write_allure(folder, results):
    folder.mkdir(parents=True, exist_ok=True)
    for r in results:
        (folder / f"{r['uuid']}-result.json").write_text(json.dumps(r))
    (folder / "shot-attachment.png").write_bytes(b"\x89PNG secret pixels")


def results_record(name, label, attempts, status="failed"):
    return {"test_id": f"api:tests/test_jobs.py::{name}", "suite": "API", "status": status, "attempts": attempts,
            "label": label, "flow_id": "job-create"}


@pytest.fixture
def allure(tmp_path):
    folder = tmp_path / "allure"
    steps = [{"name": "Create job", "status": "failed",
              "steps": [{"name": f"Check owner {FIXTURES['email']}", "status": "failed"},
                        {"name": "Open page", "status": "passed"}]}]
    write_allure(folder, [
        allure_result("test_create_job", "failed", 1, message=f"\x1b[31mAssertionError: {SECRETS}\x1b[0m",
                      trace=f"tests/test_jobs.py:42\n    login({FIXTURES['secret-value']})\nE   {SECRETS}", steps=steps),
        allure_result("test_create_job", "failed", 5, message=f"AssertionError: owner {FIXTURES['email']} missing",
                      trace="tests/test_jobs.py:42: AssertionError", steps=steps),
        allure_result("test_list_jobs", "broken", 2, message=f"Timeout calling {FIXTURES['url-credentials']}db"),
        allure_result("test_list_jobs", "passed", 3),
        allure_result("test_fine", "passed", 4),
    ])
    return folder


def test_build_masks_everything_and_keeps_only_text(allure):
    results = [results_record("test_create_job", "FAILED", 2), results_record("test_list_jobs", "PASSED ON RETRY", 2, "passed"),
               results_record("test_fine", "", 1, "passed")]
    out = build(results, {"API": allure}, None, 99)
    validate("triage-input", out)
    text = json.dumps(out)
    for secret in FIXTURES.values():
        assert secret not in text and json.dumps(secret)[1:-1] not in text
    for leaked in ("screenshot", "shot-attachment", "PNG", "\\u001b"):
        assert leaked not in text

    first, retry = out["failures"]
    assert first["test_id"] == "api:tests/test_jobs.py::test_create_job" and first["suite"] == "API"
    # The last failed attempt is used.
    assert first["message"] == "AssertionError: owner [email] missing"
    assert first["trace"] == "tests/test_jobs.py:42: AssertionError"
    assert first["failed_steps"] == ["Create job", "Create job > Check owner [email]"]
    assert first["flaky_candidate"] is False and first["status"] == "failed" and first["history"] == []
    assert retry["flaky_candidate"] is True and retry["status"] == "passed-on-retry"
    assert retry["message"] == "Timeout calling //[hidden]@db"


def test_long_text_is_masked_before_it_is_cut(tmp_path):
    folder = tmp_path / "allure"
    write_allure(folder, [allure_result("test_create_job", "failed", 1, message="x" * 1990 + " " + FIXTURES["known-token"],
                                        trace="y" * 5000)])
    [f] = build([results_record("test_create_job", "FAILED", 1)], {"API": folder}, None, 1)["failures"]
    assert "ghp_" not in f["message"] and len(f["message"]) <= 2000
    assert len(f["trace"]) == 4000 and f["trace"].endswith("…")


def test_failure_without_allure_details_still_listed(tmp_path):
    [f] = build([results_record("test_create_job", "FAILED", 1)], {"API": tmp_path / "missing"}, None, 1)["failures"]
    assert f["message"] == "" and f["trace"] == "" and f["failed_steps"] == [] and f["suite"] == "API"


def test_no_failures_writes_nothing(tmp_path, allure, capsys):
    results = tmp_path / "results.json"
    results.write_text(json.dumps([results_record("test_fine", "", 1, "passed")]))
    out = tmp_path / "triage-input.json"
    assert main(["--results-json", str(results), "--allure-dir", f"API={allure}", "--run-id", "1", "--out", str(out)]) == 0
    assert not out.exists()
    assert "no triage-input" in capsys.readouterr().out


def test_main_saves_a_valid_file(tmp_path, allure):
    results = tmp_path / "results.json"
    results.write_text(json.dumps([results_record("test_create_job", "FAILED", 2)]))
    out = tmp_path / "triage-input.json"
    assert main(["--results-json", str(results), "--allure-dir", f"API={allure}", "--run-id", "7", "--out", str(out)]) == 0
    saved = json.loads(out.read_text())
    assert next(iter(saved)) == "schema_version" and saved["nightly_run_id"] == 7


def test_invalid_output_fails_and_saves_nothing(tmp_path, allure, capsys):
    results = tmp_path / "results.json"
    results.write_text(json.dumps([{**results_record("test_create_job", "FAILED", 2), "test_id": "not-a-test-id"}]))
    out = tmp_path / "triage-input.json"
    assert main(["--results-json", str(results), "--allure-dir", f"API={allure}", "--run-id", "7", "--out", str(out)]) == 1
    assert not out.exists()
    assert "triage-input is not valid, nothing saved" in capsys.readouterr().out


# ---------------------------------------------------------------- hash pin

def test_hash_check(tmp_path):
    patterns = tmp_path / "masking-patterns.json"
    patterns.write_text('{"patterns": []}')
    current = check_masking_hash.patterns_hash(patterns)
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "other.json").write_text("{}")
    assert check_masking_hash.check(patterns, workflows) == []
    (workflows / "w1.json").write_text(json.dumps({"jsCode": f"const MASKING_PATTERNS_SHA256 = '{current}';"}))
    assert check_masking_hash.check(patterns, workflows) == []
    patterns.write_text('{"patterns": [1]}')
    [problem] = check_masking_hash.check(patterns, workflows)
    assert problem.startswith("w1.json pins masking patterns") and "Update the copy in that workflow" in problem


def test_repository_pins_match():
    assert check_masking_hash.check() == []
