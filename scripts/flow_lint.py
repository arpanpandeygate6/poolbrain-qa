#!/usr/bin/env python3
"""Flow-tag linter (AD-7, FR-12, FR-18).

Checks that every test names exactly one flow defined in flows/inventory.yaml:
pytest tests under api-tests/tests/ with @pytest.mark.flow("<id>"), Playwright
specs under ui-tests/tests/ with the tag @flow:<id>. Prints the number of tests
per flow and lists skipped and fixme tests, which count as not covered.

Tests are found by the tools themselves (pytest --collect-only and
playwright test --list), so it needs the api-tests Python packages and
`npm ci` in ui-tests. It never runs a test and needs no credentials.

Usage (from the repo root):
    api-tests/.venv/bin/python scripts/flow_lint.py

Exit code 0 when every test is tagged with one known flow, 1 otherwise.
With --json PATH it also writes every test's ID, suite, flows and skip/fixme
status, for the run summary and the coverage report.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LAYERS = ("api", "db", "ui")
FLOW_TAG_PREFIX = "flow:"  # Playwright reports tags without the leading @
TOOL_TIMEOUT = 300


class LintError(Exception):
    """The check could not run: a malformed inventory or a tool that failed to list tests."""


@dataclass
class TestCase:
    test_id: str
    suite: str  # "api" or "ui"
    flows: list[str]
    status: str = ""  # "", "skipped" or "fixme"
    problem: str = ""  # a malformed flow tag found while collecting


def load_inventory(path: Path) -> list[str]:
    """Return the flow IDs in the inventory, or raise LintError naming the file and problem."""
    name = f"{path.parent.name}/{path.name}"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LintError(f"{name}: file not found")
    except yaml.YAMLError as e:
        raise LintError(f"{name}: invalid YAML: {e}")

    if not isinstance(data, dict) or not isinstance(data.get("flows"), list):
        raise LintError(f"{name}: must be a mapping with a 'flows' list")
    if not _is_text(data.get("qa_lead")):
        raise LintError(f"{name}: 'qa_lead' must name the QA lead who owns this file")

    flow_ids = []
    for index, flow in enumerate(data["flows"], start=1):
        if not isinstance(flow, dict):
            raise LintError(f"{name}: flow #{index} must be a mapping")
        flow_id = flow.get("id")
        if not isinstance(flow_id, str) or not KEBAB_CASE.match(flow_id):
            raise LintError(f"{name}: flow #{index} ID {flow_id!r} is not kebab-case (for example job-creation)")
        if flow_id in flow_ids:
            raise LintError(f"{name}: duplicate flow ID '{flow_id}'")
        for field in ("name", "owner"):
            if not _is_text(flow.get(field)):
                raise LintError(f"{name}: flow '{flow_id}' needs a '{field}'")
        layers = flow.get("layers")
        if not isinstance(layers, list) or not layers or any(layer not in LAYERS for layer in layers):
            raise LintError(f"{name}: flow '{flow_id}' 'layers' must be a non-empty list of {', '.join(LAYERS)}")
        if not isinstance(flow.get("ui_top10", False), bool):
            raise LintError(f"{name}: flow '{flow_id}' 'ui_top10' must be true or false")
        _check_rules(name, flow_id, flow.get("rules"))
        flow_ids.append(flow_id)
    return flow_ids


def _check_rules(name: str, flow_id: str, rules) -> None:
    if not isinstance(rules, list):
        raise LintError(f"{name}: flow '{flow_id}' 'rules' must be a list")
    rule_ids = set()
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict) or not _is_text(rule.get("id")):
            raise LintError(f"{name}: flow '{flow_id}' rule #{index} needs an 'id'")
        if rule["id"] in rule_ids:
            raise LintError(f"{name}: flow '{flow_id}' has duplicate rule ID '{rule['id']}'")
        rule_ids.add(rule["id"])
        tests = rule.get("tests")
        if not isinstance(tests, list) or not all(_is_text(t) for t in tests):
            raise LintError(f"{name}: flow '{flow_id}' rule '{rule['id']}' 'tests' must be a list of test IDs")


def _is_text(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def collect_api_tests(api_dir: Path) -> list[TestCase]:
    """List pytest tests with their flow markers, using pytest's own collection."""
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "tests.json"
        env = {
            **os.environ,
            "POOLBRAIN_ENV": "uat",
            "FLOW_LINT_OUTPUT": str(output),
            "PYTHONPATH": os.pathsep.join(filter(None, [str(SCRIPTS_DIR), os.environ.get("PYTHONPATH")])),
        }
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q",
             "-p", "flow_lint_pytest_plugin", "-p", "no:cacheprovider"],
            cwd=api_dir, env=env, capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False,
        )
        # 5 means no tests were collected.
        if result.returncode not in (0, 5):
            raise LintError(
                f"pytest could not collect the API tests (exit {result.returncode}):\n"
                + _tail(result.stdout + result.stderr)
            )
        records = json.loads(output.read_text(encoding="utf-8")) if output.exists() else []

    tests: dict[str, TestCase] = {}
    for record in records:
        # Parametrized cases share one test ID: drop the "[param]" suffix.
        test_id = "api:" + record["nodeid"].split("[", 1)[0]
        flows, problem = [], ""
        for args in record["flows"]:
            if len(args) == 1 and isinstance(args[0], str):
                flows.append(args[0])
            else:
                problem = 'flow marker must name exactly one flow ID, like flow("job-creation")'
        test = tests.setdefault(test_id, TestCase(test_id, "api", []))
        test.flows = _unique(test.flows + flows)
        test.problem = test.problem or problem
        if record["skipped"]:
            test.status = "skipped"
    return list(tests.values())


