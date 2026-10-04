#!/usr/bin/env python3
"""The triage workflow's own decisions (Story 6.2), kept out of YAML so they are tested.

precheck     the nightly run ID must be a number.
setup-check  the Claude token must be set up (told only true/false). Triage opens
             no PR, so it needs no qa-agent app.
fetch        downloads ONLY that nightly run's `triage-input` artifact and checks it
             against its contract (an unknown schema_version is rejected). Missing:
             `blocked`, no-triage-input.
check        after the agent: reads its triage.json, downgrades `flaky` without
             rerun evidence to `unknown`, then requires every input test exactly
             once, a bug title for product defects (and only there), a valid
             contract, and an unchanged repository. Otherwise `error`.

Decisions that end the run go to $RUNNER_TEMP/agent-result.json for the last step
(agent-finish); each command writes `go=true|false` to GITHUB_OUTPUT.

Usage:
    python scripts/agent_triage.py precheck --nightly-run-id 123
    python scripts/agent_triage.py fetch --nightly-run-id 123
    python scripts/agent_triage.py check --nightly-run-id 123
Environment: GITHUB_TOKEN, GITHUB_REPOSITORY (fetch), RUNNER_TEMP, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY.
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

from agent_cases import decide, go, temp
from agent_gate import API, GitHub
from validate_contract import ContractError, validate

ROOT = Path(__file__).resolve().parent.parent
HEADER = "### triage\n\n"
LAPTOP_HINT = "A QA member can classify the failures from the failure list, or with Claude Code on a laptop."
DOWNGRADED = "Downgraded from flaky: no retry pass or earlier failure in the last 7 nights. "


def precheck(run_id: str) -> int:
    if re.fullmatch(r"[1-9][0-9]{0,19}", run_id or ""):
        return go(True)
    decide("error", "invalid-nightly-run-id", summary=f"{HEADER}Result: Failed. The nightly run ID must be a number. Nothing was done.")
    return go(False)


def setup_check() -> int:
    if os.environ.get("HAS_CLAUDE_TOKEN") == "true":
        return go(True)
    decide("error", "agent-not-set-up", summary=f"{HEADER}Result: Failed. The agent is not set up yet: the Claude token "
           "CLAUDE_CODE_OAUTH_TOKEN is missing (docs/runbook.md, Story 4.4). No model was called.\n\n" + LAPTOP_HINT)
    return go(False)


class Artifacts(GitHub):
    def triage_input(self, run_id: int) -> dict | None:
        """The run's triage-input.json, or None when the run has none."""
        listing = json.loads(self._get(f"{API}/repos/{self.repository}/actions/runs/{run_id}/artifacts?name=triage-input"))
        artifact = next((a for a in listing.get("artifacts", []) if not a.get("expired")), None)
        if not artifact:
            return None
        with zipfile.ZipFile(io.BytesIO(self._get(artifact["archive_download_url"]))) as archive:
            return json.loads(archive.read("triage-input.json"))


