#!/usr/bin/env python3
"""Case-file check (Story 4.2): every cases/<KEY>.md follows the case format, so
reviewers and /generate-api-tests can rely on it.

Checks each case file for:
- YAML front matter with `ticket` (matching the file name), `flows` (IDs from
  flows/inventory.yaml), `priority` (high, medium or low) and `layer` (api, db
  or ui, or a list of them);
- the title "# <KEY> — <ticket title>" and a "Source:" line naming the ticket;
- one or more "## <KEY>-01 — <name>" sections, numbered from 01, each with
  Business rule, Preconditions, Steps and Expected (or Expected result), plus
  Layer (one of the file's layers) when the file has more than one;
- cases/<KEY>.questions.json next to it, valid against contracts/questions, and
  the pointer line "Questions sent to Slack for approval" exactly when it has questions.

Usage: python scripts/case_lint.py [--cases cases] [--inventory flows/inventory.yaml]
Exit code 0 when every file is fine, 1 otherwise (each problem on its own line).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from flow_lint import LintError, load_inventory
from validate_contract import ContractError, validate

ROOT = Path(__file__).resolve().parent.parent
KEY = re.compile(r"^[A-Z][A-Z0-9]+-[0-9]+$")
LAYERS = ("api", "db", "ui")
PRIORITIES = ("high", "medium", "low")
# Each case's labels; "Expected" may also be written "Expected result". Bold is optional.
FIELDS = {"Business rule": "Business rule", "Preconditions": "Preconditions", "Steps": "Steps",
          "Expected result": "Expected(?: result)?"}
POINTER = "Questions sent to Slack for approval"


def front_matter(text: str) -> tuple[dict | None, str]:
    """The parsed front matter and the rest of the file, or (None, text) when there is none."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        return None, text
    data = yaml.safe_load(match.group(1))
    return (data if isinstance(data, dict) else None), match.group(2)


def check_case_file(path: Path, flow_ids: list[str]) -> list[str]:
    name = f"cases/{path.name}"
    key = path.stem
    if not KEY.match(key):
        return [f"{name}: the file name must be the Jira key, for example PM-1234.md"]
    try:
        meta, body = front_matter(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return [f"{name}: the front matter is not valid YAML: {e}"]
    if meta is None:
        return [f"{name}: missing front matter (ticket, flows, priority, layer between --- lines at the top)"]

    problems = []
    if meta.get("ticket") != key:
        problems.append(f"{name}: front matter ticket {meta.get('ticket')!r} does not match the file name {key}")
    flows = meta.get("flows")
    if not isinstance(flows, list) or not flows:
        problems.append(f"{name}: front matter 'flows' must list at least one flow ID from flows/inventory.yaml")
    else:
        problems += [f"{name}: unknown flow '{f}' (not in flows/inventory.yaml)" for f in flows if f not in flow_ids]
    if meta.get("priority") not in PRIORITIES:
        problems.append(f"{name}: priority {meta.get('priority')!r} must be one of {', '.join(PRIORITIES)}")
    layers = meta.get("layer")
    layers = layers if isinstance(layers, list) else [layers]
    if not layers or any(layer not in LAYERS for layer in layers):
        problems.append(f"{name}: layer {meta.get('layer')!r} must be api, db or ui (or a list of them)")

    if not re.search(rf"^# {re.escape(key)} — \S", body, re.MULTILINE):
        problems.append(f"{name}: the title must be '# {key} — <ticket title>'")
    if not re.search(rf"^Source:.*\b{re.escape(key)}\b", body, re.MULTILINE):
        problems.append(f"{name}: needs a 'Source:' line naming {key} and the acceptance criteria tested")

    sections = re.split(r"^## ", body, flags=re.MULTILINE)[1:]
    if not sections:
        problems.append(f"{name}: has no cases (sections '## {key}-01 — <name>')")
    for number, section in enumerate(sections, start=1):
        heading = section.splitlines()[0]
        case_id = f"{key}-{number:02d}"
        if not heading.startswith(f"{case_id} — "):
            problems.append(f"{name}: case {number} heading '## {heading}' must start '## {case_id} — '")
            continue
        for field, label in FIELDS.items():
            if not label_line(section, label):
                problems.append(f"{name}: {case_id} has no '{field}:' line")
        layer = label_line(section, "Layer")
        if len(layers) > 1 and not layer:
            problems.append(f"{name}: {case_id} needs a 'Layer:' line, because the file has more than one layer")
        if layer and layer.group(1) not in layers:
            problems.append(f"{name}: {case_id} layer '{layer.group(1)}' is not one of the file's layers ({', '.join(map(str, layers))})")

    problems += check_questions(path.with_name(f"{key}.questions.json"), key, POINTER in body)
    return problems


def label_line(section: str, label: str) -> re.Match | None:
    """The line "Label: value" or "**Label:** value"; group 1 is the value's first word."""
    return re.search(rf"^(?:\*\*)?{label}:(?:\*\*)?[ \t]*(\S*)", section, re.MULTILINE)


def check_questions(path: Path, key: str, has_pointer: bool) -> list[str]:
    name = f"cases/{path.name}"
    if not path.exists():
        return [f"{name}: missing (write it with an empty 'questions' list when there are none)"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        validate("questions", data)
    except (json.JSONDecodeError, ContractError) as e:
        return [f"{name}: {e}"]
    problems = []
    if data["ticket"] != key:
        problems.append(f"{name}: ticket {data['ticket']!r} does not match {key}")
    numbers = [q["number"] for q in data["questions"]]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"{name}: questions must be numbered 1, 2, 3, … in order")
    if data["questions"] and not has_pointer:
        problems.append(f"cases/{key}.md: has questions, so it needs the line '{POINTER}'")
    if not data["questions"] and has_pointer:
        problems.append(f"cases/{key}.md: says '{POINTER}' but {name} has no questions")
    return problems


def find_problems(cases: Path, inventory: Path) -> list[str]:
    try:
        flow_ids = load_inventory(inventory)
    except LintError as e:
        return [str(e)]
    problems = []
    case_files = sorted(p for p in cases.glob("*.md") if p.name != "README.md") if cases.is_dir() else []
    for path in case_files:
        problems += check_case_file(path, flow_ids)
    keys = {p.stem for p in case_files}
    for path in sorted(cases.glob("*.questions.json")) if cases.is_dir() else []:
        if path.name.removesuffix(".questions.json") not in keys:
            problems.append(f"cases/{path.name}: has no case file next to it")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the case files in cases/.")
    parser.add_argument("--cases", type=Path, default=ROOT / "cases")
    parser.add_argument("--inventory", type=Path, default=ROOT / "flows" / "inventory.yaml")
    args = parser.parse_args(argv)
    problems = find_problems(args.cases, args.inventory)
    for problem in problems:
        print(f"FAILED: {problem}")
    if not problems:
        count = len([p for p in args.cases.glob("*.md") if p.name != "README.md"]) if args.cases.is_dir() else 0
        print(f"OK: {count} case {'file follows' if count == 1 else 'files follow'} the case format.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
