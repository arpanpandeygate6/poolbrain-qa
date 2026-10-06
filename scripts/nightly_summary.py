#!/usr/bin/env python3
"""Nightly summary (Story 7.1): one small file per nightly run for n8n's daily QA
update (W4): the verdict, counts, coverage, the failures and the quarantine
registry, and links. Saved as the artifact `nightly-summary`.

Reads run_summary.py's --results-json and the flow-tag linter's --json output
for this run (both in the nightly-results artifact). Coverage is worked out the
same way as the nightly's coverage report (scripts/flow_coverage.py).

The file is checked against contracts/nightly-summary.schema.json; if that
fails, this step fails and nothing is saved. The test result is unchanged.

Usage:
    python scripts/nightly_summary.py --results-json results.json --tests-json tests.json \\
        --run-id 123 --event schedule --started-at 2026-10-03T21:00:12Z --tests-result success \\
        --run-url URL --report-url URL --out nightly-summary.json
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from failure_list import failures_from
from flow_coverage import REPO, flow_status
from validate_contract import ContractError, validate

MAX_FAILURES = 50


def counts_of(results: list[dict]) -> dict:
    counts = {"passed": 0, "failed": 0, "passed_on_retry": 0, "quarantined": 0, "skipped": 0}
    for r in results:
        label = r.get("label", "")
        if label == "FAILED":
            counts["failed"] += 1
        elif label == "QUARANTINED":
            counts["quarantined"] += 1
        elif label == "PASSED ON RETRY":
            counts["passed_on_retry"] += 1
        elif r.get("status") == "skipped":
            counts["skipped"] += 1
        else:
            counts["passed"] += 1
    return counts


def status_of(tests_result: str, results: list[dict], counts: dict) -> str:
    """The gate's verdict. A tests job that didn't succeed is failed even when its results say otherwise."""
    if not results:
        return "not-run"
    return "passed" if tests_result == "success" and counts["failed"] == 0 else "failed"


def coverage_of(inventory: dict, tests: list[dict], results: list[dict], quarantined: set[str]) -> dict:
    flows = inventory.get("flows") or []
    ran = {r["test_id"] for r in results if r.get("status") in ("passed", "failed")}
    automated = sum(1 for flow in flows if not flow_status(flow, tests, ran, quarantined))
    return {"automated": automated, "total": len(flows)}


def build(results: list[dict], tests: list[dict], inventory: dict, quarantine: list[dict], *, run_id: int,
          event: str, started_at: str, tests_result: str, run_url: str, report_url: str, target: str = "UAT") -> dict:
    counts = counts_of(results)
    quarantine = [
        {"test_id": e["test_id"], "owner": str(e.get("owner", "")), "jira": str(e.get("jira", "")), "deadline": str(e.get("deadline", ""))}
        for e in quarantine if isinstance(e, dict) and e.get("test_id")
    ]
    return {
        "schema_version": 1,
        "nightly_run_id": run_id,
        "event": event,
        "started_at": started_at,
        "target": target,
        "status": status_of(tests_result, results, counts),
        "counts": counts,
        "coverage": coverage_of(inventory, tests, results, {e["test_id"] for e in quarantine}),
        "failures": [
            {"test_id": f["test_id"], "flow_id": f["flow_id"], "status": f["status"]} for f in failures_from(results)
        ][:MAX_FAILURES],
        "quarantine": quarantine,
        "links": {"run": run_url, "report": report_url},
    }


def _load_json(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Save the nightly-summary file for the daily QA update.")
    parser.add_argument("--results-json", type=Path, required=True)
    parser.add_argument("--tests-json", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, default=REPO / "flows" / "inventory.yaml")
    parser.add_argument("--quarantine", type=Path, default=REPO / "flows" / "quarantine.yaml")
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--started-at", required=True, help="UTC, for example 2026-10-03T21:00:12Z")
    parser.add_argument("--tests-result", required=True, help="the tests job's result: success, failure, cancelled")
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--report-url", default="")
    parser.add_argument("--target", default="UAT", help='where the tests ran: "UAT", or "pretend site" on the prototype')
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    inventory = yaml.safe_load(args.inventory.read_text(encoding="utf-8")) or {}
    quarantine = (yaml.safe_load(args.quarantine.read_text(encoding="utf-8")) if args.quarantine.exists() else None) or []
    summary = build(
        _load_json(args.results_json), _load_json(args.tests_json), inventory, quarantine,
        run_id=args.run_id, event=args.event, started_at=args.started_at, tests_result=args.tests_result,
        run_url=args.run_url, report_url=args.report_url, target=args.target,
    )
    try:
        validate("nightly-summary", summary)
    except ContractError as e:
        print(f"nightly-summary is not valid, nothing saved: {e}")
        return 1
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    c = summary["counts"]
    print(f"Saved nightly-summary: {summary['status']}, {c['passed']} passed, {c['failed']} failed, "
          f"{c['passed_on_retry']} passed on retry; coverage {summary['coverage']['automated']} of {summary['coverage']['total']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
