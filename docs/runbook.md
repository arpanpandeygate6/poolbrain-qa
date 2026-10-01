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
| 2026-10-01 | Owner (n8n maintainer, prototype) | yes | n8n database check, confirmed by the maintainer |

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

## n8n connections (Story 5.2)

| Connection | n8n credential | Status |
|---|---|---|
| Slack app "QA Bot" | QA Bot (Slack) | **Waiting** for a QA Slack channel the bot can be invited to |
| GitHub App `qa-relay` (named `poolbrain-qa-relay` on GitHub) | qa-relay | Done 1 Oct 2026; checked: it sees only this repository and can read runs and variables |
| Jira Cloud, `https://gatesix.atlassian.net`, project `PM` | Jira (QA relay) | Done 1 Oct 2026; checked: it reads PM tickets and can create issues and add comments, but **cannot set Reporter** (needed later for filing bugs) |

**Slack.** Create the app from `n8n/slack-app-manifest.yaml` (https://api.slack.com/apps → Create New App → From a manifest). It has exactly the bot scopes `chat:write`, `reactions:read`, `channels:history`, `groups:history`, `usergroups:read`, `users:read`, `users:read.email` and `files:write`, with no events, slash commands or interactivity (n8n polls Slack). Invite the bot only to the QA channel. The bot token goes only into the n8n credential.

**GitHub App `qa-relay`.** It is installed only on this repository, with webhooks off, and has these repository permissions: Actions read and write, Contents read, Issues read and write, Pull requests read, Variables read and write. Its private key goes only into the n8n credential (type "GitHub App API"); afterwards, delete the downloaded `.pem` or move it to a password manager.

**Jira.** The credential is the Jira SW Cloud API type, with an API token from id.atlassian.com, and should belong to the shared ai.team@gate6.com account (D9), not a named person. The board's ready-for-testing status is **"Ready to Test"**; the PRD calls it "Ready for QA". Before bug filing (Epic 6), ask the Jira admin to give this account the "Modify Reporter" permission in PM.

**Updates and rotation (AR-16).** The n8n maintainer owns both:

- Once a month, update n8n, PostgreSQL and Docker Desktop: bump the pinned versions in `n8n/docker-compose.yml` through a PR, take a backup, run `docker compose up -d`, then run the restore drill.
- Once a year, or at once if exposed, rotate the `qa-relay` private key, the Slack bot token, the heartbeat webhook, the Jira token, the database users' passwords and the audit writer's password.

## Audit log (Story 5.3)

One append-only table, `audit.audit_log` in n8n's PostgreSQL, records every agent run, n8n action and QA decision. Its columns are `ts` (UTC), `actor`, `actor_type` (`human`, `agent`, `n8n` or `ci`), `action`, `target` and `link`. `actor` is an email for humans, and `agent:<workflow>`, `ci:<workflow>` or `n8n:<workflow>` otherwise; the database rejects any other form.

**Setup:** run `n8n/audit-setup.sh`; it is safe to run again. It:

- creates the table and the `audit_writer` database user;
- adds the n8n credential "Audit log (Postgres)";
- installs and publishes the shared sub-workflow "Audit: write entry" (`n8n/workflows/audit-write-entry.json`).

Every n8n workflow writes audit entries only by calling that sub-workflow, with the inputs `actor`, `actor_type`, `action`, `target` and `link`.

**Append-only.** `audit_writer` can INSERT and SELECT only. Checked on 1 Oct 2026: as `audit_writer`, UPDATE, DELETE and TRUNCATE are refused with "permission denied", and badly formed actors are rejected.

**After a restore,** run `n8n/audit-setup.sh` again: database users are not part of the backup, so it recreates `audit_writer` and its grants.

**Run recorder.** The n8n workflow "Audit: record GitHub runs" (`n8n/workflows/audit-record-github-runs.json`) runs every 10 minutes.

- It adds one entry per completed run of `draft-cases`, `generate-tests`, `triage`, `quarantine`, `nightly`, `smoke` and `uat-pr`, plus `mock-tests` while it stands in for `nightly`.
- Each entry records the actor as `agent:<workflow>` or `ci:<workflow>`, the action as `run-<conclusion>` (for example `run-success`), and the run link.
- Workflows that don't exist yet are skipped without error.
- It keeps its own checkpoint in `audit.checkpoints` and looks back one day before it, so runs that finished while n8n was down are recorded when it returns.
- A unique index on the run link means a run is never recorded twice. Checked on 1 Oct 2026: a second pass over the same three runs added nothing.

**Still to build:** the W0 error handler that alerts in Slack. It needs the Slack app.

## Heartbeat (Story 5.4)

n8n can't report its own death, so two sides work together:

- **W5 Heartbeat** (n8n, `n8n/workflows/w5-heartbeat.json`) runs every hour and sets the repository variable `N8N_HEARTBEAT_AT` to the current UTC time. It is the only writer of that variable, and it runs even when `AGENT_ENABLED` is off.
- **heartbeat-watch** (GitHub Actions, `.github/workflows/heartbeat-watch.yml`) runs every hour at :23 UTC. If `N8N_HEARTBEAT_AT` is more than 2 hours old, missing or unreadable, the run fails and its job summary shows the alert. GitHub emails the repository owner about the failed run. It alerts at most once every 6 hours per outage, and the next W5 run clears it. It reads variables only and holds no secret.

**Slack, later.** Once the Slack app and the `notify` Environment exist (or, on GitHub Free, once the team agrees where the webhook is kept), add `environment: notify` to the job and pass `SLACK_WEBHOOK_URL` to the check step. `scripts/heartbeat_check.py` already posts to Slack when that variable is set.

**Check it.** In GitHub, **Settings → Secrets and variables → Actions → Variables** shows `N8N_HEARTBEAT_AT`. To test an outage, stop n8n (`cd n8n && docker compose stop`) and run heartbeat-watch by hand after more than 2 hours, then start n8n again.

**Note.** GitHub turns off scheduled workflows in a repository with no activity for 60 days. If that happens, re-enable heartbeat-watch on the Actions tab.

## n8n workflows in this repository

`n8n/workflows/` holds each workflow as JSON, with credentials referenced only by ID and name. To install or update one:

```bash
cd n8n
docker compose exec -T n8n sh -c 'cat > /tmp/w.json && n8n import:workflow --input=/tmp/w.json; rm -f /tmp/w.json' < workflows/<file>.json
docker compose run --rm --no-deps -T n8n publish:workflow --id=<id from the file>
docker compose restart n8n
```

On another n8n instance, fix the credential IDs in the editor after importing.

## Nightly regression run (Stories 2.3 and 2.5)

`.github/workflows/nightly.yml` runs the whole pack:

- **When:** every night at 02:30 IST (cron `0 21 * * *`), after every merge to `main`, and from **Actions → nightly → Run workflow**.
- **Reset window:** a post-merge or manual run that would start between 01:00 and 02:30 IST doesn't run tests. It ends with "Not run: UAT reset window (01:00–02:00 IST)", and the 02:30 run covers the change.
- **One run at a time:** a new run waits for the current one to finish.
- **Timeout:** 180 minutes, so the 02:30 run ends by 05:30 IST, before the 06:00 deadline. A timed-out run fails.
- **Retries:** API tests get one retry (`pytest-rerunfailures`), UI tests two. A test that passes on a retry is listed as PASSED ON RETRY and doesn't turn the run red.
- **Quarantine:** a failing test listed in `flows/quarantine.yaml` is reported as QUARANTINED and doesn't turn the run red. Any other failure after retries does. **A red nightly blocks UAT sign-off.**
- **Job summary:** PASSED or FAILED, the commit, who or what started it, the IST time, counts per suite, up to 10 failed, quarantined or passed-on-retry tests ("and N more — see the run"), the Allure report link, and the coverage table.
- **Artifacts (30 days):** the Allure report, test output, and `nightly-results-<run>` (per-test results, used for the 7-night history in Story 2.4).

**Coverage (Story 2.5).** `scripts/flow_coverage.py` writes "Coverage: N of M regression flows automated (P%)" with a table per flow. A flow counts as automated only when each of its rules has a mapped test that ran that night and none of its tests is skipped, fixme or quarantined.

**Prototype.** It runs against the pretend PoolBrain, so the tests job has no `uat-nightly` Environment. With UAT access, add `environment: uat-nightly` to the tests job and replace the "Start the pretend PoolBrain" step.

**To confirm with the QA lead before running on UAT (Story 2.3):** UAT uses Stripe test mode, the QBO sandbox and the Chargebee test site. Not confirmed yet.

Checked on 1 Oct 2026, in a local rehearsal with temporary tests:

- A test that failed once and then passed was PASSED ON RETRY, and the run was green.
- A failing quarantined test was QUARANTINED, the run was green, and its flow showed as not covered.
- The same failing test without quarantine turned the run red.
