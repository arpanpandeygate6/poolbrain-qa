#!/usr/bin/env python3
"""Writes a test run's job summary: PASSED or FAILED, run details, counts per suite and failures.

Results come from each suite's Allure results. Retries of one test share a
historyId; the last attempt decides its status, and a test that passed after a
failed attempt is PASSED ON RETRY. A failing test listed in flows/quarantine.yaml
is QUARANTINED: it is reported but does not turn the run red (AD-7, NFR-03).

Usage (in a workflow):
    python scripts/run_summary.py --title nightly --outcome success \\
        --detail Commit=abc1234 --report-url <url> --quarantine flows/quarantine.yaml \\
        --tests-json tests.json --results-json results.json \\
        --suite API=api-tests/reports/allure-results --suite UI=ui-tests/reports/allure-results

--tests-json is the flow-tag linter's --json output (gives each test's flow).
--results-json writes one record per test, for the failure list and coverage.

Appends to GITHUB_STEP_SUMMARY (or prints) and writes verdict=passed|failed to GITHUB_OUTPUT.
The verdict is passed only when every suite produced results, no test failed except
quarantined ones, and the test steps succeeded (or failed only because of quarantined tests).
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

MAX_ROWS = 10
FAILED, QUARANTINED, PASSED_ON_RETRY = "FAILED", "QUARANTINED", "PASSED ON RETRY"


@dataclass
class RunResult:
    test_id: str
    suite: str
    status: str  # passed, failed or skipped (final attempt)
    attempts: int
    passed_on_retry: bool = False
    quarantined: bool = False
    flow_id: str = ""

    @property
    def label(self) -> str:
        """The status word shown in summaries, or '' for a plain pass or skip."""
        if self.status == "failed":
            return QUARANTINED if self.quarantined else FAILED
        return PASSED_ON_RETRY if self.passed_on_retry else ""


@dataclass
class Counts:
    passed: int = 0
    failed: int = 0
    passed_on_retry: int = 0
    skipped: int = 0
    quarantined: int = 0


def canonical_id(result: dict) -> str:
    """Canonical test ID (AR-19) from an Allure result, or '' when it can't be worked out."""
    labels = {label["name"]: label["value"] for label in result.get("labels", [])}
    full_name = result.get("fullName") or ""
    if labels.get("framework") == "playwright" and full_name:
        return "ui:tests/" + full_name.replace(" › ", " > ")
    if labels.get("framework") == "pytest" and "#" in full_name and labels.get("package"):
        package = labels["package"]
        module, name = full_name.split("#", 1)
        test_class = module[len(package) + 1 :] if module.startswith(package + ".") else ""
        parts = [package.replace(".", "/") + ".py", *([test_class] if test_class else []), name.split("[", 1)[0]]
        return "api:" + "::".join(parts)
    return ""


