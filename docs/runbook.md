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

## n8n (Story 5.1, prototype on a laptop)

**Host decision (1 Oct 2026):** for the prototype, n8n runs in Docker Desktop on the developer's Mac, not on the office server named in PRD D8. The Mac runs no GitHub runner. Moving to the office server later means copying `n8n/` there, restoring a backup and reusing the same encryption key.

Everything lives in `n8n/`: `docker-compose.yml` pins n8n Community Edition 2.41.5 and PostgreSQL 17.11.

**First start**

```bash
cd n8n
./setup.sh             # creates n8n/.env with a random DB password and encryption key (gitignored)
docker compose up -d   # editor: http://localhost:5678
```

Then:

1. Copy `N8N_ENCRYPTION_KEY` from `n8n/.env` into a password manager. It must be kept somewhere other than the n8n data and the backups.
2. Open http://localhost:5678 and create the owner account.
3. Turn on two-factor login: **Settings → Personal → Two-factor authentication**. Only the QA lead and the n8n maintainer get n8n accounts, each with two-factor login. Disable any account without it until it's turned on.

**Access.** The editor port is bound to `127.0.0.1` only, so no other computer can reach it, and there is no public URL, tunnel or port forward. n8n makes only outbound connections. Checked on 1 Oct 2026: reachable on `127.0.0.1:5678`, refused on the Mac's network address.

**Two-factor check**

| Date | Account | 2FA on | Checked by |
|---|---|---|---|
| | | | |

**Backups.** `n8n/backup.sh` dumps the database (workflows, encrypted credentials, executions, audit log) to `BACKUP_DIR` (default `~/n8n-backups`, outside the Docker volumes) and deletes backups older than 30 days. If it fails, it shows a macOS notification and logs to `~/Library/Logs/n8n-backup.log`. Run `n8n/schedule-backup.sh` once to schedule it nightly at 02:00; if the Mac is asleep then, it runs on wake. On a real server, `BACKUP_DIR` must be an office file share that is not on the n8n host.

**Restore drill.** `n8n/restore-drill.sh` restores the newest backup into a throwaway database, then checks that workflows and credentials are there and that credentials decrypt with the stored key. It never touches the running n8n. Run it after any n8n upgrade, and record each run here.

| Date (UTC) | Backup | Workflows | Credentials | Decrypt | Duration | Result |
|---|---|---|---|---|---|---|
| 2026-10-01 11:36 | test backup with one dummy credential | 0 | 1 | yes | 7 s | PASSED; a wrong key was correctly rejected |

**Stop and start**

```bash
cd n8n
docker compose stop          # stop (data is kept)
docker compose up -d         # start again
docker compose logs -f n8n   # watch the logs
```

Never run `docker compose down -v`: `-v` deletes the data volumes.
