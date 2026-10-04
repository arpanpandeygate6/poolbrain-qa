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
| Slack app "QA Bot" | QA Bot (Slack) | **Placeholder** since 4 Oct 2026: messages are previews until the app exists and a channel is chosen (see "Slack messages" below) |
| GitHub App `qa-relay` (named `poolbrain-qa-relay` on GitHub) | qa-relay | Done 1 Oct 2026; checked: it sees only this repository and can read runs and variables |
| Jira Cloud, `https://gatesix.atlassian.net`, project `PM` | Jira (QA relay) | Done 1 Oct 2026; checked: it reads PM tickets and can create issues and add comments, but **cannot set Reporter** (needed later for filing bugs) |

**Slack.** Create the app from `n8n/slack-app-manifest.yaml` (https://api.slack.com/apps → Create New App → From a manifest). It has exactly the bot scopes `chat:write`, `reactions:read`, `channels:history`, `groups:history`, `usergroups:read`, `users:read`, `users:read.email` and `files:write`, with no events, slash commands or interactivity (n8n polls Slack). Invite the bot only to the QA channel. The bot token goes only into the n8n credential, through `n8n/slack-setup.sh` (see "Slack messages").

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


## Slack messages and the W0 error alert (Story 5.3)

**One way to post.** Every n8n workflow posts to Slack only by calling the sub-workflow "Slack: post message" (`n8n/workflows/slack-post-message.json`). Its inputs are `kind` (`info`, `action` or `alert`, which adds "FYI:", "Action needed:" or "Alert:"), `header`, `body`, `todo`, `links` (a list of `{label, url}`) and `thread_ts`. It builds the message in the shared shape (header, what happened, what to do, links) and returns `posted`, or `preview`, or `error`.

**Preview mode.** Until Slack is set up, nothing is sent. The sub-workflow returns the message as a preview, which you can read in n8n under **Executions** → "Slack: post message".

**Turning Slack on (later).** Create the Slack app (see "n8n connections"), invite it to the QA channel, then:

1. Add the channel ID to `n8n/.env`: `SLACK_CHANNEL=C0123456789` (in Slack, open the channel → its name → the ID is at the bottom).
2. Run `SLACK_BOT_TOKEN=xoxb-... n8n/slack-setup.sh`. The token goes only into the n8n credential "QA Bot (Slack)", never into a file.

Nothing else changes: every workflow starts posting. Running `n8n/slack-setup.sh` without a token keeps the stored one. Without a channel it installs everything in preview mode, which is how it was set up on 4 Oct 2026.

**W0 Error handler** (`n8n/workflows/w0-error-handler.json`). Every n8n workflow names W0 as its error workflow (`settings.errorWorkflow`). When one fails, W0:

- posts S16: "Alert: n8n workflow error in <workflow>", the step, a short cleaned error, the time in IST, "What to do: n8n maintainer, open the execution (office network only)." and the execution link;
- cleans the error first: first line only, at most 160 characters, with tokens, emails, long keys and URL query strings replaced by `[hidden]` or `[email]`, so no stack traces, secrets or ticket text reach Slack;
- writes one audit entry as `n8n:w0-error-handler`: `error-alert-posted`, `error-alert-preview` or `error-alert-failed` (Slack refused or was unreachable, with the reason);
- never alerts about itself or its helpers, and runs whatever `AGENT_ENABLED` says.

**New workflows** must set `"errorWorkflow": "w0ErrorHandler1"` in their settings; `scripts/tests/test_n8n_workflows.py` checks the existing ones. Errors only reach W0 from scheduled or triggered runs, not from clicking "Execute workflow" in the editor.

**Checked on 4 Oct 2026:** a throwaway scheduled workflow failed with an error containing a Slack token, an email, a URL query and a stack trace. W0 ran within a second and produced the preview "Alert: n8n workflow error in Throwaway W0 test / Step: call Jira. Error: Jira returned 403 for token [hidden] and [email] at https://x.atlassian.net/rest [line 1]. / Time: 04 Oct 20:59 IST.", with none of the secrets in the execution data, and wrote an `error-alert-preview` audit entry. The throwaway workflow was then deleted.

## Kill switch and daily limits (Story 5.6)

**Turning AI work off and on.** In GitHub: **Settings → Secrets and variables → Actions → Variables**, the repository variable `AGENT_ENABLED`. Only the exact value `true` lets AI work run. `false`, any other value, or no variable at all counts as off. Only people change it (the QA lead or n8n maintainer), never a workflow.

**Daily limits.** The repository variable `AGENT_CAPS` holds each agent workflow's daily limit as JSON: `{"draft-cases": 20, "generate-tests": 20, "triage": 2, "quarantine": 5}`. Only the QA lead changes it. A missing or broken value, or a workflow with no entry, counts as "limit reached".

**Stopping a run already in progress:** open it on the Actions tab and click **Cancel workflow**.

**How n8n obeys them.** Before any AI action (starting an agent workflow, posting triage, asking for a quarantine, writing to Jira), an n8n workflow calls the shared sub-workflow **"Gate: check"** (`n8n/workflows/gate-check.json`) with `action` (`dispatch`, `triage-post`, `quarantine` or `jira-write`), `workflow` (for `dispatch`: the agent workflow, for example `draft-cases`), `target` (usually the ticket key) and `payload` (what is needed to do it later). It answers `allowed: true`, or `allowed: false` with the `reason` and the waiting-list entry. The caller acts only on `allowed: true`. W0, W5, audit writes and the audit export never call it.

- **Off:** the request goes on the waiting list. The first skipped action after the switch goes off posts "Alert: AI work is off" (what stops, what still runs, how to turn it back on). The first action after it is back on posts "FYI: AI work is on again". Each goes out once per change, and the switch is read on every check, so everything stops within one polling cycle.
- **Daily limit** (for `dispatch` only): it counts that workflow's runs created since 00:00 IST, leaving out runs whose `run-outcome` is `capped`, `disabled` or `blocked`. It reads that outcome from each run's `run-outcome` artifact. If the limit is reached, the request waits until after 00:00 IST, and "FYI: <work> waits until tomorrow" is posted once per workflow per day. The counting rule is shared with the agent side and tested against `contracts/cap-count.fixture.json`.
- **Broken `AGENT_CAPS`:** the request waits, and the caller's run fails with the reason (for example "AGENT_CAPS has no daily limit for draft-cases"), so W0 alerts.
- **Every skip or wait** is recorded in the audit log as `n8n:gate-check` (`gate-skipped-disabled`, `gate-deferred-capped`, `gate-deferred-caps-invalid`), and so is each notice.

**The waiting list** is the table `audit.deferred_requests`: one open entry per action, workflow and ticket, in arrival order, with the time after which it may run (`not_before`). Asking again for the same open request only updates it. The switch state and notice days are in `audit.relay_state`. Both tables are created by `n8n/audit-setup.sh`.

**Still to build with W1 (Story 5.5):** working through the waiting list (W1 picks up due entries in arrival order, asks the gate again and sets `done_at` once dispatched), and putting a request back on the list when an agent run ends `capped`. Nothing uses the gate yet: W1 is its first caller.

**Not created yet:** `AGENT_ENABLED` and `AGENT_CAPS` (Story 4.4 has the QA lead create them). Until then the gate counts AI work as off, which is safe.

**Checked on 4 Oct 2026:**
- With `AGENT_ENABLED` missing, a request was refused and kept. "AI work is off" was previewed once, and asking again reused the same waiting-list entry.
- In a temporary copy of the gate with the switch on and a limit of 1 for `nightly`, an allowed request posted "AI work is on again". Two capped requests were deferred to 05 Oct 00:00 IST with one "Nightly waits until tomorrow" notice. A workflow missing from the limits failed with the reason.
- The artifact reading (find the download link, download without GitHub's login, unzip, read JSON) worked on a real nightly artifact. GitHub's storage rejects the GitHub login, so the download is done in two steps.
- The temporary workflows and test waiting-list entries were deleted. The audit entries from the test remain, because the audit log is append-only.

## Ready-for-QA notice (Story 5.7)

The n8n workflow "Ready-for-QA notice" (`n8n/workflows/ready-for-qa-notice.json`) is the early n8n demo: Jira, GitHub and Slack working together. It only reads Jira and GitHub; it never writes to Jira or starts a GitHub workflow.

- **When:** every 5 minutes. It asks Jira for PM tickets that moved to **"Ready to Test"** (this board's name for "Ready for QA") since its last fully successful poll, plus 10 minutes of overlap. Its first run starts from that moment, so old tickets aren't announced.
- **What it reads:** only each ticket's key and title. It never reads the description or acceptance criteria.
- **The message:** "FYI: PM-123 is ready for QA", the ticket title, "Latest UAT result: **PASSED**" or "**FAILED**" with the workflow and its IST start time (from the newest finished `nightly` or `uat-pr` run; cancelled runs are skipped), or "No UAT run yet", and the links Jira · Latest run. It goes through "Slack: post message", so it is a preview until Slack is set up.
- **One notice per ticket, ever.** Each notice writes an audit entry (`n8n:ready-notice`, `ready-notice-posted` with the Slack link, or `ready-notice-preview` with the Jira link), and a ticket with an entry is never announced again. A preview counts, so turning Slack on later doesn't re-announce tickets.
- **When something fails** (Jira, GitHub or Slack): the run fails, W0 alerts, and the checkpoint doesn't move, so the next poll retries. Tickets already announced are not repeated.
- **Settings** (project, status name, Jira URL, repository) are in the workflow's "Settings" node.

**Volume.** PM is busy: the first test run on 4 Oct 2026 (an earlier version that looked back 8 days) found 100 tickets moved to "Ready to Test", which is about 12 a day. Those 100 were recorded as previews, so they will never be posted. If that many messages is too noisy for the channel, add a filter (for example a label or component) to the Jira query in the "Find tickets" node.

**When W1 (Story 5.5) goes live,** switch this workflow off (unpublish it in n8n) so a ticket doesn't get two messages. W1's own "Tests generated" message replaces it. Record the date here when that happens.

**Checked on 4 Oct 2026:** a run read the live PM project and produced correct previews (title, latest nightly result, Jira and run links, no description). The next run found no new tickets, posted nothing twice and moved the checkpoint on.

## Heartbeat (Story 5.4)

n8n can't report its own death, so two sides work together:

- **W5 Heartbeat** (n8n, `n8n/workflows/w5-heartbeat.json`) runs every hour and sets the repository variable `N8N_HEARTBEAT_AT` to the current UTC time. It is the only writer of that variable, and it runs even when `AGENT_ENABLED` is off.
- **heartbeat-watch** (GitHub Actions, `.github/workflows/heartbeat-watch.yml`) runs every hour at :23 UTC. If `N8N_HEARTBEAT_AT` is more than 2 hours old, missing or unreadable, the run fails and its job summary shows the alert. GitHub emails the repository owner about the failed run. It alerts at most once every 6 hours per outage, and the next W5 run clears it. It reads variables only and holds no secret.

**Slack, later.** Once the Slack app and the `notify` Environment exist (or, on GitHub Free, once the team agrees where the webhook is kept), add `environment: notify` to the job and pass `SLACK_WEBHOOK_URL` to the check step. `scripts/heartbeat_check.py` already posts to Slack when that variable is set.

**Check it.** In GitHub, **Settings → Secrets and variables → Actions → Variables** shows `N8N_HEARTBEAT_AT`. To test an outage, stop n8n (`cd n8n && docker compose stop`) and run heartbeat-watch by hand after more than 2 hours, then start n8n again.

**Laptop host (prototype).** n8n runs only while the Mac is awake. If the Mac sleeps for more than 2 hours, heartbeat-watch correctly alerts by email, at most every 6 hours. On 2 Oct 2026, the Mac slept from about 00:15 to 22:30 IST and three alerts arrived; a manual W5 run cleared it. To avoid this, keep the Mac awake on power (System Settings → Battery → Options → "Prevent automatic sleeping on power adapter when the display is off"), disable heartbeat-watch while away, or move n8n to an always-on machine (D8). W5 and the run recorder retry each GitHub call up to 5 times, 5 seconds apart, to ride out the brief network gap just after waking.

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

## Failure list (Story 2.4)

After the tests, the nightly's separate **Failure list** job builds the plain list of last night's failures. That job holds no test credentials.

- **Which tests:** FAILED, QUARANTINED and PASSED ON RETRY tests, each with its last 7 scheduled nights' results (fewer while there are fewer runs).
- **The Slack message** follows EXPERIENCE.md M1: the header "Nightly run failed: N tests (UAT, <date> 02:30 IST)", one line per test (cut at 10, with "and N more — see the run"), a "Passed on retry" section, a "What to do" line, and the labelled links Run · Allure report. Nothing is posted when every test passed with no retries.
- **Triage line:** "The agent is classifying these. Results appear in this thread." appears only when the repository variable `TRIAGE_LIVE` is `true`. It stays unset until the triage epic.
- **Words:** every status word, reaction, triage class, run outcome, notice kind and label comes from `contracts/vocabulary.json`, never from code (UX-DR1).
- **Saved file:** after a successful post, the list is checked against `contracts/failure-list.schema.json` and saved as the artifact `failure-list` (30 days), with the message's `slack_channel` and `slack_ts`. If the check fails, the job fails and nothing is saved. If the Slack post fails, the job fails with the reason and nothing is saved. Either way the test result is unchanged.

**Slack not set up yet.** Until it is, the job shows the message it would post as a preview in its summary, and saves no `failure-list`, because the file needs the Slack message's ID. To turn posting on:

1. Finish the Slack app (Story 5.2) and invite it to the QA channel.
2. Set the repository variable `SLACK_CHANNEL`, for example `#qa-automation`.
3. Put the bot token where only `main` can use it: in the `notify` Environment on a plan with Environments. On GitHub Free, the team decides; it must never be a repository secret without that decision being recorded here.
4. Add `environment: notify` and `SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}` to the "Build the failure list" step's job.

## Contracts (AD-5)

`contracts/` holds the schema for every file handed between components (`<name>.schema.json`), a sample of each in `contracts/samples/`, and the shared vocabulary.

- `schema_version` comes first in every file.
- A breaking change bumps `schema_version`, and consumers reject versions they don't know.
- Producers validate before saving: `python scripts/validate_contract.py <name> <file>`, or call `validate()` from Python.
- The `ci` check validates every sample (`--samples`), so each schema needs at least one sample.