def load_results(results_dir: Path, suite: str) -> list[RunResult]:
    """One RunResult per test in an Allure results folder (empty when there are none)."""
    attempts: dict[str, list[dict]] = {}
    for path in sorted(results_dir.glob("*-result.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        key = result.get("historyId") or result.get("testCaseId") or result.get("uuid") or path.name
        attempts.setdefault(key, []).append(result)

    tests = []
    for key, runs in attempts.items():
        runs.sort(key=lambda r: r.get("stop") or r.get("start") or 0)
        final = runs[-1].get("status")
        status = "passed" if final == "passed" else "skipped" if final == "skipped" else "failed"
        tests.append(
            RunResult(
                test_id=canonical_id(runs[-1]) or key,
                suite=suite,
                status=status,
                attempts=len(runs),
                passed_on_retry=status == "passed" and any(r.get("status") != "passed" for r in runs[:-1]),
            )
        )
    return tests


def count(tests: list[RunResult]) -> Counts:
    counts = Counts()
    for test in tests:
        if test.status == "failed":
            if test.quarantined:
                counts.quarantined += 1
            else:
                counts.failed += 1
        elif test.status == "skipped":
            counts.skipped += 1
        elif test.passed_on_retry:
            counts.passed_on_retry += 1
        else:
            counts.passed += 1
    return counts


def count_results(results_dir: Path) -> Counts | None:
    """Counts for one Allure results folder, or None when it has no results."""
    tests = load_results(results_dir, "")
    return count(tests) if tests else None


def load_quarantine(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return {entry["test_id"] for entry in entries if isinstance(entry, dict) and entry.get("test_id")}


def load_flows(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    return {r["test_id"]: r["flows"][0] for r in records if len(r.get("flows", [])) == 1}


def verdict_of(outcome: str, suites: dict[str, list[RunResult]]) -> str:
    tests = [t for results in suites.values() for t in results]
    every_suite_ran = bool(suites) and all(suites.values())
    unquarantined = [t for t in tests if t.status == "failed" and not t.quarantined]
    quarantined = [t for t in tests if t.status == "failed" and t.quarantined]
    steps_ok = outcome == "success" or bool(quarantined)
    return "passed" if every_suite_ran and not unquarantined and steps_ok else "failed"


def build_summary(
    title: str,
    outcome: str,
    details: list[tuple[str, str]],
    suites: dict[str, list[RunResult]],
    report_url: str,
    notes: list[str] = (),
    every_check: bool = False,
) -> tuple[str, str]:
    verdict = verdict_of(outcome, suites)
    lines = [f"## {title} — {verdict.upper()}", ""]
    if details:
        lines += ["| | |", "|---|---|", *[f"| {name} | {value} |" for name, value in details], ""]

    if any(suites.values()):
        lines += ["| Suite | Passed | Failed | Passed on retry | Quarantined | Skipped |", "|---|---|---|---|---|---|"]
        for name, tests in suites.items():
            if not tests:
                lines.append(f"| {name} | no results | | | | |")
                continue
            c = count(tests)
            lines.append(f"| {name} | {c.passed} | {c.failed} | {c.passed_on_retry} | {c.quarantined} | {c.skipped} |")
    else:
        lines.append("No test results were produced (no results). Open the run log to see why.")

    if every_check and any(suites.values()):
        # The smoke summary (Story 3.2): every check with its result, not only the failures.
        word = {"passed": "PASSED", "failed": "FAILED", "skipped": "SKIPPED"}
        lines += ["", "| Check | Result |", "|---|---|"]
        for t in sorted((t for ts in suites.values() for t in ts), key=lambda t: t.test_id):
            lines.append(f"| `{t.test_id}` | **{t.label or word[t.status]}** |")
        lines.append("")
        lines.append(f"[Allure report]({report_url})" if report_url else "Allure report: no results")
        lines += [f"\n{note}" for note in notes]
        return "\n".join(lines) + "\n", verdict

    order = {FAILED: 0, QUARANTINED: 1, PASSED_ON_RETRY: 2}
    flagged = sorted((t for ts in suites.values() for t in ts if t.label), key=lambda t: (order[t.label], t.test_id))
    if flagged:
        lines += ["", "| Result | Test | Flow |", "|---|---|---|"]
        lines += [f"| **{t.label}** | `{t.test_id}` | {t.flow_id or '-'} |" for t in flagged[:MAX_ROWS]]
        if len(flagged) > MAX_ROWS:
            lines.append(f"\nand {len(flagged) - MAX_ROWS} more — see the run")

    lines.append("")
    lines.append(f"[Allure report]({report_url})" if report_url else "Allure report: no results")
    lines += [f"\n{note}" for note in notes]
    return "\n".join(lines) + "\n", verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a test run's job summary.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--outcome", required=True, help="success when every test step succeeded")
    parser.add_argument("--detail", action="append", default=[], help="NAME=VALUE row for the details table")
    parser.add_argument("--suite", action="append", default=[], help="NAME=ALLURE_RESULTS_DIR")
    parser.add_argument("--report-url", default="")
    parser.add_argument("--note", action="append", default=[], help="a line added at the end")
    parser.add_argument("--quarantine", type=Path, help="flows/quarantine.yaml")
    parser.add_argument("--tests-json", type=Path, help="the flow-tag linter's --json output")
    parser.add_argument("--results-json", type=Path, help="write one record per test to this file")
    parser.add_argument("--every-check", action="store_true", help="list every test with its result (smoke)")
    args = parser.parse_args(argv)

    quarantine, flows = load_quarantine(args.quarantine), load_flows(args.tests_json)
    suites: dict[str, list[RunResult]] = {}
    for name, path in (s.split("=", 1) for s in args.suite):
        tests = load_results(Path(path), name)
        for test in tests:
            test.quarantined = test.test_id in quarantine
            test.flow_id = flows.get(test.test_id, "")
        suites[name] = tests

    details = [tuple(d.split("=", 1)) for d in args.detail]
    summary, verdict = build_summary(args.title, args.outcome, details, suites, args.report_url, args.note, args.every_check)

    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(summary)
    print(summary)
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"verdict={verdict}\n")
    if args.results_json:
        records = [{**asdict(t), "label": t.label} for tests in suites.values() for t in tests]
        args.results_json.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
