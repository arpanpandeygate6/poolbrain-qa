# PoolBrain QA Automation

Automated regression tests for PoolBrain. Following approach B from the PRD, business rules are tested through the Flask API with SQL checks on read replicas, and UI tests cover only the top 10 flows.

```
poolbrain-qa/
├── .github/workflows/  ci (secret-free checks), mock-tests (tests on every PR), uat-pr ("Run UAT tests" button)
├── .github/actions/    Shared steps: start the pretend site, build and upload the test report
├── mock-poolbrain/     Pretend PoolBrain (login page and API) while there is no UAT access
├── n8n/                n8n + PostgreSQL in Docker, backups and restore drill; workflows/ for exported JSON
├── docs/runbook.md     Decisions and procedures (GitHub plan, merge gate)
├── api-tests/          Python + pytest: API tests and read-replica SQL checks
│   ├── config.py       Environment selection and settings (uat, preprod, prod, npp)
│   ├── conftest.py     Fixtures (api, db) and the read-only guard
│   ├── pytest.ini      Markers and default options
│   ├── utils/          ApiClient (requests) and ReadReplica (SELECT-only SQL)
│   └── tests/          Tests go here
├── ui-tests/           Playwright + TypeScript: top 10 UI flows
│   ├── playwright.config.ts
│   ├── pages/          Page objects go here
│   └── tests/          Specs go here
├── flows/
│   ├── inventory.yaml  Business flows: the only place flow IDs are defined
│   └── quarantine.yaml Quarantined tests (owner, Jira key, deadline)
└── scripts/            Flow-tag linter and its tests
```

## Pretend PoolBrain (no UAT access yet)

Until we have UAT access, the tests run against `mock-poolbrain/`, a small Flask app with a PoolBrain-style login page and login API. It proves the test setup works; it does not test PoolBrain itself. Its API path and response fields are a best guess, to be corrected against real UAT.

1. In `api-tests/.env.uat` and `ui-tests/.env.uat` (copied from `.env.example`), set:
   - `API_BASE_URL=http://127.0.0.1:5050/api` and `BASE_URL=http://127.0.0.1:5050`
   - any made-up `OFFICE_ADMIN_EMAIL` / `OFFICE_ADMIN_PASSWORD` and `API_USER_EMAIL` / `API_USER_PASSWORD`. The pretend site accepts whatever you set here.
2. Start it, and leave the terminal open:
   ```bash
   api-tests/.venv/bin/pip install -r mock-poolbrain/requirements.txt   # once
   api-tests/.venv/bin/python mock-poolbrain/app.py                     # http://127.0.0.1:5050/login
   ```
3. Run the suites in another terminal, as below.

To switch to real UAT later, change the URLs and accounts in the two `.env.uat` files and check `LOGIN_PATH` in `api-tests/utils/api_client.py` and the locators in `ui-tests/pages/LoginPage.ts`.

On GitHub, the `mock-tests` workflow does all of this on every PR with freshly made-up passwords, and uploads the reports.

## Environments

Choose an environment with `POOLBRAIN_ENV` (or `--env` for pytest): `uat` (default), `preprod`, `prod` or `npp`.

Locally, only UAT runs. Its settings come from `.env.uat` in each folder; copy that folder's `.env.example` to create it. The file is gitignored. Preprod, PROD and NPP credentials exist only as CI secrets and must never be stored on a laptop, so those environments run only in CI (`CI=true`), where no `.env` file is read. UI tests run on UAT only.

**Read-only rule:** on `preprod`, `prod` and `npp`, pytest skips every test that isn't marked `smoke`. Smoke tests must never write data, and on PROD and NPP they must use only the testing company.

## API tests

```bash
cd api-tests
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

pytest                      # UAT, all tests
CI=true pytest -m smoke --env prod  # read-only smoke on PROD (CI only; refused locally)
```

Markers:

