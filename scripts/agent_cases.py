#!/usr/bin/env python3
"""The draft-cases workflow's own decisions (Story 4.5), kept out of YAML so they are tested.

precheck   before any model call. --stage key: the ticket key's format (first of
           all). --stage repo (after the kill switch and cap): whether its cases
           are already on main, and whether PR 1 is already open (no second PR).
setup-check  whether the qa-agent app and the Claude token are set up (told
           only true/false, never the values).
check      after the agent: whether it stopped on purpose (it writes
           $RUNNER_TEMP/agent-stop.json), whether the case file and questions pass
           their checks, and that it changed nothing but those two files.
pr-body    the filled-in Cases PR template (body to --out, title printed).
agent-failed / opened   record a failed agent step (with the laptop hint) or the opened PR.

Every decision that ends the run is written to $RUNNER_TEMP/agent-result.json
({"status", "reason", "pr_url"}), which the last step (agent-finish) turns into
run-outcome. Each command also writes `go=true|false` to GITHUB_OUTPUT.

Usage:
    python scripts/agent_cases.py precheck --stage key --ticket PM-1234
    python scripts/agent_cases.py check --ticket PM-1234
    python scripts/agent_cases.py pr-body --ticket PM-1234 --out body.md
Environment: GITHUB_TOKEN, GITHUB_REPOSITORY (precheck), RUNNER_TEMP, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

from case_lint import check_case_file
from flow_lint import LintError, load_inventory

ROOT = Path(__file__).resolve().parent.parent
KEY = re.compile(r"^[A-Z][A-Z0-9]+-[0-9]+$")
LAPTOP_HINT = "A QA member can run `/draft-cases {key}` in Claude Code on a laptop instead."


def temp() -> Path:
    return Path(os.environ.get("RUNNER_TEMP", "."))


def decide(status: str, reason: str, pr_url: str = "", summary: str = "") -> None:
    """Record how the run ends; agent-finish turns it into run-outcome."""
    (temp() / "agent-result.json").write_text(json.dumps({"status": status, "reason": reason, "pr_url": pr_url}))
    if summary:
        _append("GITHUB_STEP_SUMMARY", summary)


def _append(variable: str, text: str) -> None:
    if path := os.environ.get(variable):
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)


def go(value: bool) -> int:
    _append("GITHUB_OUTPUT", f"go={'true' if value else 'false'}")
    return 0


def open_pr(branch: str) -> str:
    """The URL of the open PR from `branch` into main, or ''."""
    repository = os.environ["GITHUB_REPOSITORY"]
    owner = repository.split("/")[0]
    query = urllib.parse.urlencode({"state": "open", "head": f"{owner}:{branch}", "base": "main"})
    request = urllib.request.Request(f"https://api.github.com/repos/{repository}/pulls?{query}", headers={
        "Accept": "application/vnd.github+json", "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        pulls = json.loads(response.read())
    return pulls[0]["html_url"] if pulls else ""


def precheck(ticket: str, stage: str, root: Path = ROOT, find_pr=open_pr) -> int:
    if stage == "key":
        if KEY.match(ticket):
            return go(True)
        shown = re.sub(r"[^A-Za-z0-9-]", "?", ticket[:30])
        decide("error", "invalid-ticket-key",
               summary=f"### draft-cases\n\nResult: Failed. `{shown}` is not a Jira key like PM-1234. Nothing was done.")
        return go(False)
    if (root / "cases" / f"{ticket}.md").exists():
        decide("blocked", "cases-already-on-main",
               summary=f"### draft-cases\n\nResult: Blocked. Cases for {ticket} are already on `main`. "
                       f"Change `cases/{ticket}.md` in a normal PR instead.")
        return go(False)
    if url := find_pr(f"agent/{ticket}-cases"):
        decide("ok", "already-open", url, f"### draft-cases\n\nResult: Done. PR 1 for {ticket} is already open: {url}")
        return go(False)
    return go(True)


def setup_check(ticket: str) -> int:
    missing = [name for name, env in (("the Claude token CLAUDE_CODE_OAUTH_TOKEN", "HAS_CLAUDE_TOKEN"),
                                      ("the qa-agent app ID QA_AGENT_APP_ID", "HAS_APP_ID"),
                                      ("the qa-agent private key QA_AGENT_PRIVATE_KEY", "HAS_APP_KEY"))
               if os.environ.get(env) != "true"]
    if missing:
        decide("error", "agent-not-set-up",
               summary="### draft-cases\n\nResult: Failed. The agent is not set up yet: " + "; ".join(missing)
                       + " missing (docs/runbook.md, Story 4.4). No model was called.\n\n" + LAPTOP_HINT.format(key=ticket))
        return go(False)
    return go(True)


def agent_failed(ticket: str) -> int:
    decide("error", "agent-failed",
           summary="### draft-cases\n\nResult: Failed. The agent step did not finish: the Claude Max limit may be "
                   "reached or the token may have expired (see the step's log). No PR was opened.\n\n"
                   + LAPTOP_HINT.format(key=ticket))
    return go(False)


def opened(ticket: str, pr_url: str) -> int:
    decide("ok", "", pr_url, f"### draft-cases\n\nOpened PR 1 for {ticket}: {pr_url}\n\nNext: review and merge PR 1.")
    return go(True)


def changed_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return sorted(line[3:] for line in out.splitlines() if line.strip())


def check(ticket: str, root: Path = ROOT) -> int:
    stop = temp() / "agent-stop.json"
    if stop.exists():
        data = json.loads(stop.read_text(encoding="utf-8"))
        reason = data.get("reason") if re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(data.get("reason", ""))) else "agent-stopped"
        decide("blocked", reason, summary=f"### draft-cases\n\nResult: Blocked ({reason}). {data.get('message', '')}\n\n"
                                          + LAPTOP_HINT.format(key=ticket))
        return go(False)

    allowed = {f"cases/{ticket}.md", f"cases/{ticket}.questions.json"}
    changed = changed_files(root)
    problems = [f"unexpected change: {path}" for path in changed if path not in allowed]
    case_file = root / "cases" / f"{ticket}.md"
    if not case_file.exists():
        problems.append(f"cases/{ticket}.md was not written")
    else:
        try:
            problems += check_case_file(case_file, load_inventory(root / "flows" / "inventory.yaml"))
        except LintError as e:
            problems.append(str(e))
    if problems:
        decide("error", "invalid-output", summary="### draft-cases\n\nResult: Failed. The agent's output did not pass "
               "the checks, so no PR was opened:\n\n" + "\n".join(f"- {p}" for p in problems[:20]))
        return go(False)
    return go(True)


def pr_body(ticket: str, root: Path = ROOT) -> tuple[str, str]:
    """(PR title, body) from the case file, following .github/PULL_REQUEST_TEMPLATE/cases.md."""
    text = (root / "cases" / f"{ticket}.md").read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---\n", 2)[1])
    title = re.search(rf"^# {re.escape(ticket)} — (.+)$", text, re.MULTILINE).group(1).strip()
    cases = len(re.findall(rf"^## {re.escape(ticket)}-\d+ — ", text, re.MULTILINE))
    questions = json.loads((root / "cases" / f"{ticket}.questions.json").read_text(encoding="utf-8"))["questions"]
    flows = ", ".join(f"`{f}`" for f in meta["flows"])
    body = f"""## Summary
