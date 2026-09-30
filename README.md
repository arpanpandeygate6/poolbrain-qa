# PoolBrain QA Automation

Automated regression tests for PoolBrain. Following approach B from the PRD, business rules are tested through the Flask API with SQL checks on read replicas, and UI tests cover only the top 10 flows.

```
poolbrain-qa/
├── api-tests/          Python + pytest: API tests and read-replica SQL checks
│   ├── config.py       Environment selection and settings (uat, preprod, prod, npp)
│   ├── conftest.py     Fixtures (api, db) and the read-only guard
│   ├── pytest.ini      Markers and default options
│   ├── utils/          ApiClient (requests) and ReadReplica (SELECT-only SQL)
│   └── tests/          Tests go here
└── ui-tests/           Playwright + TypeScript: top 10 UI flows
    ├── playwright.config.ts
    ├── pages/          Page objects go here
    └── tests/          Specs go here
```

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

## BMAD Method

[BMAD Method](https://bmadcode.com/) v6.12.0 (the `bmm` module) is installed for Claude Code.

- `_bmad/` holds the framework and its config.
- `.claude/skills/bmad-*` holds the 29 BMAD skills, such as `bmad-help`, `bmad-prd`, `bmad-architecture` and `bmad-qa-generate-e2e-tests`.
- Generated documents go to `_bmad-output/`.

If you're not sure where to start, ask Claude Code to run the `bmad-help` skill.

`.claude/settings.json` turns off claude.ai connectors in this repo and denies connector tools, web fetches, `curl`/`wget`, and reads or edits of real `.env` files, whoever is logged in. These rules reduce what Claude Code can reach; they are not a complete sandbox (for example, a test run can still load `.env.uat`). To update BMAD, run `npx bmad-method install` again.

## Not set up yet

- PoolBrain tests
- CI workflows (GitHub Actions and the Docker runner)
- Seeded test data
- The business-flow inventory
