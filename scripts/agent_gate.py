#!/usr/bin/env python3
"""The agent workflows' shared first and last steps (Story 4.4, AD-9, AR-11).

start: runs before any model call. Lets the run go on only when
  - the repository variable AGENT_ENABLED is exactly `true` (anything else,
    or no variable, ends the run as `disabled`), and
  - today's runs of this workflow are below its daily limit in AGENT_CAPS
    (a JSON map such as {"draft-cases": 20}); at or over the limit the run
    ends as `capped`. A missing or broken AGENT_CAPS, or no entry for this
    workflow, ends it as `error` (the job fails) with a plain reason.
  Today's runs are counted with the rule shared with n8n's "Gate: check":
  runs of this workflow created at or after 00:00 IST, excluding this run and
  runs whose run-outcome status is capped, disabled or blocked; runs still in
  progress or without an outcome count. contracts/cap-count.fixture.json tests both.
  Writes proceed=true|false to GITHUB_OUTPUT, and run-outcome.json when it stops the run.

finish: runs last, always. Writes run-outcome.json (unless `start` already did),
  from $RUNNER_TEMP/agent-result.json when a workflow step decided how the run
  ends ({"status", "reason", "pr_url"}), otherwise from its own arguments;
  checks it against contracts/run-outcome.schema.json; the workflow then uploads
  it as the artifact `run-outcome`.

Usage (in an agent workflow, see .github/actions/agent-start and agent-finish):
    python scripts/agent_gate.py start --ticket PM-1234
    python scripts/agent_gate.py finish --ticket PM-1234 --status ok [--reason R] [--pr-url URL]
Environment: AGENT_ENABLED, AGENT_CAPS, GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_RUN_ID,
GITHUB_WORKFLOW_REF, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY, RUNNER_TEMP.
"""

import argparse
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from validate_contract import CONTRACTS, ContractError, validate

IST = timedelta(hours=5, minutes=30)
EXCLUDED = {"capped", "disabled", "blocked"}
TICKET = re.compile(r"^[A-Z][A-Z0-9]+-[0-9]+$")
API = "https://api.github.com"


def ist_midnight(now: datetime) -> datetime:
    """The start of today in IST, in UTC (00:00 IST = 18:30 UTC the day before)."""
    local = now.astimezone(UTC) + IST
    return datetime(local.year, local.month, local.day, tzinfo=UTC) - IST


def count_today(runs: list[dict], now: datetime, current_run_id: int | None) -> int:
    """The shared counting rule. Each run has id, created_at and outcome (None when it has none)."""
    since = ist_midnight(now)
    return sum(
        1
        for r in runs
        if _time(r["created_at"]) >= since and r["id"] != current_run_id and r.get("outcome") not in EXCLUDED
    )


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text)


def workflow_name(workflow_ref: str) -> str:
    """'owner/repo/.github/workflows/draft-cases.yml@refs/heads/main' -> 'draft-cases'."""
    file = workflow_ref.split("@", 1)[0].rsplit("/", 1)[-1]
    return file.rsplit(".", 1)[0]


def read_cap(caps_text: str | None, workflow: str) -> tuple[int | None, str]:
    """(cap, '') or (None, plain reason) when AGENT_CAPS can't give this workflow a limit."""
    try:
        caps = json.loads(caps_text or "")
    except json.JSONDecodeError:
        return None, "AGENT_CAPS is missing or not valid JSON"
    cap = caps.get(workflow) if isinstance(caps, dict) else None
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
        return None, f"AGENT_CAPS has no daily limit for {workflow}"
    return cap, ""


