#!/usr/bin/env python3
"""Checks that every n8n workflow holding a copy of the masking patterns pins the
current scripts/masking-patterns.json (Story 6.1, AR-15).

A workflow pins its copy with a line `MASKING_PATTERNS_SHA256 = '<sha256 of the
file's bytes>'` in a Code node. Changing the patterns therefore means updating
that copy and its hash in the same PR.

Usage: python scripts/check_masking_hash.py      Exit code 0 when all match.
"""

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = ROOT / "scripts" / "masking-patterns.json"
WORKFLOWS = ROOT / "n8n" / "workflows"
PIN = re.compile(r"MASKING_PATTERNS_SHA256 = '([0-9a-f]{64})'")


def patterns_hash(path: Path = PATTERNS) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(patterns: Path = PATTERNS, workflows: Path = WORKFLOWS) -> list[str]:
    """Problems found, one readable line each (empty when all pins match)."""
    current = patterns_hash(patterns)
    problems = []
    for path in sorted(workflows.glob("*.json")):
        for pinned in PIN.findall(path.read_text(encoding="utf-8")):
            if pinned != current:
                problems.append(
                    f"{path.name} pins masking patterns {pinned[:12]}…, but scripts/masking-patterns.json is "
                    f"{current[:12]}…. Update the copy in that workflow and its MASKING_PATTERNS_SHA256 in this PR."
                )
    return problems


def main() -> int:
    pinned = [p.name for p in sorted(WORKFLOWS.glob("*.json")) if PIN.search(p.read_text(encoding="utf-8"))]
    problems = check()
    for problem in problems:
        print(f"FAILED: {problem}")
    if not problems:
        if pinned:
            print(f"OK: {', '.join(pinned)} pin the current masking patterns ({patterns_hash()[:12]}…).")
        else:
            print("OK: no n8n workflow holds a copy of the masking patterns yet.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
