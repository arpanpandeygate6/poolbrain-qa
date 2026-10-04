---
description: Generate tests from a ticket's merged case file and open PR 2 (Story 4.3)
argument-hint: <JIRA-KEY, for example PM-1234>
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(git *), Bash(gh pr create *), Bash(command -v gh), Bash(api-tests/.venv/bin/python scripts/flow_lint.py*), Bash(api-tests/.venv/bin/python scripts/case_lint.py*), Bash(api-tests/.venv/bin/python -m pytest *), Bash(cd api-tests && .venv/bin/python -m pytest *), Bash(cd ui-tests && npm run typecheck), Bash(cd ui-tests && npx playwright test *), Bash(api-tests/.venv/bin/ruff check *)
---

Generate the tests for the merged cases of Jira ticket **$ARGUMENTS** and open PR 2. Follow `CLAUDE.md` throughout, above all: tests call only the helpers, one flow tag per test, and never weaken a test to make it pass.

## 1. Only from cases merged on `main`

1. If `$ARGUMENTS` is not a Jira key like `PM-1234`, say "Usage: /generate-api-tests PM-1234" and stop.
2. If `git status --porcelain` shows uncommitted changes, stop: "You have uncommitted changes. Commit or stash them, then run /generate-api-tests again."
3. `git fetch origin main`
4. If `git cat-file -e origin/main:cases/$ARGUMENTS.md` fails, say exactly "Cases for $ARGUMENTS are not merged on main yet. Merge PR 1 first." and stop. Change nothing.
5. `git switch -c agent/$ARGUMENTS-tests origin/main`. If that branch already exists, stop and ask the QA member whether to delete it or continue on it.

## 2. Read what to build

- Read `cases/$ARGUMENTS.md`: its flows, layers and every case (`$ARGUMENTS-01`, …). Use only the merged file.
- Read the flows in `flows/inventory.yaml` (business rules, and whether the flow has `ui_top10: true`).
- Read the existing tests and helpers you will follow: `api-tests/tests/`, `api-tests/conftest.py` (fixtures `api`, `logged_in_api`, `db`), `api-tests/utils/` (`ApiClient`, `ReadReplica`, `qa_auto_name`), and for UI `ui-tests/tests/`, `ui-tests/pages/`, `ui-tests/support/naming.ts`.

## 3. Write the tests

**Cases with layer `api` or `db`** → pytest in `api-tests/tests/test_<flow or topic>.py` (a new file, or the flow's existing file):
- One test per case, named after what it checks, with the case ID in its docstring: `"""PM-1234-01: <case name>."""`.
- Decorators: `@pytest.mark.regression`, `@pytest.mark.db` when it checks the read replica, and `@pytest.mark.flow("<flow-id>")` from the case file.
- Call only the `logged_in_api`/`api` and `db` fixtures. If `ApiClient` lacks a call you need, add a small method to `api-tests/utils/api_client.py` in the same style; never use `requests` or SQL connections in a test. SQL goes through `db.query` or `db.wait_for_row` (SELECT only).
- Name every record the test creates with `qa_auto_name(...)`.
- Assert exactly what the case's Expected line says, with a plain failure message.

**Cases with layer `ui`** → only when the flow has `ui_top10: true`: a Playwright spec in `ui-tests/tests/`, with locators only in page objects under `ui-tests/pages/` (add or extend one), the tag `{ tag: '@flow:<flow-id>' }`, `qaAutoName(...)` for data, and the case ID in the test title or a comment. For a `ui` case on a flow without `ui_top10`, write no UI test; list it in the PR body under "Where the product differs from the cases" as "not automated: not a top-10 UI flow".

Never add `skip`, `fixme`, `xfail`, looser assertions or longer waits to get a pass.

## 4. Map the tests to the business rules

In `flows/inventory.yaml`, add each new test ID under the business rule its case checks (`api:tests/<file>.py::<test name>`, `ui:tests/<file>.spec.ts > <describe> > <title>`), so coverage counts it once merged. If a case checks a rule the flow doesn't have yet, add the rule with the next ID (for example `JOB-3`) and the case's Business rule line as its description. Don't change or remove other rules.

## 5. Check on the laptop

Run each and keep the results for the PR:
1. `api-tests/.venv/bin/python scripts/flow_lint.py` (flow tags)
2. `cd api-tests && .venv/bin/python -m pytest --collect-only -q` (collection)
3. `cd ui-tests && npm run typecheck` (type check), and `api-tests/.venv/bin/ruff check .`
4. The new tests on UAT: `cd api-tests && .venv/bin/python -m pytest <new file> -q` (and `cd ui-tests && npx playwright test <new spec>` for UI). This uses `api-tests/.env.uat`, which you must not read. If UAT can't be reached, record "not run: UAT not reachable" and go on.

Fix your own mistakes (syntax, imports, wrong helper use, flow tags) and run the checks again. **When a test fails because the product behaves differently from the case, leave the test as written.** Say so in your output and in the PR body: the case ID, what the case expects and what UAT did.

## 6. Open PR 2

1. Commit the tests, any helper or page-object changes and `flows/inventory.yaml` with the message `[$ARGUMENTS] Tests: <ticket title in a few words>`.
2. `git push -u origin agent/$ARGUMENTS-tests`
3. Fill in `.github/PULL_REQUEST_TEMPLATE/tests.md`. Keep "UAT: **not run yet.** It runs only after a QA member reviews and starts it.": the laptop run doesn't count as the UAT check.
4. If `command -v gh` finds the GitHub CLI, run `gh pr create --base main --head agent/$ARGUMENTS-tests --title "[$ARGUMENTS] Tests: <title>" --body "<filled template>"`. Otherwise print the filled body and the link `https://github.com/<owner>/<repo>/compare/main...agent/$ARGUMENTS-tests?quick_pull=1` (owner and repo from `git remote get-url origin`) and ask the QA member to open the PR there.

## 7. Finish

Print:

```
Generated <N> tests for $ARGUMENTS (<files>).
Laptop checks: <one line of results>
Opened PR 2: <PR link, or "open it here: <compare link>">
Next: review PR 2, then start uat-pr after review with its head commit SHA.
```

If any test failed because the product differs from a case, list those cases before the last line.
