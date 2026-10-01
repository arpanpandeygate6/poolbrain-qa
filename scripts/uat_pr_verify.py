#!/usr/bin/env python3
"""Checks a "Run UAT tests" (uat-pr) request before any test runs (Story 1.5, AD-3).

Accepts the request only when all hold:
- the workflow runs from main, so this check is the one on main;
- the person who started it is listed in .github/qa-team.txt on main;
- that person is a person, not an app or bot;
- the commit SHA is the head of an open PR to main;
- for a PR opened by the qa-agent app, that person approved the PR at this commit.

Runs in GitHub Actions with the default workflow token only. On success it
writes `pr_number` to GITHUB_OUTPUT. On failure it writes "## uat-pr — Not run"
with the reason to the job summary, sets the `uat-pr` commit status to failure
when the SHA is the head of an open PR, and exits 1.
"""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

STATUS_CONTEXT = "uat-pr"
AGENT_LOGIN = "qa-agent[bot]"
QA_TEAM_FILE = ".github/qa-team.txt"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class GitHub:
    """Minimal GitHub REST client for one repository."""

    def __init__(self, repo: str, token: str, api_url: str = "https://api.github.com"):
        self.repo_url = f"{api_url.rstrip('/')}/repos/{repo}"
        self.api_url = api_url.rstrip("/")
        self.token = token

    def _request(self, method: str, url: str, body: dict | None = None):
        request = urllib.request.Request(
            url,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or "null")

    def user_type(self, login: str) -> str:
        return self._request("GET", f"{self.api_url}/users/{login}").get("type", "")

    def file_on_main(self, path: str) -> str:
        try:
            data = self._request("GET", f"{self.repo_url}/contents/{path}?ref=main")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            raise
        return base64.b64decode(data["content"]).decode("utf-8")

    def pulls_for_commit(self, sha: str) -> list[dict]:
        return self._request("GET", f"{self.repo_url}/commits/{sha}/pulls?per_page=100")

    def reviews(self, pr_number: int) -> list[dict]:
        return self._request("GET", f"{self.repo_url}/pulls/{pr_number}/reviews?per_page=100")

    def set_status(self, sha: str, state: str, description: str, target_url: str) -> None:
        body = {"state": state, "context": STATUS_CONTEXT, "description": description[:140], "target_url": target_url}
        self._request("POST", f"{self.repo_url}/statuses/{sha}", body)


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    fix: str = ""
    pr: dict | None = None  # the open PR whose head is the SHA, when there is one


def qa_team(text: str) -> set[str]:
    """GitHub usernames from qa-team.txt: one per line, '#' starts a comment."""
    names = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return {name.lower() for name in names if name}


def find_open_pr(gh: GitHub, sha: str) -> dict | None:
    for pr in gh.pulls_for_commit(sha):
        if pr["state"] == "open" and pr["base"]["ref"] == "main" and pr["head"]["sha"] == sha:
            return pr
    return None


def verify(gh: GitHub, *, ref: str, actor: str, sha: str) -> Verdict:
    if ref != "refs/heads/main":
        return Verdict(
            False,
            f"the workflow was started from {ref.removeprefix('refs/heads/')}, not main.",
            "In the Run workflow form, keep 'Use workflow from' set to main.",
        )
    if not FULL_SHA.match(sha):
        return Verdict(
            False,
            f"'{sha}' is not a full 40-character commit SHA.",
            "Copy the full SHA of the PR's latest commit from the PR's Commits tab.",
        )

    pr = find_open_pr(gh, sha)
    if actor.endswith("[bot]") or gh.user_type(actor) != "User":
        return Verdict(False, f"{actor} is an app or bot; only a person can start uat-pr.", "Ask a QA member.", pr)
    if actor.lower() not in qa_team(gh.file_on_main(QA_TEAM_FILE)):
        return Verdict(
            False,
            f"{actor} is not listed in {QA_TEAM_FILE} on main.",
            f"Ask a QA member to start it. To join the QA team, open a PR that adds you to {QA_TEAM_FILE}.",
            pr,
        )
    if not pr:
        return Verdict(
            False,
            "this commit is not the head of an open PR. Start it again with the current head SHA.",
            "Copy the SHA of the PR's latest commit from the PR's Commits tab.",
        )
    if pr["user"]["login"] == AGENT_LOGIN:
        approved = any(
            review["user"]["login"].lower() == actor.lower()
            and review["state"] == "APPROVED"
            and review["commit_id"] == sha
            for review in gh.reviews(pr["number"])
        )
        if not approved:
            return Verdict(
                False,
                f"this PR was opened by the agent and {actor} has not approved it at this commit.",
                "Review the PR, approve it at this commit, then start uat-pr again.",
                pr,
            )
    return Verdict(True, pr=pr)


def not_run_summary(verdict: Verdict, sha: str, actor: str) -> str:
    return (
        "## uat-pr — Not run\n\n"
        f"**Why:** {verdict.reason}\n\n"
        f"**How to fix:** {verdict.fix}\n\n"
        f"Commit: `{sha}` · Started by: @{actor}\n"
    )


def _append(env_name: str, text: str) -> None:
    path = os.environ.get(env_name)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def main() -> int:
    env = os.environ
    gh = GitHub(env["GITHUB_REPOSITORY"], env["GITHUB_TOKEN"], env.get("GITHUB_API_URL", "https://api.github.com"))
    sha = env.get("COMMIT_SHA", "").strip().lower()
    actor = env["GITHUB_TRIGGERING_ACTOR"]
    run_url = f"{env['GITHUB_SERVER_URL']}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"

    verdict = verify(gh, ref=env["GITHUB_REF"], actor=actor, sha=sha)
    if verdict.ok:
        _append("GITHUB_OUTPUT", f"pr_number={verdict.pr['number']}\n")
        print(f"Accepted: {actor} may run UAT tests for PR #{verdict.pr['number']} at {sha}.")
        return 0

    summary = not_run_summary(verdict, sha, actor)
    _append("GITHUB_STEP_SUMMARY", summary)
    print(summary)
    if verdict.pr:
        gh.set_status(sha, "failure", f"Not run: {verdict.reason}", run_url)
    return 1


if __name__ == "__main__":
    sys.exit(main())
