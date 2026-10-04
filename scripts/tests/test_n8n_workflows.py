"""Tests for the code inside the n8n Slack and W0 workflows.

Each n8n Code node is run with Node.js against a stand-in for n8n's `$input`
and `$(...)`, so the message wording and the error cleaning are checked
without a running n8n.
"""

import json
import shutil
import subprocess
from datetime import UTC, datetime
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
    """Runs one Code node's code and returns the items' json. In `nodes`, a list
    stands for several items of that node; a node left out did not run."""
    harness = f"""
const NODES = {json.dumps(nodes or {})};
const $input = {{ first: () => ({{ json: {json.dumps(input_json)} }}) }};
const items = (name) => [].concat(NODES[name]).map((json) => ({{ json }}));
const $ = (name) => ({{ first: () => items(name)[0], all: () => items(name), isExecuted: name in NODES }});
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


# ---------------------------------------------------------------- Ready-for-QA notice (Story 5.7)

READY = workflow("ready-for-qa-notice.json")
SETTINGS = {"jira_url": "https://jira.example", "project": "PM", "ready_status": "Ready to Test", "repo": "o/r"}


def gh_run(path, conclusion, started, url="https://github.com/o/r/actions/runs/1"):
    return {"path": f".github/workflows/{path}", "status": "completed", "conclusion": conclusion,
            "run_started_at": started, "html_url": url}


def notices(pages, noticed=(), nightly=None, uat_pr=None):
    nodes = {
        "Settings": SETTINGS,
        "Already noticed": {"keys": list(noticed)},
        "nightly runs": {"workflow_runs": nightly} if nightly is not None else {"error": "404"},
        "uat-pr runs": {"workflow_runs": uat_pr} if uat_pr is not None else {"error": "404"},
    }
    code = code_of(READY, "Notices to send").replace(
        "$('Find tickets').all()", f"{json.dumps([{'json': p} for p in pages])}"
    )
    return run_code(code, {}, nodes)


def test_ready_notice_status_words_match_vocabulary():
    code = code_of(READY, "Notices to send")
    assert f"success: '{VOCABULARY['test_status']['passed']}'" in code
    assert f"failure: '{VOCABULARY['test_status']['failed']}'" in code


def test_ready_notice_reads_only_key_and_title_from_jira():
    find = next(n for n in READY["nodes"] if n["name"] == "Find tickets")
    params = {p["name"]: p["value"] for p in find["parameters"]["queryParameters"]["parameters"]}
    assert params["fields"] == "summary"
    assert READY["settings"]["errorWorkflow"] == W0["id"]


@needs_node
def test_ready_notice_message():
    pages = [{"issues": [{"key": "PM-1", "fields": {"summary": "Fix <b>pay</b> & save"}}]},
             {"issues": [{"key": "PM-2", "fields": {"summary": "Old one"}}]}]
    nightly = [gh_run("nightly.yml", "success", "2026-10-03T21:00:00Z", "https://gh/n")]
    uat_pr = [gh_run("uat-pr.yml", "failure", "2026-10-04T05:00:00Z", "https://gh/u"),
              gh_run("uat-pr.yml", "cancelled", "2026-10-04T06:00:00Z")]
    out = notices(pages, noticed=["PM-2"], nightly=nightly, uat_pr=uat_pr)
    assert [o["key"] for o in out] == ["PM-1"]
    [n] = out
    assert n["kind"] == "info" and n["header"] == "PM-1 is ready for QA"
    assert n["body"] == "*Fix &lt;b&gt;pay&lt;/b&gt; &amp; save*\nLatest UAT result: *FAILED* (uat-pr, 04 Oct 10:30 IST)."
    assert n["links"] == [{"label": "Jira", "url": "https://jira.example/browse/PM-1"},
                          {"label": "Latest run", "url": "https://gh/u"}]


@needs_node
def test_ready_notice_without_any_uat_run():
    [n] = notices([{"issues": [{"key": "PM-3", "fields": {"summary": "T"}}]}])
    assert n["body"] == "*T*\nNo UAT run yet."
    assert n["links"] == [{"label": "Jira", "url": "https://jira.example/browse/PM-3"}]


@needs_node
def test_ready_notice_nothing_new():
    assert notices([{"issues": []}]) == []


NOTICE_ITEMS = [{"json": {"key": "PM-1", "jira": "https://jira/PM-1"}}, {"json": {"key": "PM-2", "jira": "https://jira/PM-2"}}]


def run_on_results(node_name, results):
    code = code_of(READY, node_name).replace("$('Notices to send').all()", json.dumps(NOTICE_ITEMS))
    code = code.replace("$input.all()", json.dumps([{"json": r} for r in results]))
    return run_code(code, {})


@needs_node
def test_ready_notice_audit_entries():
    out = run_on_results("Audit fields", [{"posted": True, "link": "https://slack/p1"}, {"posted": False, "preview": True}])
    assert out == [
        {"actor": "n8n:ready-notice", "actor_type": "n8n", "action": "ready-notice-posted", "target": "PM-1",
         "link": "https://slack/p1"},
        {"actor": "n8n:ready-notice", "actor_type": "n8n", "action": "ready-notice-preview", "target": "PM-2",
         "link": "https://jira/PM-2"},
    ]


@needs_node
def test_ready_notice_failed_post_gets_no_audit_entry_and_fails_the_run():
    results = [{"posted": True, "link": "l"}, {"posted": False, "error": "Slack said not_in_channel"}]
    assert [o["target"] for o in run_on_results("Audit fields", results)] == ["PM-1"]
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_on_results("Check for failures", results)
    assert "Slack did not take the notice for PM-2: Slack said not_in_channel" in failure.value.stderr


# ---------------------------------------------------------------- Gate: check (Story 5.6)

GATE = workflow("gate-check.json")
FIXTURE = json.loads((ROOT / "contracts" / "cap-count.fixture.json").read_text())


@needs_node
@pytest.mark.parametrize("case", FIXTURE["cases"], ids=[c["name"] for c in FIXTURE["cases"]])
def test_cap_count_passes_the_shared_fixture(case):
    rules = code_of(GATE, "Check cap").split("const workflow =")[0]
    call = (f"return [{{ json: {{ count: countToday({json.dumps(case['runs'])}, new Date('{case['now']}'), "
            f"{json.dumps(case['current_run_id'])}) }} }}];")
    assert run_code(rules + call, {}) == [{"count": case["expected"]}]


def check_cap(caps_value, runs=(), outcomes=None, workflow_name="draft-cases"):
    nodes = {
        "Gate input": {"workflow": workflow_name},
        "Today's runs": {"workflow_runs": list(runs)},
        "Read AGENT_CAPS": {"value": caps_value} if caps_value is not None else {"error": {"message": "404"}},
    }
    if outcomes is not None:
        nodes["Read outcome"] = [{"data": o} for o in outcomes]
    return run_code(code_of(GATE, "Check cap"), {}, nodes)[0]


def today_run(run_id, status="completed"):
    return {"id": run_id, "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "status": status}


@needs_node
def test_cap_reached_uses_outcomes_from_artifacts():
    runs = [today_run(1), today_run(2), today_run(3, "in_progress")]
    caps = json.dumps({"draft-cases": 2})
    capped = check_cap(caps, runs, outcomes=[{"run_id": 1, "status": "ok"}])
    assert capped["decision"] == "capped" and capped["count"] == 3 and capped["cap"] == 2
    assert capped["not_before"].endswith("T18:30:00.000Z")
    allowed = check_cap(caps, runs, outcomes=[{"run_id": 1, "status": "capped"}, {"run_id": 2, "status": "blocked"}])
    assert allowed == {"decision": "ok", "cap": 2, "count": 1}


@needs_node
@pytest.mark.parametrize(
    "caps_value, problem",
    [
        (None, "AGENT_CAPS is missing or not valid JSON"),
        ("{not json", "AGENT_CAPS is missing or not valid JSON"),
        ('{"triage": 2}', "AGENT_CAPS has no daily limit for draft-cases"),
        ('{"draft-cases": "20"}', "AGENT_CAPS has no daily limit for draft-cases"),
    ],
)
def test_broken_caps_count_as_cap_reached(caps_value, problem):
    out = check_cap(caps_value)
    assert out["decision"] == "caps-invalid" and out["problem"] == problem


@needs_node
@pytest.mark.parametrize(
    "value, last, enabled, transition",
    [
        ("true", None, True, ""),
        ("true", "false", True, "on"),
        ("false", "true", False, "off"),
        ("TRUE", None, False, "off"),
        (None, "true", False, "off"),
        ("false", "false", False, ""),
    ],
)
def test_kill_switch(value, last, enabled, transition):
    read = {"value": value} if value is not None else {"error": {"message": "404"}}
    [out] = run_code(code_of(GATE, "Switch state"), {}, {"Read AGENT_ENABLED": read, "Read state": {"last_enabled": last}})
    assert out["enabled"] is enabled and out["transition"] == transition
    if transition == "off":
        assert out["header"] == "AI work is off" and out["kind"] == "alert"
        assert out["todo_label"] == "To turn it back on"
        assert "Still running: nightly and smoke tests" in out["body"]
    if transition == "on":
        assert out["header"] == "AI work is on again" and out["kind"] == "info"


@needs_node
def test_s12_is_saved_only_after_the_notice_went_out():
    nodes = {"Switch state": {"enabled": False}}
    [out] = run_code(code_of(GATE, "S12 audit fields"), {"posted": False, "preview": True}, nodes)
    assert out["action"] == "ai-work-off-notice" and out["actor"] == "n8n:gate-check"
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_code(code_of(GATE, "S12 audit fields"), {"posted": False, "error": "Slack said not_in_channel"}, nodes)
    assert "S12 notice not posted" in failure.value.stderr


@needs_node
@pytest.mark.parametrize("sent_on, expected", [(None, True), ("2026-10-03", True), ("2026-10-04", False)])
def test_s11_once_per_workflow_per_day(sent_on, expected):
    nodes = {"Check cap": {"reason": "capped", "today": "2026-10-04", "cap": 20, "count": 20},
             "Read state": {"s11_sent_on": sent_on}}
    [out] = run_code(code_of(GATE, "Deferred"), {"id": 7}, nodes)
    assert out["s11"] is expected and out["queued_id"] == 7


@needs_node
def test_s11_message():
    nodes = {"Gate input": {"workflow": "draft-cases", "target": "PM-1240"}}
    [out] = run_code(code_of(GATE, "S11 message"), {"cap": 20}, nodes)
    assert out["kind"] == "info" and out["header"] == "Case drafting waits until tomorrow"
    assert out["body"] == ("Today's limit of 20 case drafts is reached (counted since 00:00 IST).\n"
                           "PM-1240 will be drafted after 00:00 IST.")
    assert out["todo_label"] == "If urgent"
    assert out["todo"].startswith("run /draft-cases in Claude Code on a laptop")


@needs_node
def test_disabled_requests_are_kept_and_not_allowed():
    nodes = {"Disabled": {"reason": "disabled", "not_before": "2026-10-04T00:00:00Z", "audit_action": "gate-skipped-disabled"},
             "Read state": {}}
    [deferred] = run_code(code_of(GATE, "Deferred"), {"id": 3}, nodes)
    assert deferred["s11"] is False
    [out] = run_code(code_of(GATE, "Not allowed"), {}, {"Deferred": deferred})
    assert out["allowed"] is False and out["reason"] == "disabled" and out["queued_id"] == 3


@needs_node
def test_broken_caps_fail_the_caller_so_w0_alerts():
    deferred = {"reason": "caps-invalid", "problem": "AGENT_CAPS is missing or not valid JSON", "queued_id": 4}
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_code(code_of(GATE, "Not allowed"), {}, {"Deferred": deferred})
    assert "AGENT_CAPS is missing or not valid JSON. Request kept until it is fixed (deferred request 4)." in failure.value.stderr


def test_gate_is_a_helper_and_never_alerts_about_itself():
    assert "errorWorkflow" not in GATE["settings"]
