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


def daily_update(summaries, newest_hours_ago=7, switch="true", newest_id=None):
    started = datetime.now(UTC).timestamp() - newest_hours_ago * 3600
    newest = {"id": newest_id or (summaries[0]["nightly_run_id"] if summaries else 1),
              "run_started_at": datetime.fromtimestamp(started, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    nodes = {"Nightly runs": {"workflow_runs": [newest]}, "Read AGENT_ENABLED": {"value": switch} if switch else {"error": {}}}
    if summaries:
        nodes["Read summary"] = [{"data": s} for s in summaries]
    return run_code(code_of(W4, "Build update"), {}, nodes)[0]


def test_w4_status_words_match_vocabulary():
    code = code_of(W4, "Build update")
    for key, word in VOCABULARY["test_status"].items():
        assert f"'{word}'" in code, key


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
