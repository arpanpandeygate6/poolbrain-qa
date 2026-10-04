<!-- Title: [<KEY>] Tests: <ticket title in a few words> -->

## Summary
API tests with SQL checks for the merged cases in `cases/<KEY>.md`.

## What changed
- `api-tests/tests/<file>.py`: <N> tests, flow `<flow-id>`
- `flows/inventory.yaml`: the new tests mapped to business rules <rule IDs>

## How it was checked
- `ci`: runs automatically (lint, flow tags, contracts, case files, type check).
- UAT: **not run yet.** It runs only after a QA member reviews and starts it.
- On the laptop: flow tags <OK/FAILED>, pytest collection <OK/FAILED>, type check <OK/FAILED>, new tests on UAT <N passed, N failed / not run: reason>.

## Where the product differs from the cases
<"None." or, per failing test: the case ID, what the case expects and what UAT did. The test was left as written; it was not weakened.>

## What the reviewer must do
1. Review every line. Approve the PR.
2. Actions → `uat-pr` → Run workflow → paste this PR's head commit SHA.
3. Merge when `ci` and `uat-pr` are both green on that commit.

## Links
Jira <KEY> · Case file `cases/<KEY>.md`
