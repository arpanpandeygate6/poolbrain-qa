#!/usr/bin/env python3
"""The agent workflows' own decisions, kept out of YAML so they are tested:
draft-cases (Story 4.5, --kind cases) and generate-tests (Story 4.6, --kind tests).

precheck   before any model call. --stage key: the ticket key's format (first of
           all). --stage repo (after the kill switch and cap): for cases, whether
           they are already on main; for tests, whether the cases ARE on main
           (otherwise `blocked`, cases-not-merged); and whether the PR is already
           open (no second PR).
setup-check  whether the qa-agent app and the Claude token are set up (told
           only true/false, never the values).
check      after the agent: whether it stopped on purpose (it writes
           $RUNNER_TEMP/agent-stop.json), and that its changes pass the checks and
           stay inside what that workflow may change. For tests: no workflow file,
           no flows/quarantine.yaml, no added skip or fixme, and the flow-tag
           linter, pytest collection and the type check pass.
pr-body    the filled-in PR template (body to --out, title printed).
agent-failed / opened   record a failed agent step (with the laptop hint) or the opened PR.

Every decision that ends the run is written to $RUNNER_TEMP/agent-result.json
({"status", "reason", "pr_url"}), which the last step (agent-finish) turns into
run-outcome. Each command also writes `go=true|false` to GITHUB_OUTPUT.

Usage:
    python scripts/agent_cases.py precheck --kind cases --stage key --ticket PM-1234
    python scripts/agent_cases.py check --kind tests --ticket PM-1234
    python scripts/agent_cases.py pr-body --kind tests --ticket PM-1234 --out body.md
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

KINDS = {
    "cases": {"workflow": "draft-cases", "pr": "PR 1", "laptop": "/draft-cases"},
    "tests": {"workflow": "generate-tests", "pr": "PR 2", "laptop": "/generate-api-tests"},
}
# What generate-tests may change, and what it must never change.
TESTS_ALLOWED = re.compile(
    r"^(api-tests/tests/[\w/-]+\.py|api-tests/utils/api_client\.py|ui-tests/tests/[\w/.-]+\.spec\.ts"
    r"|ui-tests/pages/[\w/-]+\.ts|flows/inventory\.yaml)$"
)
TESTS_FORBIDDEN = re.compile(r"^(\.github/|flows/quarantine\.yaml$)")
WEAKENED = re.compile(
    r"pytest\.mark\.(skip|skipif|xfail)\b|pytest\.(skip|xfail)\(|\b(test|it|describe)(\.\w+)*\.(skip|fixme|only)\b"
)


def header(kind: str) -> str:
    return f"### {KINDS[kind]['workflow']}\n\n"


def laptop_hint(kind: str, key: str) -> str:
    return f"A QA member can run `{KINDS[kind]['laptop']} {key}` in Claude Code on a laptop instead."


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


def precheck(ticket: str, stage: str, root: Path = ROOT, find_pr=open_pr, kind: str = "cases") -> int:
    if stage == "key":
        if KEY.match(ticket):
            return go(True)
        shown = re.sub(r"[^A-Za-z0-9-]", "?", ticket[:30])
        decide("error", "invalid-ticket-key",
               summary=f"{header(kind)}Result: Failed. `{shown}` is not a Jira key like PM-1234. Nothing was done.")
        return go(False)
    on_main = (root / "cases" / f"{ticket}.md").exists()
    if kind == "cases" and on_main:
        decide("blocked", "cases-already-on-main",
               summary=f"{header(kind)}Result: Blocked. Cases for {ticket} are already on `main`. "
                       f"Change `cases/{ticket}.md` in a normal PR instead.")
        return go(False)
    if kind == "tests" and not on_main:
        decide("blocked", "cases-not-merged",
               summary=f"{header(kind)}Result: Blocked — cases for {ticket} are not merged on `main` yet. "
                       "Merge PR 1; this retries on its own after that.")
        return go(False)
    if url := find_pr(f"agent/{ticket}-{kind}"):
        decide("ok", "already-open", url, f"{header(kind)}Result: Done. {KINDS[kind]['pr']} for {ticket} is already open: {url}")
        return go(False)
    return go(True)


def setup_check(ticket: str, kind: str = "cases") -> int:
    missing = [name for name, env in (("the Claude token CLAUDE_CODE_OAUTH_TOKEN", "HAS_CLAUDE_TOKEN"),
                                      ("the qa-agent app ID QA_AGENT_APP_ID", "HAS_APP_ID"),
                                      ("the qa-agent private key QA_AGENT_PRIVATE_KEY", "HAS_APP_KEY"))
               if os.environ.get(env) != "true"]
    if missing:
        decide("error", "agent-not-set-up",
               summary=f"{header(kind)}Result: Failed. The agent is not set up yet: " + "; ".join(missing)
                       + " missing (docs/runbook.md, Story 4.4). No model was called.\n\n" + laptop_hint(kind, ticket))
        return go(False)
    return go(True)


def agent_failed(ticket: str, kind: str = "cases") -> int:
    decide("error", "agent-failed",
           summary=f"{header(kind)}Result: Failed. The agent step did not finish: the Claude Max limit may be "
                   "reached or the token may have expired (see the step's log). No PR was opened.\n\n"
                   + laptop_hint(kind, ticket))
    return go(False)


def opened(ticket: str, pr_url: str, kind: str = "cases") -> int:
    pr = KINDS[kind]["pr"]
    after = "review and merge PR 1." if kind == "cases" else "review PR 2, then start `uat-pr` with its head commit SHA."
    decide("ok", "", pr_url, f"{header(kind)}Opened {pr} for {ticket}: {pr_url}\n\nNext: {after}")
    return go(True)


def changed_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return sorted(line[3:] for line in out.splitlines() if line.strip())


def added_lines(root: Path, path: str) -> list[str]:
    """Lines the agent added to `path` (all lines of a new file)."""
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=root, capture_output=True, check=False).returncode == 0
    if not tracked:
        return (root / path).read_text(encoding="utf-8", errors="replace").splitlines()
    diff = subprocess.run(["git", "diff", "-U0", "--", path], cwd=root, capture_output=True, text=True, check=True).stdout
    return [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]


def run_tools(root: Path) -> list[str]:
    """The checks generate-tests runs on the agent's tests (no UAT: the job has no UAT access)."""
    problems = []
    for name, command, cwd in (
        ("flow tags", [sys.executable, "scripts/flow_lint.py"], root),
        ("pytest collection", [sys.executable, "-m", "pytest", "--collect-only", "-q"], root / "api-tests"),
        ("type check", ["npm", "run", "typecheck"], root / "ui-tests"),
    ):
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
            problems.append(f"{name} failed: " + " / ".join(tail))
    return problems


