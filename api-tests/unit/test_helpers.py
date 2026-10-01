"""Unit tests for the test helpers (no PoolBrain, no database). Run: pytest unit"""

import pytest

from utils import naming
from utils.db import ReadReplica


def fake_replica(results):
    """A ReadReplica whose query() returns each item of `results` in turn (the last one repeats)."""
    replica = object.__new__(ReadReplica)
    calls = []

    def query(sql, params=None):
        calls.append(sql)
        return results[min(len(calls), len(results)) - 1]

    replica.query = query
    replica.calls = calls
    return replica


def test_wait_for_row_retries_until_the_row_appears():
    replica = fake_replica([[], [], [{"id": 7}]])
    assert replica.wait_for_row("SELECT 1", purpose="job saved", interval=0) == {"id": 7}
    assert len(replica.calls) == 3


def test_wait_for_row_fails_with_purpose_and_timeout():
    replica = fake_replica([[]])
    with pytest.raises(AssertionError, match=r"^job 42 saved: row not found on replica after 0.05 s$"):
        replica.wait_for_row("SELECT 1", purpose="job 42 saved", timeout=0.05, interval=0.01)


def test_default_timeout_comes_from_config():
    from config import REPLICA_TIMEOUTS

    assert REPLICA_TIMEOUTS["default"] == 30


@pytest.mark.parametrize("sql", ["UPDATE jobs SET name = 'x'", "DELETE FROM jobs", "  insert into jobs values (1)"])
def test_non_select_statements_are_rejected(sql):
    replica = object.__new__(ReadReplica)
    with pytest.raises(ValueError, match="only runs SELECT"):
        ReadReplica.query(replica, sql)


def test_name_in_ci_uses_the_github_run_id(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    assert naming.qa_auto_name("job") == "qa-auto-123456-job"


def test_name_on_a_laptop_uses_local_user(monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.setattr(naming.getpass, "getuser", lambda: "Arpan.Pandey")
    assert naming.qa_auto_name("job") == "qa-auto-local-arpan-pandey-job"
