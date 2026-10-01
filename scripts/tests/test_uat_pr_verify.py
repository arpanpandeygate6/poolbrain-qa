"""Tests for the uat-pr request check, against a fake GitHub."""

import pytest

from uat_pr_verify import AGENT_LOGIN, Verdict, not_run_summary, qa_team, verify

SHA = "a" * 40
OLD_SHA = "b" * 40
MAIN = "refs/heads/main"


class FakeGitHub:
    def __init__(self, team="alice\n", users=None, pulls=None, reviews=None):
        self.team = team
        self.users = users or {"alice": "User", "bob": "User", "helper-app[bot]": "Bot"}
        self.pulls = pulls if pulls is not None else {SHA: [pr()]}
        self._reviews = reviews or []

    def user_type(self, login):
        return self.users.get(login, "")

    def file_on_main(self, path):
        assert path == ".github/qa-team.txt"
        return self.team

    def pulls_for_commit(self, sha):
        return self.pulls.get(sha, [])

    def reviews(self, number):
        return self._reviews


def pr(number=7, state="open", base="main", head=SHA, author="carol"):
    return {"number": number, "state": state, "base": {"ref": base}, "head": {"sha": head}, "user": {"login": author}}


def test_qa_member_on_open_pr_head_is_accepted():
    verdict = verify(FakeGitHub(), ref=MAIN, actor="alice", sha=SHA)
    assert verdict.ok and verdict.pr["number"] == 7


def test_team_file_ignores_comments_blank_lines_and_case():
    assert qa_team("# QA team\n\nAlice\nbob  # lead\n") == {"alice", "bob"}
    assert verify(FakeGitHub(team="# team\nALICE\n"), ref=MAIN, actor="alice", sha=SHA).ok


@pytest.mark.parametrize(
    "kwargs, gh, reason",
    [
        ({"ref": "refs/heads/feature", "actor": "alice", "sha": SHA}, FakeGitHub(), "not main"),
        ({"ref": MAIN, "actor": "alice", "sha": "abc123"}, FakeGitHub(), "not a full 40-character"),
        ({"ref": MAIN, "actor": "bob", "sha": SHA}, FakeGitHub(), "bob is not listed in .github/qa-team.txt"),
        ({"ref": MAIN, "actor": "helper-app[bot]", "sha": SHA}, FakeGitHub(team="helper-app[bot]\n"), "app or bot"),
        (
            {"ref": MAIN, "actor": "alice", "sha": OLD_SHA},
            FakeGitHub(pulls={OLD_SHA: [pr(head=SHA)]}),
            "not the head of an open PR",
        ),
        ({"ref": MAIN, "actor": "alice", "sha": SHA}, FakeGitHub(pulls={SHA: [pr(state="closed")]}), "not the head"),
        ({"ref": MAIN, "actor": "alice", "sha": SHA}, FakeGitHub(pulls={SHA: [pr(base="develop")]}), "not the head"),
    ],
)
def test_rejected_requests_give_a_reason(kwargs, gh, reason):
    verdict = verify(gh, **kwargs)
    assert not verdict.ok
    assert reason in verdict.reason
    assert verdict.fix


def test_rejection_keeps_the_pr_so_a_failure_status_can_be_set():
    verdict = verify(FakeGitHub(), ref=MAIN, actor="bob", sha=SHA)
    assert not verdict.ok and verdict.pr["number"] == 7


def test_no_pr_means_no_failure_status():
    verdict = verify(FakeGitHub(pulls={}), ref=MAIN, actor="alice", sha=SHA)
    assert not verdict.ok and verdict.pr is None


def agent_review(user="alice", state="APPROVED", commit=SHA):
    return {"user": {"login": user}, "state": state, "commit_id": commit}


@pytest.mark.parametrize(
    "reviews, ok",
    [
        ([agent_review()], True),
        ([], False),
        ([agent_review(user="bob")], False),
        ([agent_review(state="COMMENTED")], False),
        ([agent_review(commit=OLD_SHA)], False),
    ],
)
def test_agent_pr_needs_the_dispatchers_approval_at_this_commit(reviews, ok):
    gh = FakeGitHub(pulls={SHA: [pr(author=AGENT_LOGIN)]}, reviews=reviews)
    verdict = verify(gh, ref=MAIN, actor="alice", sha=SHA)
    assert verdict.ok is ok
    if not ok:
        assert "has not approved it at this commit" in verdict.reason


def test_not_run_summary_wording():
    text = not_run_summary(Verdict(False, "some reason.", "do this."), SHA, "alice")
    assert text.startswith("## uat-pr — Not run")
    assert "**Why:** some reason." in text and "**How to fix:** do this." in text
