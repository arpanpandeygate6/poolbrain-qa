<!-- Title: [<KEY>] Fix: <summary in a few words> -->

## Summary
<What broke and why, in one or two sentences.>

## Type
<One of:>
- Locator fix (healer): the page changed; only the page object in `ui-tests/pages/` changed.
- `test.fixme` — link the filed defect: PM-____ (the reason in `test.fixme(...)` must contain this key, or `ci` fails).

## How it was checked
- The test passed on my laptop against UAT after the change (healer run, or by hand).
- `ci` runs on its own. `uat-pr`: start it after review with this PR's head commit SHA. Merge only when both are green.

## Links
Failed run · Jira <KEY>
