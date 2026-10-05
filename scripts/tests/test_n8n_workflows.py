"""Tests for the code inside the n8n Slack and W0 workflows.

Each n8n Code node is run with Node.js against a stand-in for n8n's `$input`
and `$(...)`, so the message wording and the error cleaning are checked
without a running n8n.
"""

import copy
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
const $input = {{ first: () => ({{ json: {json.dumps(input_json)} }}), all: () => [{{ json: {json.dumps(input_json)} }}] }};
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
        assert "write to Jira" not in out["body"] and "`JIRA_WRITES_ENABLED` is `true`" in out["body"]
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


# ---------------------------------------------------------------- W4 Daily QA update (Story 7.1)

W4 = workflow("w4-daily-update.json")
SAMPLE_SUMMARY = json.loads((ROOT / "contracts" / "samples" / "nightly-summary.sample.json").read_text())


def night(run_id, status="passed", passed=100, failed=0, retried=0, quarantined=0, failures=(), quarantine=()):
    return {**SAMPLE_SUMMARY, "nightly_run_id": run_id, "status": status,
            "counts": {"passed": passed, "failed": failed, "passed_on_retry": retried, "quarantined": quarantined, "skipped": 0},
            "failures": list(failures), "quarantine": list(quarantine)}


def daily_update(summaries, newest_hours_ago=7, switch="true", newest_id=None, decisions=()):
    started = datetime.now(UTC).timestamp() - newest_hours_ago * 3600
    newest = {"id": newest_id or (summaries[0]["nightly_run_id"] if summaries else 1),
              "run_started_at": datetime.fromtimestamp(started, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    nodes = {"Nightly runs": {"workflow_runs": [newest]}, "Read AGENT_ENABLED": {"value": switch} if switch else {"error": {}},
             "Decisions": {"decisions": list(decisions)} if decisions is not None else {"error": "connection refused"}}
    if summaries:
        nodes["Read summary"] = [{"data": s} for s in summaries]
    return run_code(code_of(W4, "Build update"), {}, nodes)[0]


def test_w4_status_words_match_vocabulary():
    code = code_of(W4, "Build update")
    for key, word in VOCABULARY["test_status"].items():
        assert f"'{word}'" in code, key
    for key, word in VOCABULARY["triage_class"].items():
        assert f"{key}: '{word}'" in code, key
    for key in ("bug", "flaky", "environment", "ignore"):
        reaction = VOCABULARY["reactions"][key]
        assert f"{key}: '{reaction['emoji']} {reaction['label']}'" in code, key


def test_w4_reads_live_decisions_before_building_the_update():
    c = W4["connections"]
    assert c["Read AGENT_ENABLED"]["main"][0][0]["node"] == "Decisions"
    assert c["Decisions"]["main"][0][0]["node"] == "Build update"
    decisions = next(n for n in W4["nodes"] if n["name"] == "Decisions")
    assert "d.undone_at IS NULL" in decisions["parameters"]["query"] and "m.kind = 'failure'" in decisions["parameters"]["query"]
    assert decisions["onError"] == "continueRegularOutput" and decisions["alwaysOutputData"] is True


def test_w4_runs_at_0930_ist_and_reports_errors_to_w0():
    trigger = next(n for n in W4["nodes"] if n["name"] == "Every day 09:30 IST")
    assert trigger["parameters"]["rule"]["interval"][0]["expression"] == "0 4 * * *"  # 04:00 UTC
    assert W4["settings"]["errorWorkflow"] == W0["id"]


@needs_node
def test_w4_failed_night():
    failures = [{"test_id": "api:tests/test_jobs.py::test_create_job", "flow_id": "job-creation", "status": "failed"},
                {"test_id": "api:tests/test_routes.py::test_route_sort", "flow_id": "routing", "status": "quarantined"},
                {"test_id": "ui:tests/login.spec.ts > Login > office admin signs in", "flow_id": "login", "status": "passed-on-retry"}]
    quarantine = [{"test_id": "api:tests/test_routes.py::test_route_sort", "owner": "ravi", "jira": "PM-5679", "deadline": "2026-10-15"}]
    out = daily_update([night(9, "failed", 212, 3, 1, 1, failures, quarantine)])
    assert out["header"].startswith("Daily QA update — ") and out["header"].endswith(", 09:30 IST")
    assert out["kind"] == ""
    lines = out["body"].split("\n")
    assert lines[0] == "Nightly UAT: *FAILED* — 212 passed, 3 failed, 1 passed on retry."
    assert lines[1] == "Coverage: 14 of 40 regression flows automated (35%)."
    assert lines[2] == "Flaky rate (last 1 night): 0.5%."
    assert "*Failures and decisions*" in lines
    assert "• `test_create_job` — FAILED — no decision yet" in lines
    assert "• `office admin signs in` — PASSED ON RETRY — no decision yet" in lines
    assert "• `test_route_sort` — *QUARANTINED*, owner ravi, PM-5679, deadline 15 Oct" in lines
    assert lines[-1] == "Datadog: not available."
    assert [link["label"] for link in out["links"]] == ["Nightly run", "Allure report"]
    assert out["ai_off"] is False


def decided(test_id, action=None, state="handled", cls="", name="asha", jira_key="", reason="", night=9):
    return {"nightly_run_id": str(night), "test_id": test_id, "class": cls, "action": action, "state": state if action else None,
            "actor_id": "U1", "actor_name": name, "reason": reason, "jira_key": jira_key}


@needs_node
def test_w4_failures_show_class_and_decision():
    ids = [f"api:tests/t.py::test_{n}" for n in ("bug", "env", "flaky", "waiting", "open", "no_message", "nameless")]
    failures = [{"test_id": t, "flow_id": "x", "status": "failed"} for t in ids]
    decisions = [
        decided(ids[0], "bug", cls="product_defect", jira_key="PM-5678"),
        decided(ids[1], "environment", cls="environment", name="ravi"),
        decided(ids[2], "flaky", cls="flaky", jira_key="PM-5679"),
        decided(ids[3], "ignore", state="waiting-for-reason"),
        decided(ids[4]),  # posted, nobody reacted yet; plain mode has no class
        decided(ids[6], "environment", name=""),
        decided(ids[5], "bug", jira_key="PM-1", night=8),  # another night: not shown
    ]
    lines = daily_update([night(9, "failed", failed=7, failures=failures)], decisions=decisions)["body"].split("\n")
    assert "• `test_bug` — FAILED — Product defect — 🐞 Bug PM-5678 by @asha" in lines
    assert "• `test_env` — FAILED — Environment — 🌩️ Environment by @ravi" in lines
    assert "• `test_flaky` — FAILED — Flaky — 🔁 Flaky PM-5679 by @asha" in lines
    assert "• `test_waiting` — FAILED — Not classified — 🙈 Ignore by @asha, waiting for a reason" in lines
    assert "• `test_open` — FAILED — Not classified — no decision yet" in lines
    assert "• `test_no_message` — FAILED — no decision yet" in lines
    assert "• `test_nameless` — FAILED — Not classified — 🌩️ Environment by <@U1>" in lines


@needs_node
def test_w4_ignored_failures_have_their_own_section():
    failures = [{"test_id": "api:tests/t.py::test_pdf", "flow_id": "x", "status": "failed"}]
    reason = "Test data\nreset late. " + "x" * 300
    out = daily_update([night(9, "failed", failed=1, failures=failures)],
                       decisions=[decided("api:tests/t.py::test_pdf", "ignore", reason=reason)])
    lines = out["body"].split("\n")
    assert "*Failures and decisions*" not in lines and "No failures last night." not in lines
    i = lines.index("*Ignored (with reasons)*")
    assert lines[i + 1].startswith('• `test_pdf` — 🙈 Ignore by @asha: "Test data reset late. xxx')
    assert lines[i + 1].endswith('…"') and len(lines[i + 1]) < 260


@needs_node
def test_w4_says_when_decisions_could_not_be_read():
    failures = [{"test_id": "api:tests/t.py::test_a", "flow_id": "x", "status": "failed"}]
    out = daily_update([night(9, "failed", failed=1, failures=failures)], decisions=None)
    assert "• `test_a` — FAILED — no decision yet" in out["body"]
    assert "Decisions: not available (the audit database didn't answer)." in out["body"]
    assert "Decisions: not available" not in daily_update([night(9)], decisions=None)["body"]


@needs_node
def test_w4_passed_night_and_flaky_rate_above_target():
    nights = [night(20 - i, retried=3 if i < 2 else 0) for i in range(14)]  # 6 retried of 1406 tests ran
    out = daily_update(nights)
    assert "No failures last night." in out["body"]
    assert "Flaky rate (last 14 nights): 0.4%." in out["body"]
    out = daily_update([night(5, retried=5, passed=95)])
    assert "Flaky rate (last 1 night): 5.0%. Above the 2% target. Review flaky tests and react 🔁 Flaky to quarantine them." in out["body"]


@needs_node
def test_w4_cuts_long_lists():
    failures = [{"test_id": f"api:tests/t.py::test_{i:02d}", "flow_id": "x", "status": "failed"} for i in range(13)]
    out = daily_update([night(9, "failed", failed=13, failures=failures)])
    assert "• `test_09` — FAILED — no decision yet" in out["body"]
    assert "test_10" not in out["body"]
    assert "and 3 more — see the run" in out["body"]


@pytest.mark.parametrize("case", ["no summaries", "stale run", "newest run has no summary"])
@needs_node
def test_w4_no_result_still_posts(case):
    if case == "no summaries":
        out = daily_update([])
    elif case == "stale run":
        out = daily_update([night(9)], newest_hours_ago=48)
    else:
        out = daily_update([night(8)], newest_id=9)
    assert out["body"].startswith("Nightly run: no result found for last night.")
    assert "Datadog: not available." in out["body"] and out["links"] == []


@needs_node
@pytest.mark.parametrize("switch", [None, "false"])
def test_w4_ai_off_line(switch):
    out = daily_update([night(9)], switch=switch)
    assert out["body"].endswith("AI work is off (`AGENT_ENABLED` is not `true`): failures are not classified.")
    assert out["ai_off"] is True


@needs_node
@pytest.mark.parametrize(
    "result, ai_off, action",
    [({"posted": True, "link": "l"}, False, "daily-update-posted"), ({"preview": True}, True, "daily-update-preview-ai-off")],
)
def test_w4_audit(result, ai_off, action):
    [out] = run_code(code_of(W4, "Audit fields"), result, {"Build update": {"nightly_run_id": 9, "ai_off": ai_off}})
    assert out["action"] == action and out["actor"] == "n8n:w4-daily-update" and out["target"] == "nightly 9"


@needs_node
def test_w4_failed_post_fails_the_run():
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_code(code_of(W4, "Audit fields"), {"posted": False, "error": "Slack said x"}, {"Build update": {}})
    assert "Daily update not posted: Slack said x" in failure.value.stderr


# ---------------------------------------------------------------- W7 Weekly audit log (Story 7.2)

W7 = workflow("w7-weekly-audit.json")


def build_file(entries, start="2026-09-29", end="2026-10-05", entries_as_text=False):
    week = {"week_start": start, "week_end": end, "entries": json.dumps(entries) if entries_as_text else entries}
    return run_code(code_of(W7, "Build file"), week, {"Settings": {"slack_channel": "C1"}})[0]


ENTRIES = [
    {"ts": "2026-09-29T21:04:11Z", "actor": "ci:nightly", "actor_type": "ci", "action": "run-success",
     "target": "nightly #12 on main (5b4a364)", "link": "https://github.com/o/r/actions/runs/1"},
    {"ts": "2026-09-30T05:12:40Z", "actor": "asha@gate6.com", "actor_type": "human", "action": "reaction-bug",
     "target": 'PM-5678, "Filed via QA bot"\nsecond line', "link": ""},
]


@needs_node
def test_w7_csv_follows_the_contract():
    from validate_contract import validate_csv

    out = build_file(ENTRIES)
    validate_csv("audit-export", out["csv"])
    assert out["csv"].startswith("ts,actor,actor_type,action,target,link\r\n")
    assert '"PM-5678, ""Filed via QA bot""\nsecond line"' in out["csv"]
    assert out["filename"] == "audit-2026-10-05.csv" and out["entries"] == 2
    assert out["bytes"] == len(out["csv"].encode())
    assert out["header"] == "Weekly audit log: 29 Sep–5 Oct"
    assert out["comment"] == (
        "*Weekly audit log: 29 Sep–5 Oct*\n"
        "The file lists every agent run, n8n action and QA decision this week (2 entries).\n"
        "Columns: ts, actor, actor_type, action, target, link. Times in the file are UTC."
    )


@needs_node
def test_w7_empty_week_and_text_entries():
    from validate_contract import validate_csv

    out = build_file([], start="2026-09-22", end="2026-09-28", entries_as_text=True)
    assert out["csv"] == "ts,actor,actor_type,action,target,link\r\n"
    validate_csv("audit-export", out["csv"])
    assert out["header"] == "Weekly audit log: 22–28 Sep"
    assert "No entries were recorded this week. The file has only the header row." in out["comment"]


def test_w7_schedule_and_errors():
    trigger = next(n for n in W7["nodes"] if n["name"] == "Every Monday 04:00 UTC")
    assert trigger["parameters"]["rule"]["interval"][0]["expression"] == "0 4 * * 1"
    assert W7["settings"]["errorWorkflow"] == W0["id"]
    settings = next(n for n in W7["nodes"] if n["name"] == "Settings")
    assert settings["parameters"]["assignments"]["assignments"][0] == {**settings["parameters"]["assignments"]["assignments"][0], "name": "slack_channel", "value": ""}


@needs_node
def test_w7_slack_refusal_fails_the_run():
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_code(code_of(W7, "Upload done?"), {"ok": False, "error": "not_in_channel"})
    assert "Slack refused the audit file upload: not_in_channel" in failure.value.stderr


@needs_node
@pytest.mark.parametrize("posted, action", [(True, "weekly-audit-posted"), (False, "weekly-audit-preview")])
def test_w7_audit_entry(posted, action):
    nodes = {"Build file": {"filename": "audit-2026-10-05.csv", "entries": 2, "week_start": "2026-09-29", "week_end": "2026-10-05"}}
    if posted:
        nodes["Upload done?"] = {"ok": True}
    [out] = run_code(code_of(W7, "Audit fields"), {}, nodes)
    assert out == {"actor": "n8n:w7-weekly-audit", "actor_type": "n8n", "action": action,
                   "target": "audit-2026-10-05.csv: 2 entries, 2026-09-29 to 2026-10-05", "link": ""}


# Month names are "Sep", never "Sept" (newer en-GB data spells it Sept).

@needs_node
def test_september_dates_use_sep():
    [n] = notices([{"issues": [{"key": "PM-5", "fields": {"summary": "T"}}]}],
                  nightly=[gh_run("nightly.yml", "success", "2026-09-03T21:00:00Z")])
    assert "(nightly, 04 Sep 02:30 IST)" in n["body"]
    quarantine = [{"test_id": "api:tests/t.py::test_x", "owner": "ravi", "jira": "PM-1", "deadline": "2026-09-15"}]
    assert "deadline 15 Sep" in daily_update([night(9, quarantine=quarantine)])["body"]
    assert build_file([], start="2026-09-01", end="2026-09-07")["header"] == "Weekly audit log: 1–7 Sep"
    for wf in (W0, READY, W4, W7):
        assert "en-GB" not in json.dumps(wf)


# ---------------------------------------------------------------- W1 Ticket watcher (Story 5.5)

W1 = workflow("w1-ticket-watcher.json")
PATTERNS_FILE = ROOT / "scripts" / "masking-patterns.json"


def w1_patterns():
    return run_code(code_of(W1, "Masking patterns"), {})[0]


def test_w1_copy_of_the_patterns_is_the_file_and_its_hash():
    import hashlib

    out = w1_patterns()
    assert out["raw"] == PATTERNS_FILE.read_text(encoding="utf-8")
    assert out["pinned"] == hashlib.sha256(PATTERNS_FILE.read_bytes()).hexdigest()


@needs_node
def test_w1_refuses_when_the_copy_does_not_match():
    nodes = {"Masking patterns": {"pinned": "a" * 64}}
    assert run_code(code_of(W1, "Check the pin"), {"actual": "a" * 64}, nodes) == [{"ok": True}]
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_code(code_of(W1, "Check the pin"), {"actual": "b" * 64}, nodes)
    assert "Masking patterns copy does not match its pinned hash" in failure.value.stderr


def test_w1_reads_only_description_and_acceptance_criteria():
    fetch = next(n for n in W1["nodes"] if n["name"] == "Fetch ticket text")
    assert fetch["parameters"]["queryParameters"]["parameters"] == [
        {"name": "fields", "value": "=description,{{ $('Settings').first().json.ac_field }}"}]
    settings = {a["name"]: a["value"] for a in next(n for n in W1["nodes"] if n["name"] == "Settings")["parameters"]["assignments"]["assignments"]}
    assert settings["ac_field"] == "customfield_11600"
    assert settings["draft_status"] == "In Progress" and settings["tests_status"] == "Ready to Test"
    assert W1["settings"]["errorWorkflow"] == W0["id"]


@needs_node
def test_w1_new_requests_skip_known_queued_and_repeated():
    nodes = {
        "Known requests": {"known": ["PM-1 draft-cases"]},
        "Due queue": {"due": [{"ticket": "PM-2", "workflow": "generate-tests", "queue_id": 4}]},
        "Find draft tickets": [{"issues": [{"key": "PM-1"}, {"key": "PM-3"}]}, {"issues": [{"key": "PM-3"}, {"key": "bad key"}]}],
        "Find test tickets": [{"issues": [{"key": "PM-1"}, {"key": "PM-2"}]}],
    }
    out = run_code(code_of(W1, "New requests"), {}, nodes)
    assert out == [{"ticket": "PM-3", "workflow": "draft-cases"}, {"ticket": "PM-1", "workflow": "generate-tests"}]


def adf(*paragraphs, items=()):
    content = [{"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs]
    if items:
        content.append({"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": i}]}]} for i in items]})
    return {"type": "doc", "version": 1, "content": content}


