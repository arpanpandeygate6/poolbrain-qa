#!/usr/bin/env python3
"""Nightly failure list (Story 2.4): the plain list of last night's failures for Slack,
saved as the contracted `failure-list` file for triage (AD-5).

Reads run_summary.py's --results-json for this run, and the same file from up to 7
earlier scheduled nightly runs for each test's history. Words come from
contracts/vocabulary.json, never hard-coded here (UX-DR1).

- No failures and no passed-on-retry tests: nothing is posted.
- Slack not set up (no SLACK_BOT_TOKEN or channel): the message is shown in the job
  summary as a preview and nothing is saved, because a failure-list needs the Slack
  message's channel and ts.
- Slack post fails: the job fails with a readable reason and nothing is saved.
- Otherwise the list is validated against contracts/failure-list.schema.json, then saved.

Usage:
    python scripts/failure_list.py --results-json results.json --history-dir history \\
        --run-id 123 --run-url URL --report-url URL --date "02 Oct 02:30 IST" --out failure-list.json
Environment: SLACK_BOT_TOKEN, SLACK_CHANNEL; TRIAGE_LIVE=true adds the "agent is classifying" line.
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from validate_contract import ContractError, validate

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"
MAX_LINES = 10
HISTORY_NIGHTS = 7


def load_vocabulary(path: Path = CONTRACTS / "vocabulary.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def failures_from(results: list[dict]) -> list[dict]:
    """Failed, quarantined and passed-on-retry tests, in that order, one entry per test ID.

    Test IDs leave out a parametrized case's [parameter] (AR-19), so the cases of
    one test share an ID. They become one entry with the most serious status and
    `cases`, the number of cases with that status (only when more than one), so
    each test gets one Slack message and one decision.
    """
    status_for = {"FAILED": "failed", "QUARANTINED": "quarantined", "PASSED ON RETRY": "passed-on-retry"}
    order = list(status_for.values())
    by_test: dict[str, list[dict]] = {}
    for r in results:
        if r.get("label") in status_for:
            by_test.setdefault(r["test_id"], []).append(r)
    entries = []
    for test_id, runs in by_test.items():
        status = min((status_for[r["label"]] for r in runs), key=order.index)
        same = [r for r in runs if status_for[r["label"]] == status]
        entry = {
            "test_id": test_id,
            "flow_id": next((r.get("flow_id") for r in runs if r.get("flow_id")), ""),
            "attempts": max(max(1, int(r.get("attempts", 1))) for r in runs),
            "status": status,
            "flaky_candidate": status == "passed-on-retry",
        }
        if len(same) > 1:
            entry["cases"] = len(same)
        entries.append(entry)
    return sorted(entries, key=lambda e: (order.index(e["status"]), e["test_id"]))


def night_result(record: dict | None) -> str:
    if record is None or record.get("status") == "skipped":
        return "not-run"
    return {"FAILED": "failed", "QUARANTINED": "quarantined", "PASSED ON RETRY": "passed-on-retry"}.get(
        record.get("label", ""), "passed" if record.get("status") == "passed" else "failed"
    )


def load_history(history_dir: Path | None, current_run_id: int) -> list[tuple[int, dict[str, dict]]]:
    """Earlier nights, newest first: (run_id, results by test_id). history_dir/index.json lists the runs."""
    if not history_dir or not (history_dir / "index.json").exists():
        return []
    index = json.loads((history_dir / "index.json").read_text(encoding="utf-8"))
    nights = []
    for run in sorted(index, key=lambda r: r["created_at"], reverse=True):
        if run["id"] == current_run_id:
            continue
        path = history_dir / str(run["id"]) / "results.json"
        if path.exists():
            records = json.loads(path.read_text(encoding="utf-8"))
            nights.append((run["id"], {r["test_id"]: r for r in records}))
        if len(nights) == HISTORY_NIGHTS:
            break
    return nights


def with_history(failures: list[dict], nights: list[tuple[int, dict[str, dict]]]) -> list[dict]:
    for failure in failures:
        failure["history"] = [
            {"nightly_run_id": run_id, "result": night_result(results.get(failure["test_id"]))}
            for run_id, results in nights
        ]
    return failures


def _tests(count: int) -> str:
    return "test" if count == 1 else "tests"


def build_message(
    vocab: dict, failures: list[dict], date: str, run_url: str, report_url: str, triage_live: bool, target: str = "UAT"
) -> tuple[str, list[dict]]:
    """Slack fallback text and Block Kit blocks (EXPERIENCE.md M1 layout)."""
    words, status, msg = vocab["link_labels"], vocab["test_status"], vocab["messages"]
    failed = [f for f in failures if f["status"] in ("failed", "quarantined")]
    retried = [f for f in failures if f["status"] == "passed-on-retry"]
    if failed:
        header = msg["failure_list_header"].format(count=len(failed), tests=_tests(len(failed)), target=target, date=date)
    else:
        header = msg["retry_only_header"].format(count=len(retried), tests=_tests(len(retried)), target=target, date=date)

    word_for = {
        "failed": status["failed"],
        "quarantined": status["quarantined"],
        "passed-on-retry": status["passed_on_retry"],
    }

    def lines(items: list[dict]) -> list[str]:
        out = [
            f"*{word_for[f['status']]}*  `{f['test_id']}`  (flow `{f['flow_id'] or '-'}`"
            + (f", {f['cases']} cases)" if f.get("cases") else ")")
            for f in items[:MAX_LINES]
        ]
        if len(items) > MAX_LINES:
            out.append(msg["more_items"].format(count=len(items) - MAX_LINES))
        return out

    body = lines(failed)
    if retried:
        body += [*([""] if body else []), f"{msg['passed_on_retry_section']}:", *lines(retried)]
    if triage_live:
        body += ["", msg["triage_live_line"]]

    links = " · ".join(
        f"<{url}|{label}>" for url, label in ((run_url, words["run"]), (report_url, words["allure"])) if url
    )
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(body)}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*What to do:* {msg['failure_list_action']}"}},
    ]
    if links:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": links}]})
    return f"{header}. {msg['failure_list_action']}", blocks


def post_to_slack(token: str, channel: str, text: str, blocks: list[dict]) -> tuple[str, str]:
    """Post a top-level message; return (channel ID, message ts). Raises RuntimeError with Slack's reason."""
    request = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": channel, "text": text, "blocks": blocks, "unfurl_links": False}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            reply = json.loads(response.read())
    except OSError as e:
        raise RuntimeError(f"could not reach Slack ({e})")
    if not reply.get("ok"):
        raise RuntimeError(f"Slack refused the message: {reply.get('error', 'unknown error')}")
    return reply["channel"], reply["ts"]


