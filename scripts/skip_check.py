#!/usr/bin/env python3
"""Skip and healer check for `ci` (Story 4.7, AD-10).

1. A change that ADDS `test.fixme`, `test.skip`, `describe.skip`, a pytest skip or an
   xfail fails unless its reason (on the same line or the next added line) contains a
   Jira key such as PM-5678, so every skip links a filed defect. Skips already on the
   base branch are not touched. The PR still needs QA approval to merge.
2. No workflow in .github/workflows may run the Playwright healer, so healing never
   runs in CI.

Usage: python scripts/skip_check.py [--base origin/main]
Exit code 0 when both hold, 1 otherwise (each problem on its own line).
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_DIRS = ("api-tests", "ui-tests/tests", "ui-tests/pages")
SKIP = re.compile(
    r"\b(test|it|describe)(\.\w+)*\.(fixme|skip)\b|pytest\.mark\.(skip|skipif|xfail)\b|pytest\.(skip|xfail)\("
)
JIRA_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-[0-9]+\b")
HEALER = re.compile(r"init-agents|playwright-test-healer|run-test-mcp-server")


def added_lines(base: str, root: Path = ROOT) -> list[tuple[str, int, str]]:
    """(file, line number, text) of every line the change adds under the test folders."""
    diff = subprocess.run(["git", "diff", "--unified=0", "--no-color", f"{base}...HEAD", "--", *TEST_DIRS],
                          cwd=root, capture_output=True, text=True, check=True).stdout
    lines, path, number = [], "", 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("@@"):
            number = int(re.search(r"\+(\d+)", line).group(1))
        elif line.startswith("+") and path:
            lines.append((path, number, line[1:]))
            number += 1
    return lines


def skip_problems(lines: list[tuple[str, int, str]]) -> list[str]:
    problems = []
    for i, (path, number, text) in enumerate(lines):
        if not SKIP.search(text):
            continue
        following = lines[i + 1][2] if i + 1 < len(lines) and lines[i + 1][0] == path else ""
        if not JIRA_KEY.search(text) and not JIRA_KEY.search(following):
            problems.append(f"{path}:{number}: adds a skip or fixme without a Jira key in its reason "
                            f"(file the defect and name it, for example PM-5678): {text.strip()[:100]}")
    return problems


def healer_problems(root: Path = ROOT) -> list[str]:
    return [f"{path.relative_to(root)}: runs the Playwright healer; healing is for laptops only, never in CI"
            for path in sorted((root / ".github" / "workflows").glob("*.y*ml")) if HEALER.search(path.read_text(encoding="utf-8"))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check added skips and that no workflow runs the healer.")
    parser.add_argument("--base", default="origin/main", help="what the change is compared with")
    args = parser.parse_args(argv)
    problems = skip_problems(added_lines(args.base)) + healer_problems()
    for problem in problems:
        print(f"FAILED: {problem}")
    if not problems:
        print("OK: no skip or fixme added without a Jira key, and no workflow runs the healer.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
