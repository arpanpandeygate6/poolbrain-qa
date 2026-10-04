import getpass
import os
import re


def run_id() -> str:
    """The GitHub run ID in CI, or local-<user> on a laptop."""
    if os.getenv("GITHUB_RUN_ID"):
        return os.environ["GITHUB_RUN_ID"]
    user = re.sub(r"[^a-z0-9]+", "-", getpass.getuser().lower()).strip("-") or "user"
    return f"local-{user}"


def qa_auto_name(name: str) -> str:
    """Name for data a test creates: qa-auto-<run-id>-<name> (AR-13), so it can be found and cleaned up."""
    return f"qa-auto-{run_id()}-{name}"