@needs_node
def test_w1_ticket_text_is_plain_masked_and_only_two_fields():
    from tests.test_sanitize import FIXTURES

    secrets = " ".join(v for k, v in FIXTURES.items() if k != "private-key")
    issue = {"fields": {
        "description": adf("Owner maria.lopez@sunnypools.com can create a job.", f"Token: {secrets}"),
        "customfield_11600": adf("Given a job", items=["it is saved", "it starts as Scheduled"]),
        "summary": "SHOULD NOT APPEAR", "comment": "SHOULD NOT APPEAR",
    }}
    nodes = {"Masking patterns": w1_patterns(), "Settings": {"ac_field": "customfield_11600"},
             "New requests": [{"ticket": "PM-7", "workflow": "draft-cases"}]}
    [out] = run_code(code_of(W1, "Ticket text"), issue, nodes)
    assert out["ticket"] == "PM-7" and out["workflow"] == "draft-cases" and out["queue_id"] == 0
    text = out["ticket_text"]
    assert text.startswith("Description:\nOwner [email] can create a job.\n")
    assert "Acceptance criteria:\nGiven a job\n- it is saved\n- it starts as Scheduled" in text
    assert "SHOULD NOT APPEAR" not in text
    for secret in FIXTURES.values():
        assert secret not in text


@needs_node
def test_w1_ticket_text_without_fields_and_long_text():
    nodes = {"Masking patterns": w1_patterns(), "Settings": {"ac_field": "customfield_11600"},
             "New requests": [{"ticket": "PM-7", "workflow": "draft-cases"}]}
    [out] = run_code(code_of(W1, "Ticket text"), {"fields": {}}, nodes)
    assert out["ticket_text"] == "Description:\n(none)\n\nAcceptance criteria:\n(none)"
    [out] = run_code(code_of(W1, "Ticket text"), {"fields": {"description": adf("word " * 5000)}}, nodes)
    assert len(out["ticket_text"]) == 15000 and out["ticket_text"].endswith("…")


@needs_node
def test_w1_requests_to_try_put_the_waiting_list_first():
    nodes = {
        "Due queue": {"due": json.dumps([{"queue_id": 4, "ticket": "PM-2", "workflow": "generate-tests", "ticket_text": "masked"}])},
        "Ticket text": [{"ticket": "PM-3", "workflow": "draft-cases", "ticket_text": "new", "queue_id": 0}],
    }
    out = run_code(code_of(W1, "Requests to try"), {}, nodes)
    assert out == [
        {"action": "dispatch", "workflow": "generate-tests", "target": "PM-2", "payload": {"ticket": "PM-2", "ticket_text": "masked"}, "queue_id": 4},
        {"action": "dispatch", "workflow": "draft-cases", "target": "PM-3", "payload": {"ticket": "PM-3", "ticket_text": "new"}, "queue_id": 0},
    ]
    del nodes["Ticket text"]
    assert [r["target"] for r in run_code(code_of(W1, "Requests to try"), {}, nodes)] == ["PM-2"]