- `smoke`: read-only release-gate checks.
- `regression`: the full business-rule suite, for UAT.
- `db`: the test includes SQL checks.
- `flow("<id>")`: the business flow the test covers (required, see below).

Allure results are written to `reports/allure-results`.

## UI tests

```bash
cd ui-tests
npm install
npx playwright install chromium

npm test                          # UAT (the only environment for UI tests)
npm run report                    # open the HTML report
```

Traces, screenshots and videos are kept for failed tests. Reports are written to `reports/html` (Playwright) and `reports/allure-results` (Allure).

To build one combined Allure report of both suites after running them, run `npm run report:combined` and open `reports/allure-report/index.html` at the repo root.

## Flows and the flow-tag check

Every test names exactly one flow from `flows/inventory.yaml`: pytest tests with `@pytest.mark.flow("job-creation")`, Playwright specs with the tag `@flow:job-creation`, for example `test('creates a job', { tag: '@flow:job-creation' }, ...)`. To add a flow, add it to the inventory first (kebab-case ID); the QA lead owns that file.

The linter fails when a test has no flow tag, more than one, or a flow ID that isn't in the inventory. It prints the number of tests per flow and lists skipped and `fixme` tests, which count as not covered. It needs the API-test virtualenv and `npm install` in `ui-tests`, and it never runs a test.

```bash
api-tests/.venv/bin/python scripts/flow_lint.py      # from the repo root
cd scripts && ../api-tests/.venv/bin/python -m pytest  # the linter's own tests
```

Tests are named by a canonical test ID, used in the inventory and quarantine files: `api:tests/test_login.py::test_name` or `ui:tests/login.spec.ts > Describe > title`.

## PR checks (`ci`)

To run the tests for a PR on GitHub, use the "Run UAT tests" button (`uat-pr`); see [docs/runbook.md](docs/runbook.md). Every pull request to `main` runs the `ci` check: Python lint (`ruff check .`), the flow-tag check and its tests, pytest collection (no tests run) and the TypeScript type check. It uses no secrets. How merges are gated depends on the GitHub plan; see [docs/runbook.md](docs/runbook.md).

## n8n

n8n connects Jira, GitHub and Slack. For the prototype, it runs in Docker Desktop on a laptop and is reachable only at http://localhost:5678.

```bash
cd n8n && ./setup.sh && docker compose up -d
```

Setup, two-factor login, backups and the restore drill are described in [docs/runbook.md](docs/runbook.md#n8n-story-51-prototype-on-a-laptop). Exported workflows go in `n8n/workflows/` as JSON with no credentials.

## BMAD Method

[BMAD Method](https://bmadcode.com/) v6.12.0 (the `bmm` module) is used locally with Claude Code and is not committed: `_bmad/`, `_bmad-output/` and `.claude/skills/bmad-*` are gitignored. To install it in your clone, run `npx bmad-method@6.12.0 install --directory . --modules bmm --tools claude-code`.

- `_bmad/` holds the framework and its config.
- `.claude/skills/bmad-*` holds the 29 BMAD skills, such as `bmad-help`, `bmad-prd`, `bmad-architecture` and `bmad-qa-generate-e2e-tests`.
- Generated documents go to `_bmad-output/`.

If you're not sure where to start, ask Claude Code to run the `bmad-help` skill.

`.claude/settings.json` turns off claude.ai connectors in this repo and denies connector tools, web fetches, `curl`/`wget`, and reads or edits of real `.env` files, whoever is logged in. These rules reduce what Claude Code can reach; they are not a complete sandbox (for example, a test run can still load `.env.uat`). To update BMAD, run `npx bmad-method install` again.

## Not set up yet

- PoolBrain tests against real UAT (only the two login tests exist, run against the pretend site)
- Nightly and smoke workflows, and branch protection on `main` (not available on GitHub Free)
- Seeded test data
- The QA lead's name, flow owners and confirmed business rules in `flows/inventory.yaml` (currently `TBD` and drafts)
