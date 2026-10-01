# PoolBrain QA runbook

Decisions and procedures that are not visible in the code. Each section names the story that set it.

## GitHub plan (Story 1.3, AR-32)

**Plan: GitHub Free** (recorded 1 Oct 2026). The repository is private and belongs to a company-provided GitHub account, not a company organization. The merge gate is therefore the team procedure below.

The plan decides how the merge gate works:

- **Team or Enterprise:** GitHub enforces the merge gate through branch protection (below).
- **Free (private repository):** branch protection is not available, so the merge gate is the team procedure below. GitHub does not enforce it.

## Merge gate on `main` (Story 1.3)

Every pull request to `main` runs the `ci` check (`.github/workflows/ci.yml`). It uses no secrets and no Environment, so PR code, including PRs from forks and bots, never sees credentials. It runs:

- Python lint (`ruff check .`)
- the flow-tag check (`scripts/flow_lint.py`) and its own tests
- pytest collection only (`--collect-only`; no test runs)
- the TypeScript type check (`npm run typecheck`)

Contract validation is added to `ci` by Story 2.4, when the first contract exists.

### Team or Enterprise: branch protection

In **Settings → Branches → Add branch ruleset** (or **Add classic branch protection rule**) for `main`:

1. Require a pull request before merging, with **1 approval**.
2. Require status checks to pass: add **`ci`** (it appears in the list after `ci` has run once on a PR).
3. Block force pushes.
4. Restrict deletions.

Then check it once:

- A test PR with a failing `ci` check shows "Merging is blocked".
- A test PR with a green `ci` and one approval can be merged.

### Free: team procedure

GitHub does not enforce this; the team does.

- Merge a PR only when `ci` and `mock-tests` are green and one QA member, not the author, has approved it.
- Before approving, the reviewer runs the UAT tests for the PR: with the "Run UAT tests" button below, or on their laptop with `.env.uat`. Merge only when `uat-pr` is green on the PR's latest commit.

## "Run UAT tests" button: `uat-pr` (Story 1.5)

To run the tests for a PR you reviewed:

1. On the PR's **Commits** tab, copy the full SHA of the latest commit.
2. Go to **Actions → uat-pr → Run workflow**, keep "Use workflow from" on `main`, paste the SHA and click **Run workflow**.
3. The PR shows a `uat-pr` check: pending while it runs, then green or red. A new commit on the PR needs a new run; the earlier result doesn't cover it.

The first job refuses the request, without running any PR code, unless all of these hold. The job summary says why and how to fix it.

- You are listed in `.github/qa-team.txt` on `main`.
- You are a person, not an app or bot.
- The SHA is the head of an open PR to `main`.
- For a PR opened by the `qa-agent` app, you approved the PR at that commit.

**Who can press it.** `.github/qa-team.txt` lists the QA team, one GitHub username per line. Adding or removing a QA member means a PR to that file that another QA member approves.

**Free plan and the pretend site.** The test job has no `uat-pr` Environment yet: private repositories on GitHub Free have no Environments, and the tests run against the pretend PoolBrain, which needs no credentials. When UAT access arrives on a plan with Environments:

1. Create the `uat-pr` Environment, allow only `main` to deploy to it, and add the UAT values.
2. In `.github/workflows/uat-pr.yml`, add `environment: uat-pr` to the `tests` job and replace the "Start the pretend PoolBrain" step.
3. On Team or higher, make `uat-pr` a required check next to `ci`.

## Test reports (Story 1.6)

Every test run uploads two artifacts, kept for 30 days:

- `<workflow>-allure-report-<run>`: one combined Allure report for both suites. Download it, unzip it and open `index.html`; no server is needed.
- `<workflow>-test-output-<run>`: raw results, the Playwright HTML report, and screenshots, videos and traces of failed UI tests.

The job summary links to the report. The report step (`.github/actions/test-report`) runs even when tests fail or are cancelled, and says "no results" when there are none. New workflows (`nightly`, `smoke`) reuse it rather than copying it.

The Allure version is pinned in two places, which must match: `ui-tests/package.json` and `.github/actions/test-report/action.yml`.

## Tool versions and dependency updates (Story 1.3, AR-16)

- Python and Node versions come from `.python-version` and `.nvmrc`. CI reads both files.
- Node packages are installed in CI with `npm ci` from `ui-tests/package-lock.json`.
- Python packages are pinned in `api-tests/requirements.txt`.
- Pinned test dependencies are updated once a month through one PR, which must pass `ci` like any other PR.
