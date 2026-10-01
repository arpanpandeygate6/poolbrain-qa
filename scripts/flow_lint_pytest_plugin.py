"""pytest plugin used by flow_lint.py: writes each collected test's flow and skip markers to JSON.

Loaded with `-p flow_lint_pytest_plugin`; the output path comes from FLOW_LINT_OUTPUT.
"""

import json
import os


def pytest_collection_finish(session):
    records = []
    for item in session.items:
        records.append(
            {
                "nodeid": item.nodeid,
                "flows": [list(marker.args) for marker in item.iter_markers("flow")],
                "skipped": any(item.iter_markers("skip")) or any(item.iter_markers("skipif")),
            }
        )
    with open(os.environ["FLOW_LINT_OUTPUT"], "w", encoding="utf-8") as f:
        json.dump(records, f)
