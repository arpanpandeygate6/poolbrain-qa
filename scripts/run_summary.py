#!/usr/bin/env python3
"""Writes a test run's job summary: PASSED or FAILED, run details and counts per suite.

Counts come from each suite's Allure results. Retries of one test share a
historyId; the last attempt decides its status, and a test that passed after
a failed attempt counts as "passed on retry".

Usage (in a workflow):
    python scripts/run_summary.py --title uat-pr --outcome success \\
        --detail Commit=abc1234 --detail PR=#12 --report-url <url> \\
        --suite API=api-tests/reports/allure-results --suite UI=ui-tests/reports/allure-results

Appends to GITHUB_STEP_SUMMARY (or prints) and writes verdict=passed|failed to GITHUB_OUTPUT.
The verdict is passed only when --outcome is success, results exist and none failed.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Counts:
    passed: int = 0
    failed: int = 0
    passed_on_retry: int = 0
    skipped: int = 0


def count_results(results_dir: Path) -> Counts | None:
    """Count final outcomes in one Allure results folder, or None when it has no results."""
    attempts: dict[str, list[dict]] = {}
    for path in sorted(results_dir.glob("*-result.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        key = result.get("historyId") or result.get("testCaseId") or result.get("uuid") or path.name
        attempts.setdefault(key, []).append(result)
    if not attempts:
        return None

    counts = Counts()
    for runs in attempts.values():
        runs.sort(key=lambda r: r.get("stop") or r.get("start") or 0)
        final = runs[-1].get("status")
        if final == "passed":
            if any(r.get("status") != "passed" for r in runs[:-1]):
                counts.passed_on_retry += 1
            else:
                counts.passed += 1
        elif final == "skipped":
            counts.skipped += 1
        else:  # failed, broken or unknown
            counts.failed += 1
    return counts


def build_summary(
    title: str, outcome: str, details: list[tuple[str, str]], suites: dict[str, Counts | None], report_url: str
) -> tuple[str, str]:
    have_results = any(c is not None for c in suites.values())
    any_failed = any(c.failed for c in suites.values() if c)
    verdict = "passed" if outcome == "success" and have_results and not any_failed else "failed"

    lines = [f"## {title} — {verdict.upper()}", ""]
    if details:
        lines += ["| | |", "|---|---|", *[f"| {name} | {value} |" for name, value in details], ""]
    if have_results:
        lines += ["| Suite | Passed | Failed | Passed on retry | Skipped |", "|---|---|---|---|---|"]
        for name, c in suites.items():
            lines.append(
                f"| {name} | no results | | | |"
                if c is None
                else f"| {name} | {c.passed} | {c.failed} | {c.passed_on_retry} | {c.skipped} |"
            )
    else:
        lines.append("No test results were produced (no results). Open the run log to see why.")
    lines.append("")
    lines.append(f"[Allure report]({report_url})" if report_url else "Allure report: no results")
    return "\n".join(lines) + "\n", verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a test run's job summary.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--outcome", required=True, help="success when every test step succeeded")
    parser.add_argument("--detail", action="append", default=[], help="NAME=VALUE row for the details table")
    parser.add_argument("--suite", action="append", default=[], help="NAME=ALLURE_RESULTS_DIR")
    parser.add_argument("--report-url", default="")
    args = parser.parse_args(argv)

    details = [tuple(d.split("=", 1)) for d in args.detail]
    suites = {name: count_results(Path(path)) for name, path in (s.split("=", 1) for s in args.suite)}
    summary, verdict = build_summary(args.title, args.outcome, details, suites, args.report_url)

    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(summary)
    print(summary)
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"verdict={verdict}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