def check(ticket: str, root: Path = ROOT, kind: str = "cases", tools=run_tools) -> int:
    stop = temp() / "agent-stop.json"
    if stop.exists():
        data = json.loads(stop.read_text(encoding="utf-8"))
        reason = data.get("reason") if re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(data.get("reason", ""))) else "agent-stopped"
        decide("blocked", reason, summary=f"{header(kind)}Result: Blocked ({reason}). {data.get('message', '')}\n\n"
                                          + laptop_hint(kind, ticket))
        return go(False)

    changed = changed_files(root)
    if kind == "tests":
        forbidden = [p for p in changed if TESTS_FORBIDDEN.match(p)]
        weakened = [f"{p}: {line.strip()[:80]}" for p in changed if not TESTS_FORBIDDEN.match(p) and (root / p).exists()
                    for line in added_lines(root, p) if WEAKENED.search(line)]
        if forbidden or weakened:
            reason = "forbidden-change" if forbidden else "weakened-test"
            items = [f"changes {p}, which generate-tests must never change" for p in forbidden]
            items += [f"adds skip, fixme or only: {w}" for w in weakened]
            decide("error", reason, summary=f"{header(kind)}Result: Failed. No PR was opened:\n\n"
                   + "\n".join(f"- {i}" for i in items[:20]))
            return go(False)
        problems = [f"unexpected change: {p}" for p in changed if not TESTS_ALLOWED.match(p)]
        if not any(p.startswith(("api-tests/tests/", "ui-tests/tests/")) for p in changed):
            problems.append("no test was written")
        if not problems:
            problems = tools(root)
    else:
        allowed = {f"cases/{ticket}.md", f"cases/{ticket}.questions.json"}
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
        decide("error", "invalid-output", summary=f"{header(kind)}Result: Failed. The agent's output did not pass "
               "the checks, so no PR was opened:\n\n" + "\n".join(f"- {p}" for p in problems[:20]))
        return go(False)
    return go(True)