@needs_node
def test_w1_gate_answers_and_audit():
    requests = [{"target": "PM-2", "workflow": "generate-tests", "queue_id": 4}, {"target": "PM-3", "workflow": "draft-cases", "queue_id": 0}]
    code = code_of(W1, "Gate answers").replace("$input.all()", json.dumps([{"json": {"allowed": True, "reason": "ok"}},
                                                                            {"json": {"allowed": False, "reason": "disabled"}}]))
    answers = run_code(code, {}, {"Requests to try": requests})
    assert [(a["target"], a["allowed"], a["reason"]) for a in answers] == [("PM-2", True, "ok"), ("PM-3", False, "disabled")]
    audit = run_code(code_of(W1, "Audit fields"), {}, {"Gate answers": answers, "Settings": {"repo": "o/r"}})
    assert audit == [{"actor": "n8n:w1-ticket-watcher", "actor_type": "n8n", "action": "dispatch-generate-tests",
                      "target": "PM-2", "link": "https://github.com/o/r/actions/workflows/generate-tests.yml"}]


def test_w1_dispatches_with_the_masked_text_on_main():
    start = next(n for n in W1["nodes"] if n["name"] == "Start the workflow")
    assert "ref: 'main'" in start["parameters"]["jsonBody"]
    assert "ticket_text: $json.payload.ticket_text" in start["parameters"]["jsonBody"]
    assert W1["connections"]["Allowed?"]["main"][0][0]["node"] == "Start the workflow"


# ---------------------------------------------------------------- W1 Follow-up (Story 5.5, part 2)

W1F = workflow("w1-follow-up.json")