Drafted test cases for {ticket} from its acceptance criteria, by the `draft-cases` workflow.

## What changed
- `cases/{ticket}.md`: {cases} case{'s' if cases != 1 else ''}, flows {flows}
- `cases/{ticket}.questions.json`: {len(questions)} clarification question{'s' if len(questions) != 1 else ''}

## Questions
{"Clarification questions were posted to Slack for QA approval." if questions else "None."}

## What the reviewer must do
1. Read each case. Edit this PR if something is wrong or missing.
2. Merge to accept the cases. Tests are generated only after this merge.

## Links
Jira {ticket}
"""
    return f"[{ticket}] Cases: {title[:80]}", body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="draft-cases workflow decisions.")
    parser.add_argument("command", choices=["precheck", "setup-check", "check", "pr-body", "agent-failed", "opened"])
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--stage", choices=["key", "repo"], default="repo", help="precheck: which checks")
    parser.add_argument("--out", type=Path, help="pr-body: where to write the body")
    parser.add_argument("--pr-url", default="", help="opened: the new PR's link")
    args = parser.parse_args(argv)
    if args.command == "precheck":
        return precheck(args.ticket, args.stage)
    if args.command == "setup-check":
        return setup_check(args.ticket)
    if args.command == "agent-failed":
        return agent_failed(args.ticket)
    if args.command == "opened":
        return opened(args.ticket, args.pr_url)
    if args.command == "check":
        return check(args.ticket)
    title, body = pr_body(args.ticket)
    args.out.write_text(body, encoding="utf-8")
    print(title)  # the workflow reads the title from here
    return 0


if __name__ == "__main__":
    sys.exit(main())
