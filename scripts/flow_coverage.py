#!/usr/bin/env python3
"""Coverage report for the nightly run (Story 2.5, FR-12): how many regression flows are automated.

A flow counts as automated only when every business rule listed for it in
flows/inventory.yaml has at least one mapped test that ran in this nightly pack,
and none of the flow's tests is skipped, fixme or quarantined (AD-7, FR-18).

Inputs: the inventory, flows/quarantine.yaml, the flow-tag linter's --json
output (every test, its flow and skip/fixme status) and run_summary.py's
--results-json output (what ran tonight).

Usage:
    python scripts/flow_coverage.py --tests-json tests.json --results-json results.json
Appends to GITHUB_STEP_SUMMARY (or prints).
"""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def flow_status(flow: dict, tests: list[dict], ran: set[str], quarantined: set[str]) -> list[str]:
    """Reasons the flow is not covered; an empty list means automated."""
    flow_id = flow["id"]
    known = {t["test_id"]: t for t in tests}
    reasons = []
    for rule in flow.get("rules") or []:
        mapped = rule.get("tests") or []
        if not mapped:
            reasons.append(f"rule `{rule['id']}` has no test")
            continue
        for test_id in mapped:
            if test_id not in known:
                reasons.append(f"mapped test not found: `{test_id}`")
        if not any(test_id in ran for test_id in mapped if test_id in known):
            reasons.append(f"rule `{rule['id']}`: no mapped test ran")
    for test in tests:
        if flow_id not in test.get("flows", []):
            continue
        if test.get("status") in ("skipped", "fixme"):
            reasons.append(f"test {test['status']}: `{test['test_id']}`")
        if test["test_id"] in quarantined:
            reasons.append(f"test quarantined: `{test['test_id']}`")
    return list(dict.fromkeys(reasons))


def build_report(inventory: dict, tests: list[dict], results: list[dict], quarantined: set[str]) -> str:
    flows = inventory.get("flows") or []
    ran = {r["test_id"] for r in results if r.get("status") in ("passed", "failed")}
    statuses = {flow["id"]: flow_status(flow, tests, ran, quarantined) for flow in flows}
    automated = sum(1 for reasons in statuses.values() if not reasons)
    total = len(flows)
    percent = f"{automated * 100 / total:.0f}%" if total else "0%"

    lines = [f"### Coverage: {automated} of {total} regression flows automated ({percent})", ""]
    if flows:
        lines += ["| Flow | Status | Why not covered |", "|---|---|---|"]
        for flow_id, reasons in statuses.items():
            status = "automated" if not reasons else "not covered"
            lines.append(f"| `{flow_id}` | {status} | {'; '.join(reasons)} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coverage of regression flows for the nightly run.")
    parser.add_argument("--inventory", type=Path, default=REPO / "flows" / "inventory.yaml")
    parser.add_argument("--quarantine", type=Path, default=REPO / "flows" / "quarantine.yaml")
    parser.add_argument("--tests-json", type=Path, required=True, help="the flow-tag linter's --json output")
    parser.add_argument("--results-json", type=Path, required=True, help="run_summary.py's --results-json output")
    args = parser.parse_args(argv)

    inventory = yaml.safe_load(args.inventory.read_text(encoding="utf-8")) or {}
    quarantine = yaml.safe_load(args.quarantine.read_text(encoding="utf-8")) if args.quarantine.exists() else []
    quarantined = {e["test_id"] for e in quarantine or [] if isinstance(e, dict) and e.get("test_id")}
    tests = json.loads(args.tests_json.read_text(encoding="utf-8"))
    results = json.loads(args.results_json.read_text(encoding="utf-8")) if args.results_json.exists() else []

    report = build_report(inventory, tests, results, quarantined)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(report)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