def collect_ui_tests(ui_dir: Path) -> list[TestCase]:
    """List Playwright tests with their tags and skip/fixme annotations, using playwright test --list."""
    playwright = ui_dir / "node_modules" / ".bin" / "playwright"
    if not playwright.exists():
        raise LintError(f"Playwright is not installed in {ui_dir.name}/: run `npm ci` there first")
    env = {**os.environ, "POOLBRAIN_ENV": "uat"}
    env.pop("PLAYWRIGHT_JSON_OUTPUT_NAME", None)  # keep the JSON report on stdout
    result = subprocess.run(
        [str(playwright), "test", "--list", "--reporter=json", "--pass-with-no-tests"],
        cwd=ui_dir, env=env, capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise LintError(
            f"Playwright could not list the UI tests (exit {result.returncode}):\n"
            + _tail(result.stdout + result.stderr)
        )
    if report.get("errors"):
        messages = "\n".join(_tail(e.get("message", str(e)), lines=8) for e in report["errors"])
        raise LintError(f"Playwright could not list the UI tests:\n{messages}")

    root_dir = Path(report["config"]["rootDir"])
    tests: dict[str, TestCase] = {}

    def walk(suite: dict, titles: list[str]) -> None:
        for spec in suite.get("specs", []):
            path = (root_dir / spec["file"]).relative_to(ui_dir.resolve()).as_posix()
            test_id = " > ".join([f"ui:{path}", *titles, spec["title"]])
            flows = [tag[len(FLOW_TAG_PREFIX):] for tag in spec.get("tags", []) if tag.startswith(FLOW_TAG_PREFIX)]
            annotations = {a["type"] for t in spec.get("tests", []) for a in t.get("annotations", [])}
            status = "fixme" if "fixme" in annotations else "skipped" if "skip" in annotations else ""
            # One entry per spec, even when several projects run it.
            tests.setdefault(test_id, TestCase(test_id, "ui", _unique(flows), status))
        for child in suite.get("suites", []):
            walk(child, titles + [child["title"]] if child.get("title") else titles)

    for file_suite in report.get("suites", []):
        walk(file_suite, [])
    return list(tests.values())


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _tail(text: str, lines: int = 30) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def find_problems(flow_ids: list[str], tests: list[TestCase]) -> list[tuple[str, str]]:
    known = set(flow_ids)
    problems = []
    for test in tests:
        if test.problem:
            problems.append((test.test_id, test.problem))
        elif not test.flows:
            problems.append((test.test_id, "no flow tag"))
        elif len(test.flows) > 1:
            problems.append((test.test_id, f"more than one flow tag ({', '.join(test.flows)})"))
        elif test.flows[0] not in known:
            problems.append((test.test_id, f"unknown flow ID '{test.flows[0]}'"))
    return problems


def report(flow_ids: list[str], tests: list[TestCase], problems: list[tuple[str, str]]) -> str:
    lines = [f"Flow-tag check: {len(flow_ids)} flows in flows/inventory.yaml", ""]
    if not tests:
        lines.append("0 tests found")
    else:
        counts = Counter((t.flows[0], t.suite) for t in tests if len(t.flows) == 1)
        width = max(len(f) for f in flow_ids) if flow_ids else 4
        lines.append("Tests per flow:")
        lines.append(f"  {'flow':<{width}}  api  ui  total")
        for flow_id in flow_ids:
            api, ui = counts[(flow_id, "api")], counts[(flow_id, "ui")]
            lines.append(f"  {flow_id:<{width}}  {api:>3}  {ui:>2}  {api + ui:>5}")
        lines.append(f"{len(tests)} tests found")

    not_covered = [t for t in tests if t.status]
    if not_covered:
        lines += ["", f"Not covered: skipped or fixme ({len(not_covered)}):"]
        for test in not_covered:
            lines.append(f"  {test.test_id}  [flow: {', '.join(test.flows) or '-'}; {test.status}]")

    if problems:
        lines += ["", f"FAILED: {len(problems)} test(s) without exactly one known flow:"]
        lines += [f"  {test_id}: {reason}" for test_id, reason in problems]
    else:
        lines += ["", "OK"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=SCRIPTS_DIR.parent, help="repository root")
    parser.add_argument("--json", type=Path, help="also write the list of tests to this JSON file")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        flow_ids = load_inventory(root / "flows" / "inventory.yaml")
        tests = collect_api_tests(root / "api-tests") + collect_ui_tests(root / "ui-tests")
    except LintError as e:
        print(f"Flow-tag check FAILED: {e}", file=sys.stderr)
        return 1

    problems = find_problems(flow_ids, tests)
    print(report(flow_ids, tests, problems))
    if args.json:
        records = [
            {"test_id": t.test_id, "suite": t.suite, "flows": t.flows, "status": t.status} for t in tests
        ]
        args.json.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