def iso(minutes_ago):
    return datetime.fromtimestamp(datetime.now(UTC).timestamp() - minutes_ago * 60, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def request(rid=1, ticket="PM-1", wf="draft-cases", state="dispatched", minutes_ago=5, attempts=1, notified="", reason=""):
    return {"id": rid, "ticket": ticket, "workflow": wf, "state": state, "reason": reason, "attempts": attempts,
            "notified": notified, "dispatched_at": iso(minutes_ago), "since": iso(minutes_ago + 2)}


def wf_run(r, run_id=9, status="completed", minutes_ago=4, title=None):
    return {"id": run_id, "display_title": title or f"{r['workflow']} {r['ticket']}", "status": status, "created_at": iso(minutes_ago)}


def decide(dispatched=(), runs=(), outcomes=(), waiting=(), cases_now=(), s11=None, cases_prs=None):
    finished = [{"request_id": r["id"], "run_id": run["id"]} for r, page in zip(dispatched, runs)
                for run in page if run["status"] == "completed" and run["display_title"] == f"{r['workflow']} {r['ticket']}"][:len(dispatched)]
    nodes = {"Open requests": {"requests": [], "s11": s11 or {}, "cases_prs": cases_prs or {}},
             "Dispatched": list(dispatched), "List runs": [{"workflow_runs": list(p)} for p in runs],
             "Finished runs": finished, "Read outcome": [{"data": o} for o in outcomes],
             "Waiting for cases": list(waiting), "Cases on main?": [{"statusCode": c} for c in cases_now]}
    for name in [k for k, v in nodes.items() if v == []]:
        del nodes[name]
    return run_code(code_of(W1F, "Decide"), {}, nodes)


def outcome(status, reason="", pr_url="", run_id=9):
    return {"run_id": run_id, "status": status, "reason": reason, **({"pr_url": pr_url} if pr_url else {})}


@needs_node
def test_follow_up_done_posts_s7_once():
    r = request()
    [d] = decide([r], [[wf_run(r)]], [outcome("ok", pr_url="https://github.com/o/r/pull/5")])
    assert (d["state"], d["notice"], d["pr_url"], d["notified"]) == ("done", "S7", "https://github.com/o/r/pull/5", "https://github.com/o/r/pull/5")
    r = request(notified="https://github.com/o/r/pull/5")
    [d] = decide([r], [[wf_run(r)]], [outcome("ok", "already-open", "https://github.com/o/r/pull/5")])
    assert d["state"] == "done" and d["notice"] == ""


@needs_node
def test_follow_up_tests_done_posts_s9():
    r = request(wf="generate-tests")
    [d] = decide([r], [[wf_run(r)]], [outcome("ok", pr_url="https://github.com/o/r/pull/6")])
    assert d["notice"] == "S9"


@needs_node
def test_follow_up_still_running_waits_and_wrong_titles_are_ignored():
    r = request()
    assert decide([r], [[wf_run(r, status="in_progress")]]) == []
    r = request(minutes_ago=30)
    [d] = decide([r], [[wf_run(r, title="draft-cases PM-2")]])
    assert (d["state"], d["reason"], d["enqueue"]) == ("deferred", "run-not-found", "retry")


@needs_node
def test_follow_up_blocked_cases_not_merged_posts_s10_once_then_retries_after_merge():
    r = request(wf="generate-tests")
    [d] = decide([r], [[wf_run(r)]], [outcome("blocked", "cases-not-merged")], cases_prs={"PM-1": "https://github.com/o/r/pull/5"})
    assert (d["state"], d["notice"], d["notified"], d["cases_pr"]) == ("blocked", "S10", "blocked:cases-not-merged", "https://github.com/o/r/pull/5")
    r = request(wf="generate-tests", notified="blocked:cases-not-merged")
    [d] = decide([r], [[wf_run(r)]], [outcome("blocked", "cases-not-merged")])
    assert d["notice"] == ""  # the same block is not announced twice
    waiting = request(wf="generate-tests", state="blocked", reason="cases-not-merged")
    assert decide(waiting=[waiting], cases_now=[404]) == []
    [d] = decide(waiting=[waiting], cases_now=[200])
    assert (d["state"], d["enqueue"], d["reason"]) == ("deferred", "retry", "cases-merged")


@needs_node
def test_follow_up_other_blocks():
    r = request()
    [d] = decide([r], [[wf_run(r)]], [outcome("blocked", "cases-already-on-main")])
    assert d["state"] == "done" and d["notice"] == ""
    [d] = decide([r], [[wf_run(r)]], [outcome("blocked", "no-matching-flow")])
    assert (d["state"], d["notice"], d["enqueue"]) == ("blocked", "S10", "")


@needs_node
def test_follow_up_capped_requeues_after_midnight_with_one_s11():
    a, b = request(1, "PM-1"), request(2, "PM-2")
    ds = decide([a, b], [[wf_run(a, 9)], [wf_run(b, 10)]], [outcome("capped", "daily-cap-reached", run_id=9),
                                                            outcome("capped", "daily-cap-reached", run_id=10)])
    assert [d["enqueue"] for d in ds] == ["capped", "capped"]
    assert [d["notice"] for d in ds] == ["S11", ""]
    assert ds[0]["not_before"].endswith("T18:30:00.000Z")
    today = ds[0]["s11_day"]
    [d] = decide([a], [[wf_run(a)]], [outcome("capped", "daily-cap-reached")], s11={"draft-cases": today})
    assert d["notice"] == ""


@needs_node
def test_follow_up_disabled_requeues_and_errors_retry_then_fail():
    r = request()
    [d] = decide([r], [[wf_run(r)]], [outcome("disabled", "agent-enabled-off")])
    assert (d["state"], d["enqueue"], d["notice"]) == ("deferred", "disabled", "")
    [d] = decide([r], [[wf_run(r)]], [outcome("error", "agent-failed")])
    assert (d["state"], d["enqueue"], d["reason"]) == ("deferred", "retry", "agent-failed")
    r = request(attempts=3)
    [d] = decide([r], [[wf_run(r)]], [outcome("error", "agent-failed")])
    assert (d["state"], d["notice"], d["enqueue"]) == ("failed", "S10", "")
    [d] = decide([r], [[wf_run(r)]], [])
    assert d["reason"] == "no-run-outcome" and d["state"] == "failed"


def message(decision, case_text=None):
    import base64

    file = {"statusCode": 200, "body": {"content": base64.b64encode(case_text.encode()).decode()}} if case_text else {"statusCode": 404}
    nodes = {"Settings": {"repo": "o/r", "jira_url": "https://jira"}, "Notices": [decision]}
    code = code_of(W1F, "Message").replace("$input.all()", json.dumps([{"json": file}]))
    return run_code(code, {}, nodes)[0]


BASE = {"ticket": "PM-1", "workflow": "draft-cases", "pr_url": "https://github.com/o/r/pull/5", "run_id": 9,
        "reason": "", "state": "done", "cases_pr": "", "case_ref": "agent/PM-1-cases"}


@needs_node
def test_s7_and_s9_messages():
    m = message({**BASE, "notice": "S7"}, "---\nticket: PM-1\nflows: [job-creation, login]\n---\n")
    assert m["header"] == "Test cases drafted for PM-1" and m["kind"] == ""
    assert m["body"] == "The agent drafted cases from the acceptance criteria. Flows: `job-creation`, `login`."
    assert m["todo"] == "review and edit PR 1, then merge it to accept the cases."
    assert [link["label"] for link in m["links"]] == ["PR 1", "Jira PM-1", "Case file"]
    assert m["links"][2]["url"] == "https://github.com/o/r/blob/agent/PM-1-cases/cases/PM-1.md"
    m = message({**BASE, "workflow": "generate-tests", "notice": "S9", "case_ref": "main"}, "flows: [job-creation]\n")
    assert m["header"] == "Tests generated for PM-1"
    assert m["body"] == "PR 2 adds API tests with SQL checks for flow `job-creation`."
    assert m["todo"] == "review every line, approve, then start `uat-pr` with the reviewed commit SHA."
    assert [link["label"] for link in m["links"]] == ["PR 2", "Run workflow: uat-pr", "Jira PM-1"]


@needs_node
def test_s10_and_s11_messages():
    m = message({**BASE, "workflow": "generate-tests", "notice": "S10", "state": "blocked", "reason": "cases-not-merged",
                 "cases_pr": "https://github.com/o/r/pull/5", "pr_url": ""})
    assert (m["kind"], m["header"]) == ("action", "tests for PM-1 can't be generated yet")
    assert m["body"] == "Reason: its cases PR is not merged on `main` (`cases-not-merged`)."
    assert m["todo"] == "review and merge PR 1. This retries on its own after that."
    assert [link["label"] for link in m["links"]] == ["PR 1", "Run", "Jira PM-1"]
    m = message({**BASE, "notice": "S10", "state": "failed", "reason": "agent-failed", "pr_url": ""})
    assert m["header"] == "Case drafting for PM-1 failed"
    assert m["todo"] == "look at the last run, or run /draft-cases PM-1 on a laptop."
    m = message({**BASE, "notice": "S11", "state": "deferred", "reason": "capped", "pr_url": ""})
    assert (m["kind"], m["header"], m["todo_label"]) == ("info", "Case drafting waits until tomorrow", "If urgent")
    assert "PM-1 will be drafted after 00:00 IST." in m["body"]


@needs_node
def test_follow_up_notice_failure_saves_nothing():
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_code(code_of(W1F, "Posted?").replace("$input.all()", json.dumps([{"json": {"posted": False, "error": "x"}}])), {})
    assert "W1 notice not posted: x" in failure.value.stderr
    assert W1F["connections"]["Decide"]["main"][0][0]["node"] == "Notices"  # notices run before the saves
    assert W1F["settings"]["errorWorkflow"] == W0["id"]


@needs_node
def test_gate_asks_again_about_disabled_requests_after_15_minutes():
    [out] = run_code(code_of(GATE, "Disabled"), {})
    wait = datetime.fromisoformat(out["not_before"]) - datetime.now(UTC)
    assert 14 * 60 < wait.total_seconds() <= 15 * 60


def test_w1_counts_only_real_starts_as_tries():
    record = next(n for n in W1["nodes"] if n["name"] == "Record started")["parameters"]["query"]
    assert "attempts + CASE WHEN excluded.state = 'dispatched' THEN 1 ELSE 0 END" in record


# ---------------------------------------------------------------- GitHub: read artifact, and W2 Nightly watcher (Story 6.3)

READ = workflow("github-read-artifact.json")
W2 = workflow("w2-nightly-watcher.json")


@needs_node
def test_read_artifact_picks_the_named_unexpired_one():
    code = code_of(READ, "Has it?")
    artifacts = {"artifacts": [{"name": "failure-list", "expired": True, "archive_download_url": "old"},
                               {"name": "failure-list", "expired": False, "archive_download_url": "new"}]}
    assert run_code(code, artifacts, {"Artifact": {"name": "failure-list"}}) == [{"url": "new"}]
    assert run_code(code, {"artifacts": []}, {"Artifact": {"name": "failure-list"}}) == [{"url": ""}]
    assert "errorWorkflow" not in READ["settings"]


@needs_node
def test_w2_candidates_are_new_failed_nights():
    nodes = {
        "Known requests": {"known": ["10"]},
        "Due queue": {"due": json.dumps([{"queue_id": 3, "nightly_run_id": "11"}])},
        "Failed nightlies": {"workflow_runs": [
            {"id": 10, "status": "completed", "conclusion": "failure"},
            {"id": 11, "status": "completed", "conclusion": "failure"},
            {"id": 12, "status": "completed", "conclusion": "failure"},
            {"id": 13, "status": "completed", "conclusion": "success"},
            {"id": 14, "status": "in_progress", "conclusion": None},
        ]},
    }
    assert run_code(code_of(W2, "Candidates"), {}, nodes) == [{"nightly_run_id": "12"}]


@needs_node
def test_w2_needs_a_failure_list_and_puts_the_waiting_list_first():
    code = code_of(W2, "With failure-list").replace("$input.all()", json.dumps([
        {"json": {"artifacts": [{"name": "failure-list", "expired": False}]}}, {"json": {"artifacts": []}}]))
    assert run_code(code, {}, {"Candidates": [{"nightly_run_id": "12"}, {"nightly_run_id": "15"}]}) == [{"nightly_run_id": "12"}]
    nodes = {"Settings": {"triage_mode": "agent"}, "Due queue": {"due": [{"queue_id": 3, "nightly_run_id": "11"}]},
             "With failure-list": [{"nightly_run_id": "12"}]}
    out = run_code(code_of(W2, "Requests to try"), {}, nodes)
    assert out == [
        {"action": "dispatch", "workflow": "triage", "target": "11", "payload": {"nightly_run_id": "11"}, "queue_id": 3, "plain": False},
        {"action": "dispatch", "workflow": "triage", "target": "12", "payload": {"nightly_run_id": "12"}, "queue_id": 0, "plain": False},
    ]


@needs_node
@pytest.mark.parametrize("mode", ["plain", "", "Agent", None])
def test_w2_plain_mode_is_the_default_and_skips_the_waiting_list(mode):
    nodes = {"Settings": {"repo": "o/r"} if mode is None else {"triage_mode": mode},
             "Due queue": {"due": [{"queue_id": 3, "nightly_run_id": "11"}]}, "With failure-list": [{"nightly_run_id": "12"}]}
    out = run_code(code_of(W2, "Requests to try"), {}, nodes)
    assert [(o["target"], o["plain"]) for o in out] == [("12", True)]


def test_w2_plain_nights_are_recorded_without_the_gate():
    settings = next(n for n in W2["nodes"] if n["name"] == "Settings")["parameters"]["assignments"]["assignments"]
    assert {"name": "triage_mode", "value": "plain"}.items() <= next(a for a in settings if a["name"] == "triage_mode").items()
    assert W2["connections"]["Anything to try?"]["main"][0][0]["node"] == "Plain?"
    assert W2["connections"]["Plain?"]["main"][0][0]["node"] == "Record plain"
    assert W2["connections"]["Plain?"]["main"][1][0]["node"] == "Gate"
    record = next(n for n in W2["nodes"] if n["name"] == "Record plain")["parameters"]
    assert "VALUES ($1::bigint, 'plain', 'plain')" in record["query"] and "ON CONFLICT (nightly_run_id) DO NOTHING" in record["query"]
    assert "Record plain" not in W2["connections"]  # no dispatch, no audit entry: W3 audits the post
    schema = (ROOT / "n8n" / "audit" / "schema.sql").read_text()
    assert "CHECK (state IN ('dispatched', 'deferred', 'plain', 'posted', 'fallback'))" in schema


def test_w2_starts_triage_only_through_the_gate():
    assert W2["connections"]["Plain?"]["main"][1][0]["node"] == "Gate"  # agent mode
    assert W2["connections"]["Allowed?"]["main"][0][0]["node"] == "Start triage"
    start = next(n for n in W2["nodes"] if n["name"] == "Start triage")
    assert "triage.yml/dispatches" in start["parameters"]["url"] and "ref: 'main'" in start["parameters"]["jsonBody"]
    assert W2["settings"]["errorWorkflow"] == W0["id"]


# ---------------------------------------------------------------- W3 Triage poster (Story 6.3, part 2)

W3 = workflow("w3-triage-poster.json")
FAILURE_LIST = json.loads((ROOT / "contracts" / "samples" / "failure-list.sample.json").read_text())
# A triage result for the sample failure list's own tests: the first a product
# defect, the second flaky, any others not classified.
TRIAGE = {"schema_version": 1, "nightly_run_id": FAILURE_LIST["nightly_run_id"], "failures": [
    {"test_id": FAILURE_LIST["failures"][0]["test_id"], "class": "product_defect",
     "evidence": "API returned 500 on job create.", "bug_title": "Job create returns 500 when the route is empty"},
    {"test_id": FAILURE_LIST["failures"][1]["test_id"], "class": "flaky", "evidence": "Passed on retry tonight."},
]}


def open_request(nid="7", state="dispatched", minutes_ago=10, posted=(), queue_reason=None, post_wait_until=None):
    return {"nightly_run_id": nid, "state": state, "posted": list(posted), "dispatched_at": iso(minutes_ago),
            "created_at": iso(minutes_ago), "queue_reason": queue_reason, "post_wait_until": post_wait_until}


def w3_decide(requests, finished=(), outcomes=()):
    nodes = {"Open requests": {"requests": list(requests)}}
    if finished:
        nodes["Finished runs"] = list(finished)
        nodes["Read outcome"] = [{"found": o is not None, "data": o} for o in outcomes]
    return run_code(code_of(W3, "Decide"), {}, nodes)


def test_w3_vocabulary_copies_match():
    code = code_of(W3, "Messages")
    for key, word in VOCABULARY["triage_class"].items():
        assert f"{key}: '{word}'" in code
    for key in ("bug", "flaky", "environment", "ignore", "undo"):
        reaction = VOCABULARY["reactions"][key]
        assert f"{reaction['emoji']} {reaction['label'] if key != 'undo' else 'Undo within 24 h'}" in code


@needs_node
def test_w3_decides_classified_fallback_or_wait():
    finished = [{"nightly_run_id": "7", "triage_run_id": "70"}]
    [d] = w3_decide([open_request()], finished, [{"status": "ok"}])
    assert (d["mode"], d["triage_run_id"], d["reason"]) == ("classified", "70", "")
    [d] = w3_decide([open_request()], finished, [{"status": "error", "reason": "invalid-triage"}])
    assert (d["mode"], d["reason"]) == ("fallback", "invalid-triage")
    [d] = w3_decide([open_request()], finished, [{"status": "capped", "reason": "daily-cap-reached"}])
    assert (d["mode"], d["reason"]) == ("fallback", "capped")
    [d] = w3_decide([open_request()], finished, [None])
    assert d["reason"] == "no-run-outcome"
    assert w3_decide([open_request(minutes_ago=30)]) == []  # still running
    [d] = w3_decide([open_request(minutes_ago=61)])
    assert (d["mode"], d["reason"]) == ("fallback", "no-triage-run")


@needs_node
def test_w3_deferred_and_gate_back_off():
    assert w3_decide([open_request(state="deferred", minutes_ago=30, queue_reason="capped")]) == []
    [d] = w3_decide([open_request(state="deferred", minutes_ago=61, queue_reason="capped")])
    assert (d["mode"], d["reason"]) == ("fallback", "capped")
    later = datetime.fromtimestamp(datetime.now(UTC).timestamp() + 600, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert w3_decide([open_request(minutes_ago=61, post_wait_until=later)]) == []


@needs_node
def test_w3_plain_nights_fall_back_at_once_without_the_gate():
    [d] = w3_decide([open_request(state="plain", minutes_ago=0)])
    assert (d["mode"], d["reason"], d["gated"], d["triage_run_id"]) == ("fallback", "plain", False, "")
    finished = [{"nightly_run_id": "7", "triage_run_id": "70"}]
    [d] = w3_decide([open_request()], finished, [{"status": "ok"}])
    assert d["gated"] is True
    assert "'plain'" in next(n for n in W3["nodes"] if n["name"] == "Open requests")["parameters"]["query"]


def w3_messages(night, failure_list=FAILURE_LIST, triage=TRIAGE):
    reads = [{"found": failure_list is not None, "data": failure_list}]
    if night["mode"] == "classified":
        reads.append({"found": triage is not None, "data": triage})
    nodes = {"Settings": {"repo": "o/r"}, "Read artifacts": reads, "Nights to post": [night]}
    return run_code(code_of(W3, "Messages"), {}, nodes)


def night_of(mode="classified", posted=(), reason="", triage_run_id="70"):
    return {"nightly_run_id": str(FAILURE_LIST["nightly_run_id"]), "mode": mode, "posted": list(posted),
            "reason": reason, "triage_run_id": triage_run_id}


@needs_node
def test_w3_classified_replies():
    msgs = w3_messages(night_of())
    assert len(msgs) == len(FAILURE_LIST["failures"])
    assert all(m["thread_ts"] == FAILURE_LIST["slack_ts"] for m in msgs)
    by_test = {m["test_id"]: m for m in msgs}
    classified = [m for m in msgs if m["class"]]
    assert [m["class"] for m in classified] == ["product_defect", "flaky"]
    for m in classified:
        triage = next(f for f in TRIAGE["failures"] if f["test_id"] == m["test_id"])
        assert m["header"] == f"Class: {VOCABULARY['triage_class'][triage['class']]} (suggested)"
        assert f"Why: {triage['evidence']}" in m["body"]
        assert m["legend"].endswith("↩️ Undo within 24 h. Reply appears in about 2 minutes.")
        if triage["class"] == "product_defect":
            assert f'Drafted bug: "{triage["bug_title"]}"' in m["body"] and m["todo"].endswith("Suggested: 🐞 Bug.")
    unclassified = [m for t, m in by_test.items() if not m["class"]]
    assert all(m["header"] == "Not classified" and m["legend"] for m in unclassified)
    assert [link["label"] for link in msgs[0]["links"]] == ["Run", "Allure report"]


@needs_node
def test_w3_fallback_posts_s3_first_then_every_failure():
    msgs = w3_messages(night_of("fallback", reason="capped"))
    assert msgs[0]["key"] == "s3" and msgs[0]["header"] == "Classification didn't run for last night's failures."
    assert msgs[0]["body"] == "Reason: the agent's daily limit for triage is reached (`capped`)."
    assert msgs[0]["todo"].endswith("The gate is unchanged.") and msgs[0]["legend"] == ""
    assert [m["key"] for m in msgs[1:]] == [f"test:{f['test_id']}" for f in FAILURE_LIST["failures"]]
    assert all(m["header"] == "Not classified" for m in msgs[1:])


@needs_node
def test_w3_plain_night_explains_why_and_posts_every_failure():
    msgs = w3_messages(night_of("fallback", reason="plain", triage_run_id=""))
    assert msgs[0]["body"] == "Reason: AI triage is used only on laptops, not in GitHub (`plain`)."
    assert msgs[0]["links"] == []
    assert len(msgs) == 1 + len(FAILURE_LIST["failures"])
    assert all(m["header"] == "Not classified" and m["legend"].startswith("React: 🐞 Bug") for m in msgs[1:])


@needs_node
def test_w3_retry_skips_what_was_posted_and_long_lists_shorten_ids():
    first = FAILURE_LIST["failures"][0]["test_id"]
    msgs = w3_messages(night_of("fallback", posted=["s3", f"test:{first}"], reason="capped"))
    assert "s3" not in [m["key"] for m in msgs] and f"test:{first}" not in [m["key"] for m in msgs]
    many = {**FAILURE_LIST, "failures": [{**FAILURE_LIST["failures"][0], "test_id": f"api:tests/t.py::test_{i:02d}"} for i in range(12)]}
    msgs = w3_messages(night_of("fallback", reason="capped"), failure_list=many)
    assert len(msgs) == 13 and msgs[1]["body"].startswith("`test_00` — flow")
    assert w3_messages(night_of(), failure_list=None) == []


@needs_node
def test_w3_remembers_what_went_out_and_fails_on_the_rest():
    messages = [{"key": "test:a", "nightly_run_id": "7"}, {"key": "test:b", "nightly_run_id": "7"}]
    code = code_of(W3, "Posted rows").replace("$input.all()", json.dumps(
        [{"json": {"posted": True, "channel": "C1", "ts": "1.2"}}, {"json": {"posted": False, "error": "x"}}]))
    out = run_code(code, {}, {"Messages": messages})
    assert [(o["key"], o["ts"]) for o in out] == [("test:a", "1.2")]
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_code(code_of(W3, "All posted?"), {}, {"Post": [{"posted": True}, {"posted": False, "error": "not_in_channel"}],
                                                   "Nights to post": [{"nightly_run_id": "7"}]})
    assert "1 triage message(s) not posted: not_in_channel" in failure.value.stderr
    assert run_code(code_of(W3, "All posted?"), {}, {"Nights to post": [{"nightly_run_id": "7"}]}) == [{"nightly_run_id": "7"}]


def test_w3_posting_is_gated():
    c = W3["connections"]
    assert c["Decide"]["main"][0][0]["node"] == "Needs the gate?"
    assert c["Needs the gate?"]["main"][0][0]["node"] == "To the gate"
    assert c["To the gate"]["main"][0][0]["node"] == "Gate"
    assert c["Allowed nights"]["main"][0] == [{"node": "Nights to post", "type": "main", "index": 0}]
    # Only plain nights (no AI) skip the gate, into the merge's second input.
    assert c["Needs the gate?"]["main"][1] == [{"node": "Nights to post", "type": "main", "index": 1}]
    assert c["Nights to post"]["main"][0][0]["node"] == "What to read"
    gate_input = next(n for n in W3["nodes"] if n["name"] == "To the gate")["parameters"]["jsCode"]
    assert "action: 'triage-post'" in gate_input


@needs_node
def test_w3_gate_answers_match_their_nights():
    asked = [{"night": {"nightly_run_id": "7"}}, {"night": {"nightly_run_id": "8"}}]
    code = code_of(W3, "Allowed nights").replace("$input.all()", json.dumps([{"json": {"allowed": False}}, {"json": {"allowed": True}}]))
    assert run_code(code, {}, {"To the gate": asked}) == [{"nightly_run_id": "8"}]
    code = code_of(W3, "To the gate").replace("$input.all()", json.dumps([{"json": {"nightly_run_id": "7", "mode": "classified"}}]))
    [g] = run_code(code, {})
    assert g["night"] == {"nightly_run_id": "7", "mode": "classified"} and g["target"] == "7"
    assert W3["settings"]["errorWorkflow"] == W0["id"]


# ---------------------------------------------------------------- W6 Questions poster (Story 6.7, part 1)

W6 = workflow("w6-questions-poster.json")
QUESTIONS = json.loads((ROOT / "contracts" / "samples" / "questions.sample.json").read_text())
Q1 = QUESTIONS["questions"][0]

QUESTION_CASES = [
    QUESTIONS,
    {**QUESTIONS, "questions": []},
    {**QUESTIONS, "schema_version": 2},
    {"ticket": "PM-1", "schema_version": 1, "questions": []},
    {**QUESTIONS, "extra": 1},
    {**QUESTIONS, "ticket": "pm-1"},
    {**QUESTIONS, "questions": [Q1] * 11},
    {**QUESTIONS, "questions": [{**Q1, "number": 0}]},
    {**QUESTIONS, "questions": [{**Q1, "question": "short"}]},
    {**QUESTIONS, "questions": [{**Q1, "about": "x" * 201}]},
    {**QUESTIONS, "questions": [{**Q1, "colour": "red"}]},
    {**QUESTIONS, "questions": [{k: v for k, v in Q1.items() if k != "about"}]},
    {**QUESTIONS, "questions": "none"},
]


@needs_node
def test_w6_contract_copy_agrees_with_the_python_validator():
    from validate_contract import ContractError, validate

    reads = [{"found": True, "data": case} for case in QUESTION_CASES]
    runs = [{"run_id": str(i)} for i in range(len(QUESTION_CASES))]
    code = code_of(W6, "Check questions").replace("$input.all()", json.dumps([{"json": r} for r in reads]))
    out = run_code(code, {}, {"New runs": runs})
    for case, result in zip(QUESTION_CASES, out):
        try:
            validate("questions", copy.deepcopy(case))
            valid = True
        except ContractError:
            valid = False
        assert (result["state"] != "invalid") == valid, (case, result)


@needs_node
def test_w6_states():
    reads = [{"found": False}, {"found": True, "data": {**QUESTIONS, "questions": []}}, {"found": True, "data": QUESTIONS}]
    code = code_of(W6, "Check questions").replace("$input.all()", json.dumps([{"json": r} for r in reads]))
    out = run_code(code, {}, {"New runs": [{"run_id": "1"}, {"run_id": "2"}, {"run_id": "3"}]})
    assert [o["state"] for o in out] == ["none", "none", "to-post"]
    assert out[2]["ticket"] == "PM-1234" and len(out[2]["questions"]) == 2


@needs_node
def test_w6_new_runs_skip_handled_and_waiting():
    nodes = {"Known runs": {"handled": ["1"], "waiting": ["2"]}, "Settings": {"repo": "o/r"},
             "draft-cases runs": {"workflow_runs": [
                 {"id": 1, "status": "completed", "conclusion": "success"},
                 {"id": 2, "status": "completed", "conclusion": "success"},
                 {"id": 3, "status": "completed", "conclusion": "success"},
                 {"id": 4, "status": "completed", "conclusion": "failure"},
                 {"id": 5, "status": "in_progress", "conclusion": None}]}}
    assert run_code(code_of(W6, "New runs"), {}, nodes) == [{"repo": "o/r", "run_id": "3", "name": "questions"}]


@needs_node
def test_w6_message():
    allowed = [{"run_id": "3", "ticket": "PM-1234", "questions": list(reversed(QUESTIONS["questions"]))}]
    code = code_of(W6, "Message").replace("$input.all()", json.dumps([{"json": {"found": True, "data": {"pr_url": "https://github.com/o/r/pull/5"}}}]))
    [m] = run_code(code, {}, {"Allowed runs": allowed, "Settings": {"jira_url": "https://jira"}})
    assert m["header"] == "Questions about PM-1234 before testing" and m["kind"] == "" and m["thread_ts"] == ""
    assert m["body"].splitlines() == ["The agent found unclear acceptance criteria:",
                                      f"1. {QUESTIONS['questions'][0]['question']}", f"2. {QUESTIONS['questions'][1]['question']}"]
    assert m["todo"] == "react ✅ to add these to PM-1234 as a comment naming you. Nothing goes to Jira without ✅."
    assert [link["label"] for link in m["links"]] == ["PR 1", "Jira PM-1234"]
    assert m["legend"] == "React: ✅ Approve (send to Jira) · ↩️ Undo within 24 h"


@needs_node
def test_w6_rows_and_reports():
    checked = [{"run_id": "1", "state": "none", "ticket": ""}, {"run_id": "2", "state": "invalid", "ticket": "", "problem": "bad"},
               {"run_id": "3", "state": "to-post", "ticket": "PM-1"}, {"run_id": "4", "state": "to-post", "ticket": "PM-2"}]
    nodes = {"Check questions": checked, "Message": [{"run_id": "3"}],
             "Post": [{"posted": True, "channel": "C1", "ts": "1.2"}]}
    rows = run_code(code_of(W6, "Rows to save"), {}, nodes)
    assert [(r["run_id"], r["state"], r["ts"]) for r in rows] == [("1", "none", ""), ("2", "invalid", ""), ("3", "posted", "1.2")]
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_code(code_of(W6, "Report problems"), {}, nodes)
    assert "questions file of draft-cases run 2 is not valid: bad" in failure.value.stderr
    assert W6["settings"]["errorWorkflow"] == W0["id"]
    gate = next(n for n in W6["nodes"] if n["name"] == "To the gate")["parameters"]["jsCode"]
    assert "action: 'questions-post'" in gate


# ---------------------------------------------------------------- W3b Reactions (Story 6.4: reading reactions, 🌩️, 🙈)

W3B = workflow("w3b-reactions.json")


def test_w3b_slack_names_match_vocabulary():
    code = code_of(W3B, "First valid reaction")
    copied = json.loads(code.split("const REACTIONS = ", 1)[1].split(";\n", 1)[0])
    assert copied == {k: {"names": r["slack_names"], "valid_on": r["valid_on"]} for k, r in VOCABULARY["reactions"].items()}


def mapped(map_id=1, kind="failure", decision=None):
    return {"map_id": map_id, "channel": "C1", "ts": f"1.{map_id}", "kind": kind, "test_id": f"api:tests/t.py::test_{map_id}",
            "ticket": "PM-1" if kind == "questions" else "", "nightly_run_id": "7", "thread_ts": "1.0", "decision": decision}


def first_valid(messages, pages, members=("UQA", "UQB")):
    code = code_of(W3B, "First valid reaction").replace("$input.all()", json.dumps([{"json": {"message": {"reactions": p}}} for p in pages]))
    return run_code(code, {}, {"To check": messages, "QA members": {"members": list(members)}})


@needs_node
@pytest.mark.parametrize(
    "kind, reactions, expected",
    [
        ("failure", [{"name": "lightning", "users": ["UQA"]}], ("environment", "UQA")),
        ("failure", [{"name": "see_no_evil", "users": ["UX", "UQB"]}], ("ignore", "UQB")),
        ("failure", [{"name": "thumbsup", "users": ["UQA"]}, {"name": "lady_beetle::skin-tone-2", "users": ["UQA"]}], ("bug", "UQA")),
        ("failure", [{"name": "repeat", "users": ["UQB"]}, {"name": "see_no_evil", "users": ["UQA"]}], ("flaky", "UQB")),
        ("failure", [{"name": "lightning", "users": ["UOUTSIDER"]}], None),
        ("failure", [{"name": "white_check_mark", "users": ["UQA"]}], None),
        ("failure", [{"name": "leftwards_arrow_with_hook", "users": ["UQA"]}], None),
        ("questions", [{"name": "white_check_mark", "users": ["UQA"]}], ("approve", "UQA")),
        ("questions", [{"name": "lady_beetle", "users": ["UQA"]}], None),
        ("failure", [], None),
    ],
)
def test_w3b_first_valid_reaction(kind, reactions, expected):
    out = first_valid([mapped(kind=kind)], [reactions])
    assert ([(o["action"], o["actor_id"]) for o in out] or [None]) == [expected]


@needs_node
def test_w3b_qa_members_from_group_or_list():
    code = code_of(W3B, "QA members")
    assert run_code(code, {"ok": True, "users": ["U1", "U2"]}, {"Settings": {"qa_member_ids": " U2, U3 "}}) == [{"members": ["U1", "U2", "U3"]}]
    assert run_code(code, {"ok": False, "error": "paid_only"}, {"Settings": {"qa_member_ids": "U3"}}) == [{"members": ["U3"]}]


@needs_node
def test_w3b_decisions_and_the_two_paths():
    found = [{**mapped(1), "action": "environment", "actor_id": "UQA"}, {**mapped(2), "action": "ignore", "actor_id": "UQB"},
             {**mapped(3), "action": "bug", "actor_id": "UQA"}]
    users = [{"user": {"profile": {"email": "asha@gate6.com", "display_name": "asha"}}},
             {"user": {"profile": {}, "name": "ravi"}}, {"user": {"profile": {"email": "asha@gate6.com", "real_name": "Asha K"}}}]
    code = code_of(W3B, "Decisions").replace("$input.all()", json.dumps([{"json": u} for u in users]))
    out = run_code(code, {}, {"First valid reaction": found})
    assert [(o["action"], o["state"], o["actor_email"], o["actor_name"]) for o in out] == [
        ("environment", "handled", "asha@gate6.com", "asha"), ("ignore", "waiting-for-reason", "UQB@slack.invalid", "ravi"),
        ("bug", "handled", "asha@gate6.com", "Asha K")]
    slack_only = run_code(code_of(W3B, "Slack-only decisions").replace("$input.all()", json.dumps([{"json": o} for o in out])), {})
    assert [o["action"] for o in slack_only] == ["environment", "ignore"]


@needs_node
def test_w3b_replies_only_for_new_decisions():
    decisions = [{**mapped(1), "action": "environment", "actor_id": "UQA", "actor_name": "asha"},
                 {**mapped(2), "action": "ignore", "actor_id": "UQB", "actor_name": "ravi"},
                 {**mapped(3), "action": "environment", "actor_id": "UQA", "actor_name": "asha"}]
    code = code_of(W3B, "Replies").replace("$input.all()", json.dumps([{"json": {"id": 10}}, {"json": {"id": 11}}, {"json": {"id": None}}]))
    env, prompt = run_code(code, {}, {"Slack-only decisions": decisions})
    assert env["header"] == "Marked Environment by asha" and env["thread_ts"] == "1.0"
    assert env["body"] == "<@UQA> marked this failure 🌩️ Environment. The gate is unchanged. This will show in the daily update."
    assert env["legend"] == "↩️ within 24 h to undo"
    assert prompt["body"] == "<@UQB>, to record 🙈 Ignore, reply in this thread with a short reason. Nothing is recorded until then."


@needs_node
def test_w3b_ignore_reason_from_the_members_reply_after_the_prompt():
    waiting = [{**mapped(2, decision={"id": 11, "state": "waiting-for-reason", "actor_id": "UQB", "prompt_ts": "5.0",
                                      "actor_name": "ravi", "actor_email": "ravi@gate6.com"}), "thread": "1.0"}]
    pages = [{"messages": [{"user": "UQB", "ts": "4.0", "text": "before the prompt"}, {"user": "UQA", "ts": "6.0", "text": "not ravi"},
                           {"user": "UQB", "ts": "7.0", "text": "  Test data\nreset late  "}]}]
    code = code_of(W3B, "Reasons found").replace("$input.all()", json.dumps([{"json": p} for p in pages]))
    [found] = run_code(code, {}, {"Waiting for a reason": waiting})
    assert found["reason"] == "Test data reset late"
    code = code_of(W3B, "Ignore confirmation").replace("$input.all()", json.dumps([{"json": {"id": 11}}]))
    [msg] = run_code(code, {}, {"Reasons found": [found]})
    assert msg["body"] == '<@UQB> marked this failure 🙈 Ignore. Reason: "Test data reset late". The gate is unchanged.'
    code = code_of(W3B, "Reasons found").replace("$input.all()", json.dumps([{"json": {"messages": [{"user": "UQB", "ts": "4.0", "text": "old"}]}}]))
    assert run_code(code, {}, {"Waiting for a reason": waiting}) == []


def test_w3b_runs_one_at_a_time_and_stays_quiet_without_slack():
    lock = next(n for n in W3B["nodes"] if n["name"] == "Take the lock")["parameters"]["query"]
    assert "now() - interval '5 minutes'" in lock
    assert W3B["connections"]["Slack set up?"]["main"][1] == []
    load = next(n for n in W3B["nodes"] if n["name"] == "Load messages")["parameters"]["query"]
    assert "interval '7 days'" in load and "d.undone_at IS NULL" in load
    assert W3B["settings"]["errorWorkflow"] == W0["id"]


# ---------------------------------------------------------------- W3b Jira actions (Stories 6.4 🐞, 6.7 ✅)

BUG = workflow("reaction-file-bug.json")
SENDQ = workflow("reaction-send-questions.json")
REACTION = {"test_id": "api:tests/test_jobs.py::test_create_job", "flow_id": "job-creation", "bug_title": "Job create returns 500",
            "nightly_run_id": "7", "channel": "C1", "ts": "1.2", "actor_email": "asha@gate6.com", "actor_name": "Asha", "repo": "o/r"}
BUG_SETTINGS = {"jira_url": "https://jira", "project": "PM", "issue_type": "Bug", "label": "filed-via-qa-bot"}


def build_bug(users=({"accountId": "acc-1"},), reaction=REACTION):
    nodes = {"Reaction": reaction, "Settings": BUG_SETTINGS, "Jira user": {"statusCode": 200, "body": list(users)},
             "Nightly run": {"statusCode": 200, "body": {"run_started_at": "2026-10-03T21:00:00Z"}},
             "Slack link": {"ok": True, "permalink": "https://slack/p1"}}
    return run_code(code_of(BUG, "Build bug"), {}, nodes)[0]


@needs_node
def test_bug_fields_have_no_raw_evidence_and_set_the_reporter():
    out = build_bug()
    fields = out["with_reporter"]
    assert fields["summary"] == "Job create returns 500" and fields["labels"] == ["filed-via-qa-bot"]
    assert fields["reporter"] == {"id": "acc-1"} and "reporter" not in out["without_reporter"]
    text = json.dumps(fields["description"])
    assert "Filed via QA bot, by Asha from Slack." in text and "Nightly run: Oct 04, 2026" in text
    assert "api:tests/test_jobs.py::test_create_job" in text and "Flow: job-creation" in text
    hrefs = [m["attrs"]["href"] for p in fields["description"]["content"] for c in p["content"] for m in c.get("marks", []) if m["type"] == "link"]
    assert hrefs == ["https://github.com/o/r/actions/runs/7", "https://github.com/o/r/actions/runs/7#artifacts", "https://slack/p1"]
    unclassified = build_bug(users=(), reaction={**REACTION, "bug_title": ""})
    assert unclassified["with_reporter"]["summary"] == "Nightly failure: api:tests/test_jobs.py::test_create_job"
    assert "reporter" not in unclassified["with_reporter"]


@needs_node
def test_bug_creation_outcomes():
    created = code_of(BUG, "Created?")
    assert run_code(created, {"statusCode": 201, "body": {"key": "PM-9"}}) == [{"key": "PM-9", "retry": False}]
    refused = {"statusCode": 400, "body": {"errors": {"reporter": "Field 'reporter' cannot be set."}}}
    assert run_code(created, refused) == [{"key": "", "retry": True}]
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_code(created, {"statusCode": 400, "body": {"errors": {"issuetype": "Bad type"}}})
    assert "Jira refused the bug (400)" in failure.value.stderr
    verify = code_of(BUG, "Verify reporter")
    ok = {"statusCode": 200, "body": {"key": "PM-9", "fields": {"reporter": {"accountId": "acc-1"}}}}
    assert run_code(verify, ok, {"Build bug": {"account_id": "acc-1"}}) == [{"key": "PM-9", "reporter_ok": True}]
    assert run_code(verify, ok, {"Build bug": {"account_id": ""}})[0]["reporter_ok"] is False
    [comment] = run_code(code_of(BUG, "Filed-by comment"), {}, {"Reaction": REACTION})
    assert "Filed by Asha (asha@gate6.com) via Slack. Jira didn't accept them as Reporter. Filed via QA bot." in json.dumps(comment)


@needs_node
def test_send_questions_comment():
    reads = [{"found": True, "data": QUESTIONS}, {"found": True, "data": {"pr_url": "https://github.com/o/r/pull/5"}}]
    nodes = {"Reaction": {"ticket": "PM-1234", "source_run_id": "3", "actor_name": "Asha"}, "Read artifacts": reads,
             "Slack link": {"permalink": "https://slack/p2"}}
    [out] = run_code(code_of(SENDQ, "Build comment"), {}, nodes)
    content = out["body"]["content"]
    assert content[0]["content"][0]["text"] == "Clarification questions from QA, approved by Asha — Filed via QA bot"
    assert [i["content"][0]["content"][0]["text"] for i in content[1]["content"]] == [q["question"] for q in QUESTIONS["questions"]]
    with pytest.raises(subprocess.CalledProcessError):
        run_code(code_of(SENDQ, "Build comment"), {}, {**nodes, "Read artifacts": [{"found": False}, reads[1]]})
    result = run_code(code_of(SENDQ, "Result"), {"statusCode": 201, "body": {"id": "100"}},
                      {"Reaction": {"ticket": "PM-1234"}, "Settings": {"jira_url": "https://jira"}})
    assert result == [{"jira_key": "PM-1234", "url": "https://jira/browse/PM-1234?focusedCommentId=100"}]


@needs_node
def test_w3b_jira_decisions_are_only_bug_flaky_and_approve():
    later = datetime.fromtimestamp(datetime.now(UTC).timestamp() + 600, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    decisions = [{**mapped(1), "action": "bug"}, {**mapped(2, kind="questions"), "action": "approve"},
                 {**mapped(3), "action": "environment"}, {**mapped(4), "action": "bug", "jira_wait_until": later}]
    out = run_code(code_of(W3B, "Jira decisions").replace("$input.all()", json.dumps([{"json": d} for d in decisions])), {})
    assert [(o["map_id"], o["action_kind"]) for o in out] == [(1, "bug"), (2, "approve")]


@needs_node
@pytest.mark.parametrize("value, allowed", [("true", True), ("false", False), ("TRUE", False), (None, False)])
def test_w3b_jira_writes_follow_their_own_switch(value, allowed):
    read = {"value": value} if value is not None else {"error": {"message": "404"}}
    for name in ("Jira switch", "Undo Jira switch"):
        code = code_of(W3B, name).replace("$input.all()", json.dumps([{"json": {"map_id": 1}}, {"json": {"map_id": 2}}]))
        assert run_code(code, {}, {"Read JIRA_WRITES_ENABLED": read}) == [{"allowed": allowed}] * 2


def test_w3b_jira_writes_do_not_use_the_ai_gate():
    c = W3B["connections"]
    assert c["Got the lock?"]["main"][0][0]["node"] == "Read JIRA_WRITES_ENABLED"
    assert c["Read JIRA_WRITES_ENABLED"]["main"][0][0]["node"] == "Load messages"
    read = next(n for n in W3B["nodes"] if n["name"] == "Read JIRA_WRITES_ENABLED")
    assert read["parameters"]["url"].endswith("/actions/variables/JIRA_WRITES_ENABLED")
    assert read["onError"] == "continueRegularOutput" and read["alwaysOutputData"] is True
    assert c["Jira decisions"]["main"][0][0]["node"] == "Jira switch"
    assert c["Jira switch"]["main"][0][0]["node"] == "Allowed Jira actions"
    assert c["Jira undos"]["main"][0][0]["node"] == "Undo Jira switch"
    assert c["Undo Jira switch"]["main"][0][0]["node"] == "Allowed undos"
    # Only the quarantine start (a GitHub workflow) still asks the AI gate.
    gated = [n["name"] for n in W3B["nodes"] if n["parameters"].get("workflowId", {}).get("value") == "gateCheck0000001"]
    assert gated == ["Quarantine gate"]


@needs_node
def test_w3b_jira_replies():
    done = [{**mapped(1), "action": "bug", "actor_id": "UQA", "actor_name": "Asha", "jira_key": "PM-9", "url": "https://jira/browse/PM-9",
             "reporter_ok": True},
            {**mapped(2), "action": "bug", "actor_id": "UQA", "actor_name": "Asha", "jira_key": "PM-10", "url": "u", "reporter_ok": False},
            {**mapped(3, kind="questions"), "action": "approve", "actor_id": "UQB", "actor_name": "Ravi", "jira_key": "PM-1", "url": "u2"},
            {**mapped(4), "action": "bug", "actor_id": "UQA", "actor_name": "Asha", "jira_key": "PM-11", "url": "u3", "reporter_ok": True}]
    code = code_of(W3B, "Jira replies").replace("$input.all()", json.dumps([{"json": {"id": i}} for i in (1, 2, 3, None)]))
    out = run_code(code, {}, {"Jira results": done})
    assert [o["body"] for o in out] == [
        'Bug PM-9 filed by <@UQA>. Labelled "Filed via QA bot".',
        'Bug PM-10 filed by <@UQA>. Jira didn\'t accept you as Reporter, so a "Filed by Asha" comment was added.',
        "Questions added to PM-1 as a comment naming <@UQB>.",
    ]
    assert all(o["legend"] == "↩️ within 24 h to undo" for o in out)
    assert W3B["connections"]["Jira results"]["main"][0][0]["node"] == "Record Jira decision"  # recorded before the reply
    assert W3B["connections"]["Decisions"]["main"][0][0]["node"] == "Slack-only decisions"  # 🌩️ and 🙈 first


@needs_node
def test_bug_reporter_from_the_qa_leads_list_when_search_finds_nobody():
    nodes = {"Reaction": {**REACTION, "actor_email": "Asha@Gate6.com".lower()},
             "Settings": {**BUG_SETTINGS, "account_map": json.dumps({"asha@gate6.com": "acc-listed"})},
             "Jira user": {"statusCode": 200, "body": []}, "Nightly run": {"statusCode": 404, "body": {}}, "Slack link": {}}
    [out] = run_code(code_of(BUG, "Build bug"), {}, nodes)
    assert out["account_id"] == "acc-listed" and out["with_reporter"]["reporter"] == {"id": "acc-listed"}
    assert "Nightly run: unknown" in json.dumps(out["with_reporter"]["description"])
    nodes["Settings"] = {**BUG_SETTINGS, "account_map": "{broken"}
    assert run_code(code_of(BUG, "Build bug"), {}, nodes)[0]["account_id"] == ""


# ---------------------------------------------------------------- 🔁 Flaky (Story 6.6)

FLAKY = workflow("reaction-flaky.json")
INVENTORY_TEXT = (ROOT / "flows" / "inventory.yaml").read_text()


def b64(text):
    import base64

    return {"statusCode": 200, "body": {"content": base64.b64encode(text.encode()).decode()}}


def check_owner(inventory=INVENTORY_TEXT, quarantine="[]\n", test_id="api:tests/t.py::test_x", flow_id="job-creation"):
    nodes = {"Reaction": {"test_id": test_id, "flow_id": flow_id}, "Inventory": b64(inventory), "Quarantine list": b64(quarantine)}
    return run_code(code_of(FLAKY, "Check owner"), {}, nodes)[0]


@needs_node
def test_flaky_owner_from_the_inventory():
    assert check_owner() == {"stop": "owner-missing"}  # every owner is still TBD on main
    named = INVENTORY_TEXT.replace("  - id: job-creation\n    name: Job creation\n    owner: TBD", "  - id: job-creation\n    name: Job creation\n    owner: Ravi")
    assert check_owner(named) == {"stop": "", "owner": "Ravi"}
    assert check_owner(named, flow_id="login") == {"stop": "owner-missing"}
    assert check_owner(named, flow_id="unknown-flow") == {"stop": "owner-missing"}
    quarantined = '# comments\n- test_id: "api:tests/t.py::test_x"\n  owner: "Ravi"\n  jira: PM-1\n  deadline: "2026-10-19"\n'
    assert check_owner(named, quarantined) == {"stop": "already-quarantined"}


def build_task(failure=None, account_map="{}"):
    reaction = {"test_id": "ui:tests/routes.spec.ts > Routes > sorts by time", "flow_id": "routing", "nightly_run_id": "7",
                "actor_email": "asha@gate6.com", "actor_name": "Asha", "repo": "o/r"}
    nodes = {"Reaction": reaction, "Settings": {**BUG_SETTINGS, "issue_type": "Task", "account_map": account_map},
             "Check owner": {"owner": "Ravi"}, "Jira user": {"body": []}, "Slack link": {"permalink": "https://slack/p3"},
             "Failure list": {"found": failure is not None, "data": {"failures": [failure] if failure else []}}}
    return run_code(code_of(FLAKY, "Build task"), {}, nodes)[0], nodes


@needs_node
def test_flaky_owner_ticket():
    failure = {"test_id": "ui:tests/routes.spec.ts > Routes > sorts by time", "flaky_candidate": True,
               "history": [{"nightly_run_id": i, "result": r} for i, r in enumerate(["failed", "passed", "passed-on-retry", "passed"])]}
    out, _ = build_task(failure)
    fields = out["with_reporter"]
    assert fields["summary"] == "Flaky test: ui:tests/routes.spec.ts > Routes > sorts by time"
    assert fields["issuetype"] == {"name": "Task"} and fields["labels"] == ["filed-via-qa-bot"]
    expected_deadline = datetime.fromtimestamp(datetime.now(UTC).timestamp() + 14 * 86400, UTC).strftime("%Y-%m-%d")
    assert fields["duedate"] == out["deadline"] == expected_deadline
    assert out["evidence"] == "Failed 2 of the last 4 nights, passed on retry."
    text = json.dumps(fields["description"])
    assert "Owner: Ravi (from the flow inventory)." in text and "Marked flaky by Asha. Failed 2 of the last 4 nights" in text
    assert "the test keeps gating until QA merges it" in text
    no_history, _ = build_task()
    assert no_history["evidence"].startswith("No retry pass or earlier failure recorded")


@needs_node
def test_flaky_result_is_a_valid_quarantine_request():
    from validate_contract import validate

    built, nodes = build_task({"test_id": "ui:tests/routes.spec.ts > Routes > sorts by time", "flaky_candidate": True, "history": []})
    nodes.update({"Build task": built, "Verify reporter": {"key": "PM-77", "reporter_ok": True}})
    [out] = run_code(code_of(FLAKY, "Result"), {}, nodes)
    assert out["jira_key"] == "PM-77" and out["stop"] == ""
    validate("quarantine-request", out["request"])
    assert out["request"]["owner"] == "Ravi" and out["request"]["marked_by"] == "asha@gate6.com"


@needs_node
def test_w3b_flaky_replies_and_queue():
    base = {**mapped(1), "action": "flaky", "actor_id": "UQA", "actor_name": "Asha", "flow_id": "job-creation"}
    done = [{**base, "stop": "", "jira_key": "PM-77", "url": "https://jira/browse/PM-77", "request": {"jira_key": "PM-77"}},
            {**base, "map_id": 2, "stop": "owner-missing", "jira_key": "", "url": ""},
            {**base, "map_id": 3, "stop": "already-quarantined", "jira_key": "", "url": ""}]
    rows = [{"json": {"id": i}} for i in (1, 2, 3)]
    out = run_code(code_of(W3B, "Jira replies").replace("$input.all()", json.dumps(rows)), {}, {"Jira results": done})
    assert out[0]["body"] == "Quarantine requested by <@UQA>. Owner ticket PM-77 created.\nThe test keeps gating until QA merges the quarantine PR."
    assert out[1]["body"].startswith("<@UQA>: Nothing was created: the flow `job-creation` has no owner in the flow inventory.")
    assert out[2]["body"] == "<@UQA>: Nothing was created: this test is already in the quarantine list."
    queued = run_code(code_of(W3B, "To queue"), {}, {"Jira results": done, "Record Jira decision": [{"id": 1}, {"id": 2}, {"id": None}]})
    assert [q["jira_key"] for q in queued] == ["PM-77"]


@needs_node
def test_w3b_due_quarantines_go_through_the_gate():
    due = [{"queue_id": 5, "jira_key": "PM-77", "payload": json.dumps({"jira_key": "PM-77", "quarantine_request": {"test_id": "t"}})},
           {"queue_id": 6, "jira_key": "PM-78", "payload": {"jira_key": "PM-78", "quarantine_request": {"test_id": "u"}}}]
    gate_in = run_code(code_of(W3B, "Quarantines to the gate").replace("$input.all()", json.dumps([{"json": d} for d in due])), {})
    assert [(g["action"], g["workflow"], g["target"]) for g in gate_in] == [("dispatch", "quarantine", "PM-77"), ("dispatch", "quarantine", "PM-78")]
    code = code_of(W3B, "Allowed quarantines").replace("$input.all()", json.dumps([{"json": {"allowed": False}}, {"json": {"allowed": True}}]))
    assert [a["queue_id"] for a in run_code(code, {}, {"Due quarantines": due})] == [6]
    positions = {n["name"]: n["position"] for n in W3B["nodes"]}
    assert positions["To queue"][1] < positions["Jira replies"][1]  # queued before the reply can fail


# ---------------------------------------------------------------- ↩️ Undo (Story 6.8)

UNDO = workflow("reaction-undo.json")


def ago(hours):
    return datetime.fromtimestamp(datetime.now(UTC).timestamp() - hours * 3600, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@needs_node
def test_used_reactions_dont_count_again():
    m = {**mapped(1), "used": [{"action": "bug", "actor_id": "UQA", "undone_by": "UQA"}]}
    reactions = [{"name": "lady_beetle", "users": ["UQA"]}, {"name": "lightning", "users": ["UQA"]}]
    [out] = first_valid([m], [reactions])
    assert (out["action"], out["actor_id"]) == ("environment", "UQA")
    [out] = first_valid([m], [[{"name": "lady_beetle", "users": ["UQA", "UQB"]}]])
    assert (out["action"], out["actor_id"]) == ("bug", "UQB")


def undo_candidate(action="bug", hours=1, used=(), noted=False, jira_key="PM-9", wait=None):
    decision = {"id": 40, "action": action, "state": "handled", "actor_id": "UQA", "jira_key": jira_key, "link": "https://jira/browse/PM-9",
                "handled_at": ago(hours), "undo_closed_noted": noted, "undo_wait_until": wait}
    return {**mapped(1), "decision": decision, "used": list(used)}


def undo_found(candidate, reactions):
    code = code_of(W3B, "Undo found").replace("$input.all()", json.dumps([{"json": {"message": {"reactions": reactions}}}]))
    return run_code(code, {}, {"Undo candidates": [candidate], "QA members": {"members": ["UQA", "UQB"]}})


@needs_node
def test_undo_window_members_and_used_undos():
    undo = [{"name": "leftwards_arrow_with_hook", "users": ["UQB"]}]
    [u] = undo_found(undo_candidate(hours=23), undo)
    assert (u["mode"], u["undo_actor"]) == ("undo", "UQB")
    [u] = undo_found(undo_candidate(hours=25), undo)
    assert u["mode"] == "closed"
    assert undo_found(undo_candidate(hours=25, noted=True), undo) == []  # "closed" is said once
    assert undo_found(undo_candidate(), [{"name": "leftwards_arrow_with_hook", "users": ["UOUTSIDER"]}]) == []
    assert undo_found(undo_candidate(used=[{"action": "bug", "actor_id": "UQA", "undone_by": "UQB"}]), undo) == []
    assert undo_found(undo_candidate(), [{"name": "lady_beetle", "users": ["UQB"]}]) == []
    later = datetime.fromtimestamp(datetime.now(UTC).timestamp() + 600, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert undo_found(undo_candidate(wait=later), undo) == []


@needs_node
def test_undo_routes_jira_and_local_undos():
    undos = [{**undo_candidate("bug"), "mode": "undo"}, {**undo_candidate("environment", jira_key=""), "mode": "undo"},
             {**undo_candidate("flaky", jira_key=""), "mode": "undo"}, {**undo_candidate("approve", jira_key="PM-1"), "mode": "undo"},
             {**undo_candidate("bug"), "mode": "closed"}]
    jira = run_code(code_of(W3B, "Jira undos").replace("$input.all()", json.dumps([{"json": u} for u in undos])), {})
    assert [j["decision"]["action"] for j in jira] == ["bug", "approve"]
    full = [{**u, "undo_actor": "UQB", "undo_name": "Ravi", "undo_email": "ravi@gate6.com"} for u in undos]
    nodes = {"Undos": full, "Allowed undos": [{**full[0], "action": "bug", "jira_key": "PM-9"}],
             "Reverse in Jira": [{"what": "PM-9 marked as undone in Jira (moved to Won't Do)"}]}
    results = run_code(code_of(W3B, "Undo results"), {}, nodes)
    assert [r["what"] for r in results] == ["The 🌩️ Environment decision was marked reversed", "The 🔁 Flaky reaction was marked reversed",
                                            "PM-9 marked as undone in Jira (moved to Won't Do)"]
    code = code_of(W3B, "Undo replies").replace("$input.all()", json.dumps([{"json": {"id": 40}}, {"json": {"id": None}}, {"json": {"id": 41}}]))
    replies = run_code(code, {}, {"Undo results": results})
    assert [r["body"] for r in replies] == [
        "Undone by <@UQB>. The 🌩️ Environment decision was marked reversed. Nothing was deleted.\nYou can now react again on the message above.",
        "Undone by <@UQB>. PM-9 marked as undone in Jira (moved to Won't Do). Nothing was deleted.\nYou can now react again on the message above.",
    ]


@needs_node
def test_undo_too_late_reply():
    closed = [{**undo_candidate("bug", hours=30), "mode": "closed"}, {**undo_candidate("ignore", hours=30, jira_key=""), "mode": "closed"}]
    code = code_of(W3B, "Closed replies").replace("$input.all()", json.dumps([{"json": {"id": 40}}, {"json": {"id": 41}}]))
    out = run_code(code, {}, {"Too late": closed})
    assert [o["body"] for o in out] == [
        "Undo is closed for this message (more than 24 hours). Ask the QA lead to change PM-9 in Jira by hand.",
        "Undo is closed for this message (more than 24 hours). Ask the QA lead to change the 🙈 Ignore decision by hand.",
    ]


@needs_node
def test_undo_in_jira_never_deletes():
    pick = code_of(UNDO, "Pick transition")
    settings = {"close_names": "Won't Do,Cancelled,Canceled,Closed,Done"}
    transitions = {"statusCode": 200, "body": {"transitions": [{"id": "11", "name": "Start", "to": {"name": "In Progress"}},
                                                                {"id": "31", "name": "Finish", "to": {"name": "Done"}},
                                                                {"id": "41", "name": "Cancel", "to": {"name": "Cancelled"}}]}}
    nodes = {"Settings": settings, "Undo": {"jira_key": "PM-9"}}
    assert run_code(pick, transitions, nodes) == [{"transition_id": "41", "transition_name": "Cancelled"}]
    assert run_code(pick, {"statusCode": 200, "body": {"transitions": [{"id": "11", "to": {"name": "In Progress"}}]}}, nodes) == [
        {"transition_id": "", "transition_name": ""}]
    for action, words in (("bug", "Undone by Ravi via Slack within 24 hours of filing. Nothing was deleted."),
                          ("approve", "These clarification questions were withdrawn by Ravi via Slack.")):
        [c] = run_code(code_of(UNDO, "Undo comment"), {}, {"Undo": {"action": action, "actor_name": "Ravi"}})
        assert words in json.dumps(c, ensure_ascii=False)
    result = code_of(UNDO, "Result")
    assert run_code(result, {}, {"Undo": {"action": "flaky", "jira_key": "PM-7"}, "Pick transition": {"transition_name": "Won't Do"},
                                 "Find the PR": {"pr": 12}}) == [
        {"what": "PM-7 marked as undone in Jira (moved to Won't Do), and its quarantine PR was labelled undo-requested"}]
    assert run_code(result, {}, {"Undo": {"action": "approve", "jira_key": "PM-1"}}) == [
        {"what": "The questions on PM-1 were marked withdrawn in a comment"}]
    methods = {n["parameters"].get("method") for n in UNDO["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"}
    assert "DELETE" not in methods


@needs_node
def test_every_code_node_in_every_workflow_parses():
    """A syntax error (like a name declared twice) would only show up when n8n runs that node."""
    for path in sorted(WORKFLOWS.glob("*.json")):
        for n in json.loads(path.read_text())["nodes"]:
            if n["type"] != "n8n-nodes-base.code":
                continue
            script = f"new Function('$input', '$', '$json', {json.dumps(n['parameters']['jsCode'])});"
            result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
            assert result.returncode == 0, f"{path.name} / {n['name']}: {result.stderr.strip().splitlines()[-1]}"