def fetch(run_id: int, github=None) -> int:
    github = github or Artifacts(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
    data = github.triage_input(run_id)
    if data is None:
        decide("blocked", "no-triage-input", summary=f"{HEADER}Result: Blocked. Nightly run {run_id} has no `triage-input` "
               "(it passed, it is older than 30 days, or its report job didn't finish). Nothing was classified.")
        return go(False)
    try:
        validate("triage-input", data)
        if data["nightly_run_id"] != run_id:
            raise ContractError(f"triage-input is for nightly run {data['nightly_run_id']}, not {run_id}")
    except ContractError as e:
        decide("error", "invalid-triage-input", summary=f"{HEADER}Result: Failed. {e}. Nothing was classified.")
        return go(False)
    (temp() / "triage-input.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"triage-input for nightly run {run_id}: {len(data['failures'])} failures.")
    return go(True)


def has_rerun_evidence(failure: dict) -> bool:
    """Flaky needs evidence: a retry pass tonight, or a retry pass or failure in the last 7 nights."""
    return failure.get("flaky_candidate", False) or any(
        night["result"] in ("failed", "passed-on-retry") for night in failure.get("history", []))


def finalize(triage: dict, triage_input: dict) -> tuple[dict, list[str]]:
    """The checked triage, and the problems that make it unusable."""
    inputs = {f["test_id"]: f for f in triage_input["failures"]}
    problems = []
    rows = triage.get("failures") if isinstance(triage, dict) else None
    if not isinstance(rows, list):
        return triage, ["triage.json has no 'failures' list"]
    for row in rows:
        if isinstance(row, dict) and row.get("class") == "flaky" and row.get("test_id") in inputs \
                and not has_rerun_evidence(inputs[row["test_id"]]):
            row["class"] = "unknown"
            row["evidence"] = (DOWNGRADED + str(row.get("evidence", "")))[:300]
            row.pop("bug_title", None)
    ids = [row.get("test_id") for row in rows if isinstance(row, dict)]
    problems += [f"missing: {t}" for t in inputs if t not in ids]
    problems += [f"listed {ids.count(t)} times: {t}" for t in sorted(set(ids)) if ids.count(t) > 1]
    problems += [f"not in the input: {t}" for t in sorted(set(ids)) if t not in inputs]
    triage = {"schema_version": 1, "nightly_run_id": triage_input["nightly_run_id"], "failures": rows}
    try:
        validate("triage", triage)
    except ContractError as e:
        problems.append(str(e))
    return triage, problems


def repo_changed(root: Path) -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return sorted(line[3:] for line in out.splitlines() if line.strip())


def check(root: Path = ROOT) -> int:
    triage_input = json.loads((temp() / "triage-input.json").read_text(encoding="utf-8"))
    path = temp() / "triage.json"
    problems = [f"changed a repository file: {p}" for p in repo_changed(root)]
    try:
        triage = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except json.JSONDecodeError as e:
        triage, problems = None, [*problems, f"triage.json is not valid JSON: {e}"]
    if triage is None and not problems:
        problems.append("the agent wrote no triage.json")
    if triage is not None:
        triage, more = finalize(triage, triage_input)
        problems += more
    if problems:
        decide("error", "invalid-triage", summary=f"{HEADER}Result: Failed. The classification did not pass the checks, "
               "so nothing was saved:\n\n" + "\n".join(f"- {p}" for p in problems[:20]) + f"\n\n{LAPTOP_HINT}")
        return go(False)
    path.write_text(json.dumps(triage, indent=2), encoding="utf-8")
    counts = {}
    for row in triage["failures"]:
        counts[row["class"]] = counts.get(row["class"], 0) + 1
    words = json.loads((ROOT / "contracts" / "vocabulary.json").read_text(encoding="utf-8"))["triage_class"]
    lines = [f"- {words[c]} (suggested): {n}" for c, n in sorted(counts.items())]
    decide("ok", "", summary=f"{HEADER}Classified {len(triage['failures'])} failures of nightly run "
           f"{triage['nightly_run_id']}, saved as `triage`:\n\n" + "\n".join(lines))
    return go(True)


def agent_failed() -> int:
    decide("error", "agent-failed", summary=f"{HEADER}Result: Failed. The agent step did not finish: the Claude Max limit "
           "may be reached or the token may have expired (see the step's log).\n\n" + LAPTOP_HINT)
    return go(False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="triage workflow decisions.")
    parser.add_argument("command", choices=["precheck", "setup-check", "fetch", "check", "agent-failed"])
    parser.add_argument("--nightly-run-id", default="")
    args = parser.parse_args(argv)
    if args.command == "precheck":
        return precheck(args.nightly_run_id)
    if args.command == "setup-check":
        return setup_check()
    if args.command == "fetch":
        return fetch(int(args.nightly_run_id))
    if args.command == "agent-failed":
        return agent_failed()
    return check()


if __name__ == "__main__":
    sys.exit(main())