def preview(text: str, blocks: list[dict]) -> str:
    parts = [b["text"]["text"] for b in blocks if b["type"] in ("header", "section")]
    parts += [e["text"] for b in blocks if b["type"] == "context" for e in b["elements"]]
    return "\n\n".join(parts)


def _summary(text: str) -> None:
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post the nightly failure list and save failure-list.json.")
    parser.add_argument("--results-json", type=Path, required=True)
    parser.add_argument("--history-dir", type=Path)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-url", default="")
    parser.add_argument("--report-url", default="")
    parser.add_argument("--date", required=True, help='for the header, for example "02 Oct 02:30 IST"')
    parser.add_argument("--target", default="UAT", help='where the tests ran, for the header: "UAT", or "pretend site" on the prototype')
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    results = json.loads(args.results_json.read_text(encoding="utf-8")) if args.results_json.exists() else []
    failures = failures_from(results)
    if not failures:
        _summary("### Failure list\n\nNo failures and no retries: nothing posted to Slack.")
        return 0

    failures = with_history(failures, load_history(args.history_dir, args.run_id))
    triage_live = os.environ.get("TRIAGE_LIVE", "").lower() == "true"
    text, blocks = build_message(load_vocabulary(), failures, args.date, args.run_url, args.report_url, triage_live, args.target)

    token, channel = os.environ.get("SLACK_BOT_TOKEN", ""), os.environ.get("SLACK_CHANNEL", "")
    if not (token and channel):
        _summary(
            "### Failure list\n\nSlack is not set up yet, so nothing was posted and no `failure-list` was saved. "
            "This is the message that would be posted:\n\n" + "\n".join("> " + line for line in preview(text, blocks).splitlines())
        )
        return 0

    try:
        channel_id, ts = post_to_slack(token, channel, text, blocks)
    except RuntimeError as e:
        _summary(f"### Failure list — NOT POSTED\n\n{e}. No `failure-list` was saved; the test result is unchanged.")
        return 1

    failure_list = {
        "schema_version": 1,
        "nightly_run_id": args.run_id,
        "slack_channel": channel_id,
        "slack_ts": ts,
        "failures": failures,
    }
    try:
        validate("failure-list", failure_list)
    except ContractError as e:
        _summary(f"### Failure list — INVALID\n\n{e}. Nothing was saved.")
        return 1
    args.out.write_text(json.dumps(failure_list, indent=2), encoding="utf-8")
    _summary(f"### Failure list\n\nPosted to Slack ({len(failures)} tests) and saved as `failure-list`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
