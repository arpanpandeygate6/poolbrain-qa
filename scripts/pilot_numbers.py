#!/usr/bin/env python3
"""Pilot numbers (Story 8.1): the three pilot measures from real data, against
the bars in Story 8.2.

1. Cases and tests accepted without major edits (bar: 70% or more), from the
   agent's PRs (head branch agent/<KEY>-cases or agent/<KEY>-tests) created
   during the pilot: merged without the `major-edits` label, merged with it, or
   closed without merging (rejected). PRs still open are listed, not counted.
2. Triage agreement (bar: 80% or more), from pilot/decisions.json: the final
   reaction (after any undo) agrees when it matches the suggested class
   (🐞 = Product defect, 🔁 = Flaky, 🌩️ = Environment); 🙈 Ignore never matches.
   Test defect and Unknown count from pilot/triage-marks.csv. Unclassified
   messages, messages with no reaction, and Test defect/Unknown without a mark
   are listed, not counted.
3. Manual regression time saved on job creation (bar: 50% or more), from
   pilot/manual-time.csv: 1 - (average pilot minutes / average baseline minutes).

Usage:
    python scripts/pilot_numbers.py --pilot-dir pilot [--prs prs.json | --fetch-prs] [--out report.md]
--fetch-prs reads the PRs from GitHub (GITHUB_TOKEN, GITHUB_REPOSITORY).
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

AGENT_BRANCH = re.compile(r"^agent/[A-Z][A-Z0-9]+-[0-9]+-(cases|tests)$")
MAJOR_EDITS = "major-edits"
BARS = {"acceptance": 70, "agreement": 80, "time_saved": 50}
REACTION_CLASS = {"bug": "product_defect", "flaky": "flaky", "environment": "environment"}
CLASS_WORDS = {"product_defect": "Product defect", "test_defect": "Test defect", "environment": "Environment",
               "flaky": "Flaky", "unknown": "Unknown"}


@dataclass
class Measure:
    name: str
    bar: int
    value: float | None
    counted: list[str] = field(default_factory=list)
    listed: list[str] = field(default_factory=list)

    @property
    def met(self) -> str:
        if self.value is None:
            return "no data"
        return "met" if self.value >= self.bar else "not met"


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def in_pilot(timestamp: str, start: str, end: str) -> bool:
    return bool(timestamp) and start <= timestamp[:10] <= end


def acceptance(prs: list[dict], start: str, end: str) -> Measure:
    accepted = with_edits = rejected = 0
    counted, listed = [], []
    for pr in sorted(prs, key=lambda p: p.get("number", 0)):
        branch = (pr.get("head") or {}).get("ref", "")
        if not AGENT_BRANCH.match(branch) or not in_pilot(pr.get("created_at", ""), start, end):
            continue
        labels = {label.get("name") for label in pr.get("labels", [])}
        line = f"[#{pr['number']}]({pr['html_url']}) `{branch}`"
        if pr.get("state") == "open":
            listed.append(f"{line}: still open, not counted")
        elif pr.get("merged_at"):
            if MAJOR_EDITS in labels:
                with_edits += 1
                counted.append(f"{line}: accepted with major edits")
            else:
                accepted += 1
                counted.append(f"{line}: accepted without major edits")
        else:
            rejected += 1
            counted.append(f"{line}: rejected (closed without merging)")
    total = accepted + with_edits + rejected
    m = Measure("Cases and tests accepted without major edits", BARS["acceptance"], pct(accepted, total), counted, listed)
    m.counted.insert(0, f"{accepted} accepted without major edits, {with_edits} with major edits, {rejected} rejected, of {total}")
    return m


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def agreement(decisions: list[dict], marks: list[dict]) -> Measure:
    marked = {(str(m["nightly_run_id"]), m["test_id"]): m["agree"].lower() for m in marks if m.get("agree")}
    agree = total = 0
    counted, listed = [], []
    for d in decisions:
        key = (str(d.get("nightly_run_id")), d.get("test_id", ""))
        cls, reaction = d.get("suggested_class") or "", d.get("final_reaction") or ""
        name = f"`{d.get('test_id')}` (nightly {d.get('nightly_run_id')})"
        if not cls:
            listed.append(f"{name}: unclassified, not counted")
        elif cls in ("test_defect", "unknown"):
            if key not in marked:
                listed.append(f"{name}: {CLASS_WORDS[cls]} without a QA mark in triage-marks.csv, not counted")
                continue
            total += 1
            ok = marked[key] in ("yes", "agree", "y", "true")
            agree += ok
            counted.append(f"{name}: {CLASS_WORDS[cls]}, QA marked {'agree' if ok else 'disagree'}")
        elif not reaction:
            listed.append(f"{name}: {CLASS_WORDS.get(cls, cls)}, no reaction, not counted")
        else:
            total += 1
            ok = REACTION_CLASS.get(reaction) == cls
            agree += ok
            counted.append(f"{name}: suggested {CLASS_WORDS.get(cls, cls)}, final reaction {reaction}: {'agree' if ok else 'disagree'}")
    m = Measure("Triage agreement", BARS["agreement"], pct(agree, total), counted, listed)
    m.counted.insert(0, f"{agree} of {total} agree")
    return m


def time_saved(rows: list[dict], start: str, end: str) -> Measure:
    def minutes(phase):
        return [float(r["minutes"]) for r in rows if r.get("phase") == phase and r.get("minutes")]

    baseline = minutes("baseline")
    during = [float(r["minutes"]) for r in rows if r.get("phase") == "pilot" and r.get("minutes") and start <= r.get("date", "") <= end]
    value = None
    if baseline and during:
        value = round(100 * (1 - (sum(during) / len(during)) / (sum(baseline) / len(baseline))), 1)
    summary = (f"baseline: {len(baseline)} runs, {sum(baseline) / len(baseline):.0f} min average" if baseline else "baseline: no entries") + \
              "; " + (f"pilot: {len(during)} runs, {sum(during) / len(during):.0f} min average" if during else "pilot: no entries")
    return Measure("Manual regression time saved on job creation", BARS["time_saved"], value, [summary])


def report(pilot: dict, measures: list[Measure], gaps: list[dict]) -> str:
    lines = [f"# Pilot numbers: {pilot.get('start') or '?'} to {pilot.get('end') or '?'}", "",
             f"Major-edit rule: {pilot.get('major_edit_rule', '')}", "",
             "| Measure | Result | Bar | |", "|---|---|---|---|"]
    for m in measures:
        result = f"{m.value}%" if m.value is not None else "no data"
        lines.append(f"| {m.name} | {result} | {m.bar}% or more | **{m.met}** |")
    for m in measures:
        lines += ["", f"## {m.name}", "", *[f"- {c}" for c in m.counted]]
        if m.listed:
            lines += ["", "Listed, not counted:", "", *[f"- {item}" for item in m.listed]]
    lines += ["", "## Gaps in the data", ""]
    lines += [f"- {g['from']} to {g['to']}: {g['what']}" for g in gaps] or ["- None recorded."]
    return "\n".join(lines) + "\n"


def fetch_prs(token: str, repository: str) -> list[dict]:
    prs, page = [], 1
    while True:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/pulls?state=all&per_page=100&page={page}",
            headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.loads(response.read())
        prs += batch
        if len(batch) < 100:
            return prs
        page += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The pilot's three measures against their bars.")
    parser.add_argument("--pilot-dir", type=Path, default=Path(__file__).resolve().parent.parent / "pilot")
    parser.add_argument("--prs", type=Path, help="the PRs as JSON (GitHub's pulls list)")
    parser.add_argument("--fetch-prs", action="store_true", help="read the PRs from GitHub")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    pilot = yaml.safe_load((args.pilot_dir / "pilot.yaml").read_text(encoding="utf-8")) or {}
    start, end = str(pilot.get("start") or ""), str(pilot.get("end") or "")
    if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", end)):
        print("pilot/pilot.yaml needs the start and end dates (YYYY-MM-DD) first.")
        return 1
    if args.fetch_prs:
        prs = fetch_prs(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
    else:
        prs = json.loads(args.prs.read_text(encoding="utf-8")) if args.prs else []
    decisions_file = args.pilot_dir / "decisions.json"
    decisions = json.loads(decisions_file.read_text(encoding="utf-8")) if decisions_file.exists() else []

    measures = [acceptance(prs, start, end),
                agreement(decisions, read_csv(args.pilot_dir / "triage-marks.csv")),
                time_saved(read_csv(args.pilot_dir / "manual-time.csv"), start, end)]
    text = report(pilot, measures, read_csv(args.pilot_dir / "gaps.csv"))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