class GitHub:
    def __init__(self, token: str, repository: str):
        self.token, self.repository = token, repository

    def _get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        # Not sent on to the artifact storage GitHub redirects downloads to, which rejects it.
        request.add_unredirected_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()

    def runs_since(self, workflow_file: str, since: datetime) -> list[dict]:
        created = urllib.parse.quote(f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        url = f"{API}/repos/{self.repository}/actions/workflows/{workflow_file}/runs?per_page=100&created={created}"
        return json.loads(self._get(url)).get("workflow_runs", [])

    def outcome(self, run_id: int) -> str | None:
        """The run's run-outcome status, or None when it has no (readable) run-outcome."""
        listing = json.loads(self._get(f"{API}/repos/{self.repository}/actions/runs/{run_id}/artifacts?name=run-outcome"))
        artifact = next((a for a in listing.get("artifacts", []) if not a.get("expired")), None)
        if not artifact:
            return None
        try:
            with zipfile.ZipFile(io.BytesIO(self._get(artifact["archive_download_url"]))) as archive:
                return json.loads(archive.read("run-outcome.json")).get("status")
        except (KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            return None


def todays_runs(github: GitHub, workflow_file: str, now: datetime) -> list[dict]:
    runs = github.runs_since(workflow_file, ist_midnight(now))
    return [
        {"id": r["id"], "created_at": r["created_at"],
         "outcome": github.outcome(r["id"]) if r.get("status") == "completed" else None}
        for r in runs
    ]


def outcome_file() -> Path:
    return Path(os.environ.get("RUNNER_TEMP", ".")) / "run-outcome.json"


def write_outcome(workflow: str, ticket: str, status: str, reason: str = "", pr_url: str = "") -> dict:
    outcome = {
        "schema_version": 1,
        "workflow": workflow,
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "ticket_key": ticket if TICKET.match(ticket) else "",  # an invalid key is never recorded
        "status": status,
        "reason": reason,
        **({"pr_url": pr_url} if pr_url else {}),
        "finished_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    validate("run-outcome", outcome)
    outcome_file().write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    return outcome


def _append(variable: str, text: str) -> None:
    path = os.environ.get(variable)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    elif variable == "GITHUB_STEP_SUMMARY":
        print(text)


def result_line(status: str) -> str:
    words = json.loads((CONTRACTS / "vocabulary.json").read_text(encoding="utf-8"))["run_outcome"]
    return f"Result: {words['ok' if status == 'ok' else status]}"


def start(ticket: str, github: GitHub | None = None, now: datetime | None = None) -> int:
    workflow_ref = os.environ["GITHUB_WORKFLOW_REF"]
    workflow = workflow_name(workflow_ref)
    now = now or datetime.now(UTC)

    def stop(status: str, reason: str, detail: str) -> int:
        write_outcome(workflow, ticket, status, reason)
        _append("GITHUB_STEP_SUMMARY", f"### {workflow}\n\n{result_line(status)}\n\n{detail}")
        _append("GITHUB_OUTPUT", "proceed=false")
        return 1 if status == "error" else 0

    if os.environ.get("AGENT_ENABLED") != "true":
        return stop("disabled", "agent-enabled-off",
                    "`AGENT_ENABLED` is not `true`, so nothing was done and no model was called.")

    cap, problem = read_cap(os.environ.get("AGENT_CAPS"), workflow)
    if cap is None:
        return stop("error", "caps-invalid", f"{problem}. No model was called. The QA lead sets `AGENT_CAPS`.")

    github = github or GitHub(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
    file = workflow_ref.split("@", 1)[0].rsplit("/", 1)[-1]
    count = count_today(todays_runs(github, file, now), now, int(os.environ["GITHUB_RUN_ID"]))
    if count >= cap:
        return stop("capped", "daily-cap-reached",
                    f"Today's limit of {cap} is reached: {count} runs counted since 00:00 IST. No model was called.")

    _append("GITHUB_OUTPUT", "proceed=true")
    print(f"AI work is on. {workflow}: {count} of {cap} runs used today (counted since 00:00 IST).")
    return 0


def finish(ticket: str, status: str, reason: str, pr_url: str) -> int:
    workflow = workflow_name(os.environ["GITHUB_WORKFLOW_REF"])
    decided = Path(os.environ.get("RUNNER_TEMP", ".")) / "agent-result.json"
    if outcome_file().exists():  # the first step already ended the run
        outcome = json.loads(outcome_file().read_text(encoding="utf-8"))
    else:
        if decided.exists():  # a workflow step decided how the run ends
            result = json.loads(decided.read_text(encoding="utf-8"))
            status, reason, pr_url = result["status"], result.get("reason", ""), result.get("pr_url", "")
        try:
            outcome = write_outcome(workflow, ticket, status, reason, pr_url)
        except ContractError as e:
            print(f"run-outcome is not valid: {e}")
            return 1
    _append("GITHUB_STEP_SUMMARY", f"\n{result_line(outcome['status'])}")
    print(json.dumps(outcome))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent workflows' shared first and last steps.")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("start")
    s.add_argument("--ticket", default="")
    f = sub.add_parser("finish")
    f.add_argument("--ticket", default="")
    f.add_argument("--status", required=True, choices=["ok", "blocked", "error"])
    f.add_argument("--reason", default="")
    f.add_argument("--pr-url", default="")
    args = parser.parse_args(argv)
    if args.command == "start":
        return start(args.ticket)
    return finish(args.ticket, args.status, args.reason, args.pr_url)


if __name__ == "__main__":
    sys.exit(main())
