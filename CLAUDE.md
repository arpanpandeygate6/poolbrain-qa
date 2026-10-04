# PoolBrain QA: house rules for Claude Code

This repository holds PoolBrain's automated regression tests and the tooling around them. You (the agent) draft test cases and tests here; QA people review and merge every change. These rules apply on every laptop and in every GitHub workflow.

## Hard rules

1. **Never touch PROD data.** Laptops run against UAT only (`POOLBRAIN_ENV=uat`, the default). Preprod, PROD and NPP run only in CI, and only read-only `smoke` tests.
2. **Changes go only through pull requests.** Never push to `main` or merge a PR yourself.
3. **Tests call only the helpers:** `ApiClient` (`api-tests/utils/api_client.py`), `ReadReplica` (`api-tests/utils/db.py`, SELECT only) and the page objects in `ui-tests/pages/`. No raw `requests`, SQL connections or locators inside a test.
4. **Every test has exactly one flow tag** from `flows/inventory.yaml`: pytest `@pytest.mark.flow("<id>")`, Playwright `{ tag: '@flow:<id>' }`. Never invent a flow ID; if none fits, stop and ask.
5. **Never make a test pass by weakening it.** No skip, `fixme`, `xfail`, removed or looser assertions, or longer waits to hide a failure. If the product behaves differently from the case, say so plainly in your output and in the PR body.
6. **Never read, print or edit `.env` files** (`.env`, `.env.uat`, `.env.preprod`, `.env.prod`, `.env.npp`), not even through the shell. Use `.env.example` to learn variable names.
7. **No Jira, Slack, email or web tools.** Work only from what the QA member pastes in and from this repository. If you can see such a tool, stop and tell the QA member: the laptop fails the connector check (docs/runbook.md, "Laptop connector check").
8. **The existing Gate6 QA Agent is not used or changed** by this work.
9. **Don't paste ticket text beyond the acceptance criteria being tested** into case files, PRs or commits.

## Folder layout

| Folder | What lives there |
|---|---|
| `api-tests/` | Python + pytest. `tests/` holds tests, `utils/` the helpers, `conftest.py` the `api`, `logged_in_api` and `db` fixtures, `pytest.ini` the markers |
| `ui-tests/` | Playwright + TypeScript, for the top 10 flows only (`ui_top10: true` in the inventory). `tests/` holds specs, `pages/` page objects, `support/naming.ts` the naming helper |
| `cases/` | Test case files, one per Jira ticket: `cases/<KEY>.md`, plus `cases/<KEY>.questions.json` |
| `flows/` | `inventory.yaml` (the only place flow IDs and business rules are defined) and `quarantine.yaml` |
| `contracts/` | JSON schemas for handover files (`schema_version` first, snake_case fields), samples, `vocabulary.json` (all user-facing status words) |
| `scripts/` | Flow-tag linter, run summary, coverage, sanitizer, contract validator, and their tests |
| `.github/workflows/` | `ci`, `uat-pr`, `nightly`, `mock-tests`, `heartbeat-watch` |
| `.claude/commands/` | The laptop commands, for example `/draft-cases` |
| `n8n/`, `mock-poolbrain/`, `docs/` | The n8n relay, the pretend PoolBrain site, and the runbook. Leave them alone unless asked |

## Naming

- **Flow IDs:** kebab-case, from `flows/inventory.yaml` (for example `job-creation`).
- **Business rule IDs:** as in the inventory (for example `JOB-1`).
- **Test IDs:** `api:tests/<file>.py::<test name>` and `ui:tests/<file>.spec.ts > <describe> > <title>`.
- **Case IDs:** `<KEY>-01`, `<KEY>-02`, … (for example `PM-1234-01`). Each test names its case ID in its name or docstring.
- **Test data:** always `qa-auto-<run-id>-<name>`, made with `qa_auto_name()` (Python) or `qaAutoName()` (TypeScript).
- **Markers:** `regression` for business-rule tests, plus `db` when the test checks the read replica. `smoke` only for read-only release checks.
- **Branches:** `agent/<KEY>-cases` for case PRs, `agent/<KEY>-tests` for test PRs.
- **PR titles:** `[<KEY>] Cases: …` and `[<KEY>] Tests: …`, with the bodies from `.github/PULL_REQUEST_TEMPLATE/`.

## How to check your work

- Flow tags: `python scripts/flow_lint.py`
- Case files: `python scripts/case_lint.py`
- Type check (UI): `cd ui-tests && npm run typecheck`
- Contracts: `python scripts/validate_contract.py <name> <file>`
- API tests: `cd api-tests && pytest` (UAT; on the prototype, the pretend PoolBrain in `mock-poolbrain/`)
- Lint: `ruff check .`

## Writing style

Plain words and short sentences, for readers who are new to this. Times in Slack and summaries are IST; times in files are UTC ISO-8601. Status words come from `contracts/vocabulary.json`, never typed by hand.
