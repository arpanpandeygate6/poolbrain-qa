"""Tests for the code inside the n8n Slack and W0 workflows.

Each n8n Code node is run with Node.js against a stand-in for n8n's `$input`
and `$(...)`, so the message wording and the error cleaning are checked
without a running n8n.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / "n8n" / "workflows"
VOCABULARY = json.loads((ROOT / "contracts" / "vocabulary.json").read_text())

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")


def workflow(name: str) -> dict:
    return json.loads((WORKFLOWS / name).read_text())


def code_of(wf: dict, node_name: str) -> str:
    return next(n for n in wf["nodes"] if n["name"] == node_name)["parameters"]["jsCode"]


def run_code(code: str, input_json: dict, nodes: dict | None = None) -> list[dict]:
    """Runs one Code node's code and returns the items' json."""
    harness = f"""
const NODES = {json.dumps(nodes or {})};
const $input = {{ first: () => ({{ json: {json.dumps(input_json)} }}) }};
const $ = (name) => ({{ first: () => ({{ json: NODES[name] }}) }});
const out = (() => {{ {code} }})();
console.log(JSON.stringify(out.map((i) => i.json)));
"""
    result = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


SLACK = workflow("slack-post-message.json")
W0 = workflow("w0-error-handler.json")


def test_notice_kind_copy_matches_vocabulary():
    code = code_of(SLACK, "Build message")
    for kind, word in VOCABULARY["notice_kind"].items():
        assert f"{kind}: '{word}'" in code


def test_slack_channel_is_empty_in_the_committed_file():
    settings = next(n for n in SLACK["nodes"] if n["name"] == "Settings")
    assert settings["parameters"]["assignments"]["assignments"][0]["value"] == ""


def test_existing_workflows_report_errors_to_w0():
    for name in ("w5-heartbeat.json", "audit-record-github-runs.json"):
        assert workflow(name)["settings"]["errorWorkflow"] == W0["id"]
    for name in ("w0-error-handler.json", "slack-post-message.json", "audit-write-entry.json"):
        assert "errorWorkflow" not in workflow(name)["settings"], "W0 must not alert about its own helpers"


@needs_node
def test_build_message_follows_the_anatomy():
    message = {
        "kind": "alert",
        "header": "n8n workflow error in W5 Heartbeat",
        "body": "Step: x. Error: y.",
        "todo": "n8n maintainer, open the execution (office network only).",
        "links": [{"label": "n8n execution", "url": "http://localhost:5678/e/1"}],
        "thread_ts": "",
    }
    [out] = run_code(code_of(SLACK, "Build message"), {}, {"Message": message, "Settings": {"slack_channel": "C1"}})
    assert out["channel"] == "C1"
    assert [b["type"] for b in out["blocks"]] == ["header", "section", "section", "context"]
    assert out["blocks"][0]["text"]["text"] == "Alert: n8n workflow error in W5 Heartbeat"
    assert out["blocks"][2]["text"]["text"].startswith("*What to do:* n8n maintainer")
    assert out["blocks"][3]["elements"][0]["text"] == "<http://localhost:5678/e/1|n8n execution>"
    assert out["text"] == (
        "Alert: n8n workflow error in W5 Heartbeat. What to do: n8n maintainer, open the execution (office network only)."
    )
    assert out["preview"].splitlines()[-1] == "n8n execution: http://localhost:5678/e/1"


@needs_node
def test_build_message_without_kind_todo_or_links():
    message = {"kind": "", "header": "Daily QA update", "body": "", "todo": "", "links": [], "thread_ts": ""}
    [out] = run_code(code_of(SLACK, "Build message"), {}, {"Message": message, "Settings": {"slack_channel": ""}})
    assert out["channel"] == ""
    assert [b["type"] for b in out["blocks"]] == ["header"]
    assert out["text"] == out["preview"] == "Daily QA update"


@needs_node
@pytest.mark.parametrize(
    "reply, expected",
    [
        ({"ok": True, "channel": "C1", "ts": "1.2"}, {"posted": True, "channel": "C1", "ts": "1.2"}),
        ({"ok": False, "error": "not_in_channel"}, {"posted": False, "error": "Slack said not_in_channel"}),
    ],
)
def test_slack_reply_is_read(reply, expected):
    assert run_code(code_of(SLACK, "Posted?"), reply) == [expected]


ERROR_REPORT = {
    "execution": {
        "id": "42",
        "url": "http://localhost:5678/workflow/abc/executions/42",
        "lastNodeExecuted": "create Jira bug",
        "error": {
            "message": "Jira returned 403 for token xoxb-1234-abcd, ghp_abcdef123 and asha@gate6.com "
            "at https://x.atlassian.net/rest/api?jql=secret key " + "k" * 40 + "\n    at stack line 1",
        },
    },
    "workflow": {"id": "abc", "name": "W3b reactions"},
}


@needs_node
def test_w0_alert_is_short_and_safe():
    [out] = run_code(code_of(W0, "Describe the error"), ERROR_REPORT)
    assert out["kind"] == "alert"
    assert out["header"] == "n8n workflow error in W3b reactions"
    step, time = out["body"].split("\n")
    assert step == (
        "Step: create Jira bug. Error: Jira returned 403 for token [hidden], [hidden] and [email] "
        "at https://x.atlassian.net/rest/api key [hidden]."
    )
    assert time.startswith("Time: ") and time.endswith(" IST.")
    assert out["links"] == [{"label": "n8n execution", "url": ERROR_REPORT["execution"]["url"]}]
    assert out["target"] == "W3b reactions, step create Jira bug"
    for secret in ("xoxb", "ghp_", "asha@", "jql", "stack line"):
        assert secret not in json.dumps(out)


@needs_node
def test_w0_cuts_long_errors_and_handles_trigger_errors():
    report = {"trigger": {"error": {"message": "x " * 200, "node": {"name": "Every hour"}}},
              "workflow": {"name": "W5 Heartbeat"}}
    [out] = run_code(code_of(W0, "Describe the error"), report)
    error = out["body"].split("\n")[0].split("Error: ")[1]
    assert len(error) <= 161
    assert out["body"].startswith("Step: Every hour.")
    assert out["links"] == [] and out["link"] == ""


@needs_node
@pytest.mark.parametrize(
    "result, action",
    [
        ({"posted": True}, "error-alert-posted"),
        ({"posted": False, "preview": True, "message": "..."}, "error-alert-preview"),
        ({"posted": False, "error": "Slack unreachable: timeout"}, "error-alert-failed"),
        ({"error": {"message": "sub-workflow crashed"}}, "error-alert-failed"),
    ],
)
def test_w0_audit_entry(result, action):
    describe = {"target": "W5 Heartbeat, step x", "link": "http://n8n/e/1"}
    [out] = run_code(code_of(W0, "Audit fields"), result, {"Describe the error": describe})
    assert out["actor"] == "n8n:w0-error-handler" and out["actor_type"] == "n8n"
    assert out["action"] == action
    assert out["link"] == "http://n8n/e/1"
    assert out["target"].startswith("W5 Heartbeat, step x")