def _case_title(ticket: str, root: Path) -> tuple[str, dict]:
    text = (root / "cases" / f"{ticket}.md").read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---\n", 2)[1])
    title = re.search(rf"^# {re.escape(ticket)} — (.+)$", text, re.MULTILINE).group(1).strip()
    return title, meta


def pr_body(ticket: str, root: Path = ROOT) -> tuple[str, str]:
    """(PR title, body) from the case file, following .github/PULL_REQUEST_TEMPLATE/cases.md."""
    title, meta = _case_title(ticket, root)
    text = (root / "cases" / f"{ticket}.md").read_text(encoding="utf-8")
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


TEST_DEF = re.compile(r"^\s*(async\s+)?def (test_\w+)|^\s*test\(\s*['\"`]")


def tests_pr_body(ticket: str, root: Path = ROOT) -> tuple[str, str]:
    """(PR title, body) for PR 2, following .github/PULL_REQUEST_TEMPLATE/tests.md."""
    title, meta = _case_title(ticket, root)
    flows = ", ".join(f"`{f}`" for f in meta["flows"])
    lines = []
    total = 0
    for path in changed_files(root):
        if path.startswith(("api-tests/tests/", "ui-tests/tests/")):
            count = sum(1 for line in added_lines(root, path) if TEST_DEF.search(line))
            total += count
            lines.append(f"- `{path}`: {count} test{'s' if count != 1 else ''}, flow {flows}")
        else:
            lines.append(f"- `{path}`" + (": the new tests mapped to business rules" if path == "flows/inventory.yaml" else ""))
    body = f"""## Summary
Tests for the merged cases in `cases/{ticket}.md` ({total} test{'s' if total != 1 else ''}), by the `generate-tests` workflow.

## What changed
{chr(10).join(lines)}

## How it was checked
- `ci`: runs automatically (lint, flow tags, contracts, case files, type check).
- UAT: **not run yet.** It runs only after a QA member reviews and starts it.
- In the workflow: flow tags OK, pytest collection OK, type check OK. The new tests were not run: the workflow has no UAT access.

## Where the product differs from the cases
Not known yet: the tests have not run on UAT. `uat-pr` shows it.

## What the reviewer must do
1. Review every line. Approve the PR.
2. Actions → `uat-pr` → Run workflow → paste this PR's head commit SHA.
3. Merge when `ci` and `uat-pr` are both green on that commit.

## Links
Jira {ticket} · Case file `cases/{ticket}.md`
"""
    return f"[{ticket}] Tests: {title[:80]}", body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent workflow decisions (draft-cases, generate-tests).")
    parser.add_argument("command", choices=["precheck", "setup-check", "check", "pr-body", "agent-failed", "opened"])
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--kind", choices=list(KINDS), default="cases")
    parser.add_argument("--stage", choices=["key", "repo"], default="repo", help="precheck: which checks")
    parser.add_argument("--out", type=Path, help="pr-body: where to write the body")
    parser.add_argument("--pr-url", default="", help="opened: the new PR's link")
    args = parser.parse_args(argv)
    if args.command == "precheck":
        return precheck(args.ticket, args.stage, kind=args.kind)
    if args.command == "setup-check":
        return setup_check(args.ticket, args.kind)
    if args.command == "agent-failed":
        return agent_failed(args.ticket, args.kind)
    if args.command == "opened":
        return opened(args.ticket, args.pr_url, args.kind)
    if args.command == "check":
        return check(args.ticket, kind=args.kind)
    title, body = (pr_body if args.kind == "cases" else tests_pr_body)(args.ticket)
    args.out.write_text(body, encoding="utf-8")
    print(title)  # the workflow reads the title from here
    return 0


if __name__ == "__main__":
    sys.exit(main())
