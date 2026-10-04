#!/usr/bin/env python3
"""The quarantine workflow's decisions and its one change (Story 6.5).

precheck   the request (JSON) must follow contracts/quarantine-request and name the
           same Jira key as the workflow's input; an unknown schema_version or
           anything else invalid ends the run `error`.
repo       the test already in flows/quarantine.yaml: `ok`, already-quarantined;
           an open PR on agent/<KEY>-quarantine: `ok`, already-open; otherwise go.
setup-check  the qa-agent app must be set up (told only true/false). No model is
           called: the change is four lines, so this script writes it.
add        adds the entry (test_id, owner, jira, deadline) to flows/quarantine.yaml,
           keeping the file's comments, and nothing else.
pr-body    the Quarantine PR body (G3) to --out; the title is printed.
opened     records the opened PR.

Decisions that end the run go to $RUNNER_TEMP/agent-result.json for the last step
(agent-finish); each command writes `go=true|false` to GITHUB_OUTPUT.

Usage: python scripts/agent_quarantine.py <command> --request-file request.json [--out body.md] [--pr-url URL]
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import yaml

from agent_cases import decide, go, open_pr
from validate_contract import ContractError, validate

ROOT = Path(__file__).resolve().parent.parent
QUARANTINE = Path("flows") / "quarantine.yaml"
HEADER = "### quarantine\n\n"


def load_request(path: Path) -> tuple[dict | None, str]:
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
        validate("quarantine-request", request)
    except (json.JSONDecodeError, ContractError) as e:
        return None, str(e)
    return request, ""


def precheck(path: Path, jira_key: str) -> int:
    request, problem = load_request(path)
    if request is not None and request["jira_key"] != jira_key:
        request, problem = None, f"its jira_key {request['jira_key']} does not match the jira_key input"
    if request is None:
        decide("error", "invalid-request", summary=f"{HEADER}Result: Failed. The quarantine request is not valid: {problem}")
        return go(False)
    return go(True)


def quarantined(root: Path = ROOT) -> set[str]:
    entries = yaml.safe_load((root / QUARANTINE).read_text(encoding="utf-8")) or []
    return {e["test_id"] for e in entries if isinstance(e, dict) and e.get("test_id")}


def repo_check(request: dict, root: Path = ROOT, find_pr=open_pr) -> int:
    if request["test_id"] in quarantined(root):
        decide("ok", "already-quarantined", summary=f"{HEADER}Result: Done. `{request['test_id']}` is already in "
               "`flows/quarantine.yaml`. No PR was opened.")
        return go(False)
    if url := find_pr(f"agent/{request['jira_key']}-quarantine"):
        decide("ok", "already-open", url, f"{HEADER}Result: Done. The quarantine PR is already open: {url}")
        return go(False)
    return go(True)


def setup_check() -> int:
    missing = [name for name, env in (("the qa-agent app ID QA_AGENT_APP_ID", "HAS_APP_ID"),
                                      ("the qa-agent private key QA_AGENT_PRIVATE_KEY", "HAS_APP_KEY"))
               if os.environ.get(env) != "true"]
    if missing:
        decide("error", "agent-not-set-up", summary=f"{HEADER}Result: Failed. The agent is not set up yet: "
               + "; ".join(missing) + " missing (docs/runbook.md, Story 4.4). Nothing was changed.")
        return go(False)
    return go(True)


def add_entry(request: dict, root: Path = ROOT) -> None:
    """Append the entry, keeping the header comments. Values are quoted as JSON strings (valid YAML)."""
    path = root / QUARANTINE
    text = path.read_text(encoding="utf-8")
    entry = "".join([
        f"- test_id: {json.dumps(request['test_id'], ensure_ascii=False)}\n",
        f"  owner: {json.dumps(request['owner'], ensure_ascii=False)}\n",
        f"  jira: {request['jira_key']}\n",
        f"  deadline: \"{request['deadline']}\"\n",
    ])
    lines = text.splitlines(keepends=True)
    body = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if [line.strip() for line in body] == ["[]"]:  # the empty list: replace it with the first entry
        index = next(i for i, line in enumerate(lines) if line.strip() == "[]")
        lines[index] = entry
        text = "".join(lines)
    else:
        text = text if text.endswith("\n") else text + "\n"
        text += entry
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, list) or request["test_id"] not in {e.get("test_id") for e in parsed if isinstance(e, dict)}:
        raise ValueError("flows/quarantine.yaml would not be a valid list with the new entry")
    path.write_text(text, encoding="utf-8")


def pr_body(request: dict) -> tuple[str, str]:
    deadline = date.fromisoformat(request["deadline"]).strftime("%d %b %Y").lstrip("0")
    links = [f"Jira {request['jira_key']}"]
    if request.get("slack_thread"):
        links.append(f"[Slack thread]({request['slack_thread']})")
    if request.get("run_url"):
        links.append(f"[Run]({request['run_url']})")
    body = f"""## Summary
{request['rerun_evidence']} A QA member ({request['marked_by']}) marked it Flaky.

## What changed
- `flows/quarantine.yaml`: `{request['test_id']}`, owner {request['owner']}, Jira {request['jira_key']}, deadline {deadline}

## What happens after merge
The test still runs every night but no longer blocks the gate. Its flow counts as not covered until it is fixed.

## What the reviewer must do
1. Confirm the owner (default from the flow inventory).
2. Merge. Until then, the test keeps gating.

## Links
{" · ".join(links)}
"""
    return f"[{request['jira_key']}] Quarantine: {request['test_id']}"[:200], body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="quarantine workflow decisions.")
    parser.add_argument("command", choices=["precheck", "repo", "setup-check", "add", "pr-body", "opened"])
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--jira-key", default="", help="precheck: the workflow's jira_key input")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--pr-url", default="")
    args = parser.parse_args(argv)
    if args.command == "precheck":
        return precheck(args.request_file, args.jira_key)
    request, _ = load_request(args.request_file)
    if args.command == "repo":
        return repo_check(request)
    if args.command == "setup-check":
        return setup_check()
    if args.command == "add":
        add_entry(request)
        return 0
    if args.command == "opened":
        decide("ok", "", args.pr_url, f"{HEADER}Opened the quarantine PR for `{request['test_id']}`: {args.pr_url}\n\n"
               "Next: confirm the owner and merge it. Until then, the test keeps gating.")
        return go(True)
    title, body = pr_body(request)
    args.out.write_text(body, encoding="utf-8")
    print(title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
