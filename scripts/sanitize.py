#!/usr/bin/env python3
"""Sanitizer (Story 6.1): turns last night's failures into `triage-input`, the only
text the triage model may see (SEC-05, AD-13).

For each failed, quarantined or passed-on-retry test it keeps only the error
message, the stack trace and the names of the failed steps of the last failed
attempt, read from the Allure *-result.json files. Screenshots, traces, videos,
attachments and raw logs are never read. Everything kept is masked with
scripts/masking-patterns.json, then cut to size.

- No failures and no passed-on-retry tests: no file is written.
- The file is checked against contracts/triage-input.schema.json; if that fails,
  the step fails and nothing is saved. The test result is unchanged either way.

Usage:
    python scripts/sanitize.py --results-json results.json --history-dir history \\
        --allure-dir API=current/api-tests/reports/allure-results \\
        --allure-dir UI=current/ui-tests/reports/allure-results \\
        --run-id 123 --out triage-input.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

from failure_list import failures_from, load_history, with_history
from run_summary import canonical_id
from validate_contract import ContractError, validate

PATTERNS = Path(__file__).resolve().parent / "masking-patterns.json"
MAX_MESSAGE, MAX_TRACE, MAX_STEPS, MAX_STEP = 2000, 4000, 10, 200
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def load_patterns(path: Path = PATTERNS) -> list[tuple[str, re.Pattern, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        (p["name"], re.compile(p["pattern"], re.IGNORECASE if "i" in p.get("flags", "") else 0), p["replacement"])
        for p in data["patterns"]
    ]


def mask(text: str, patterns: list[tuple[str, re.Pattern, str]]) -> str:
    """Applies every pattern in order. Replacements are plain text (no backreferences)."""
    for _, pattern, replacement in patterns:
        text = pattern.sub(lambda _, r=replacement: r, text)
    return text


def clean(text: str | None, patterns, limit: int) -> str:
    """Masked first, then cut, so a secret is never split past its pattern."""
    text = mask(ANSI.sub("", text or ""), patterns).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def attempts_by_test(allure_dirs: dict[str, Path]) -> dict[str, tuple[str, list[dict]]]:
    """Every attempt of every test, by test ID (as run_summary.py works it out), oldest first."""
    found: dict[str, tuple[str, list[dict]]] = {}
    for suite, folder in allure_dirs.items():
        for path in sorted(folder.glob("*-result.json")) if folder.is_dir() else []:
            result = json.loads(path.read_text(encoding="utf-8"))
            test_id = canonical_id(result) or result.get("historyId") or result.get("testCaseId") or result.get("uuid") or path.name
            found.setdefault(test_id, (suite, []))[1].append(result)
    for _, runs in found.values():
        runs.sort(key=lambda r: r.get("stop") or r.get("start") or 0)
    return found


def failed_steps(steps: list[dict], prefix: str = "") -> list[str]:
    """Names of failed or broken steps, outermost first ("Outer > inner")."""
    names = []
    for step in steps or []:
        if step.get("status") in ("failed", "broken"):
            name = f"{prefix}{step.get('name') or '(unnamed step)'}"
            names.append(name)
            names += failed_steps(step.get("steps", []), name + " > ")
    return names


def details(runs: list[dict], patterns) -> dict:
    """The masked message, trace and failed steps of the last attempt that didn't pass."""
    failed = [r for r in runs if r.get("status") in ("failed", "broken")]
    if not failed:
        return {"message": "", "trace": "", "failed_steps": []}
    last = failed[-1]
    status = last.get("statusDetails") or {}
    return {
        "message": clean(status.get("message"), patterns, MAX_MESSAGE),
        "trace": clean(status.get("trace"), patterns, MAX_TRACE),
        "failed_steps": [clean(s, patterns, MAX_STEP) for s in failed_steps(last.get("steps", []))][:MAX_STEPS],
    }


def build(results: list[dict], allure_dirs: dict[str, Path], history_dir: Path | None, run_id: int,
          patterns=None) -> dict | None:
    failures = failures_from(results)
    if not failures:
        return None
    patterns = patterns or load_patterns()
    failures = with_history(failures, load_history(history_dir, run_id))
    attempts = attempts_by_test(allure_dirs)
    suite_of = {r["test_id"]: r.get("suite", "") for r in results}
    entries = []
    for f in failures:
        suite, runs = attempts.get(f["test_id"], (suite_of.get(f["test_id"], ""), []))
        entries.append({
            "test_id": f["test_id"],
            "flow_id": f["flow_id"],
            "suite": suite or suite_of.get(f["test_id"], ""),
            "attempts": f["attempts"],
            "history": f["history"],
            "status": f["status"],
            "flaky_candidate": f["flaky_candidate"],
            **details(runs, patterns),
        })
    return {"schema_version": 1, "nightly_run_id": run_id, "failures": entries}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the masked triage-input file from last night's failures.")
    parser.add_argument("--results-json", type=Path, required=True)
    parser.add_argument("--allure-dir", action="append", default=[], metavar="SUITE=DIR")
    parser.add_argument("--history-dir", type=Path)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    allure_dirs = {s: Path(d) for s, d in (a.split("=", 1) for a in args.allure_dir)}
    results = json.loads(args.results_json.read_text(encoding="utf-8")) if args.results_json.exists() else []
    triage_input = build(results, allure_dirs, args.history_dir, args.run_id)
    if triage_input is None:
        print("No failures and no retries: no triage-input.")
        return 0
    try:
        validate("triage-input", triage_input)
    except ContractError as e:
        print(f"triage-input is not valid, nothing saved: {e}")
        return 1
    args.out.write_text(json.dumps(triage_input, indent=2), encoding="utf-8")
    print(f"Saved triage-input with {len(triage_input['failures'])} tests (masked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
