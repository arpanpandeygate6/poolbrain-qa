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

## AI agent on laptops (Stories 4.1 and 4.2)

**House rules.** `CLAUDE.md` at the repository root holds the rules Claude Code follows here: the folder layout, the naming conventions and the hard rules (never touch PROD data; changes only through PRs; tests call only the helpers; one flow tag per test; never weaken a test to make it pass; never read `.env` files; laptops run UAT only; no Jira, Slack or web tools; the existing Gate6 QA Agent is not used or changed). To check them, ask Claude Code "explain the house rules for this repo": its answer must match `CLAUDE.md`.

**What the repository blocks** (`.claude/settings.json`, committed):
- claude.ai connectors are switched off (`disableClaudeAiConnectors`);
- every MCP tool (`mcp__*`), web fetch, web search, `curl` and `wget` are denied;
- reading or editing `.env`, `.env.uat`, `.env.preprod`, `.env.prod`, `.env.npp` and `.env.local` is denied, including through common shell commands (`cat`, `head`, `grep`, `sed`, `cp`, `base64` and others). Shell denies can't cover every possible command, so the rule in `CLAUDE.md` still matters.

Plugins synced from the organisation's claude.ai account (for example the "design" plugin, which brings Slack, Atlassian, Asana, Figma, Notion and other MCP servers) can still **load** in a session, even though the deny list stops their tools being used. The laptop check below counts a loaded tool as a fail.

### Laptop connector check

Do this on each QA laptop before it is used for agent work, and again after Claude Code or plugin changes:

1. Log in to Claude Code with the ai.team Claude Max account, and make sure no API key is set (`echo $ANTHROPIC_API_KEY` prints nothing).
2. Start a **fresh** session in the repository folder.
3. Type `/mcp`: no server may be listed as connected. Type `/context`: the tools list must show no MCP tools.
4. Ask: "read api-tests/.env.uat". It must be refused.
5. Write the result in the table. **A laptop that fails is not used for agent work** until it is fixed (switch off the plugin for this project with `/plugin`, or ask the claude.ai organisation admin to stop syncing it) and checked again.

| Laptop owner | Date | Claude Code version | Result | Notes |
|---|---|---|---|---|
| (developer Mac, ai.team) | | | **Not checked yet** | Organisation-synced plugins are installed ("design" with Slack, Atlassian and other MCP servers): expect a fail until they are switched off for this project |

### `/draft-cases <KEY>` (Story 4.2)

Run it in Claude Code in the repository. It asks you to paste the ticket text, because it has no Jira access, and then:
1. starts the branch `agent/<KEY>-cases` from the latest `main`;
2. picks the flows from `flows/inventory.yaml`, or stops and asks you if none fits (it never invents one);
3. writes `cases/<KEY>.md` (format in `cases/README.md`) and `cases/<KEY>.questions.json` (clarification questions, or an empty list);
4. checks both with `scripts/validate_contract.py` and `scripts/case_lint.py`;
5. commits, pushes and opens PR 1 titled `[<KEY>] Cases: …` with the body from `.github/PULL_REQUEST_TEMPLATE/cases.md`. Without the GitHub CLI (`gh`), it prints a link that opens the PR form, plus the title and body to paste;
6. ends with the case count, the PR link and "Next: review and merge PR 1 in GitHub."

`ci` runs `scripts/case_lint.py` on every PR. It fails on missing front matter, a `ticket` that doesn't match the file name, an unknown flow, a layer other than `api`, `db` or `ui`, misnumbered cases, a case missing a part, or a missing or invalid questions file.

**Still to do: the end-to-end try with a real ticket.** The QA lead picks a ticket, a QA member runs `/draft-cases` on it, and the QA lead confirms the drafted cases make sense. Adjust `CLAUDE.md` or `.claude/commands/draft-cases.md` until they do. Checked on 4 Oct 2026 without a real ticket: a case file and questions file drafted by following the command's steps for a made-up ticket passed both checks. It was written outside the repository and not committed.

### `/generate-api-tests <KEY>` (Story 4.3)

Run it after PR 1 (the case file) is merged. It:
1. fetches the latest `main` and stops with "Cases for <KEY> are not merged on main yet. Merge PR 1 first." if `cases/<KEY>.md` isn't there, changing nothing;
2. starts `agent/<KEY>-tests` from `main`;
3. writes one pytest test per `api`/`db` case (helpers only, `regression`/`db`/`flow` markers, `qa-auto-` names, the case ID in the docstring). For `ui` cases it writes Playwright specs with page objects, but only on flows marked `ui_top10: true` in `flows/inventory.yaml`;
4. maps the new tests to their business rules in `flows/inventory.yaml`, so coverage counts them once merged;
5. runs the flow-tag linter, pytest collection, the type check, `ruff` and the new tests on UAT from the laptop. A test that fails because the product behaves differently from the case is left as written and reported, never weakened;
6. opens PR 2 `[<KEY>] Tests: …` with `.github/PULL_REQUEST_TEMPLATE/tests.md`. UAT stays "not run yet" until a QA member reviews it and starts `uat-pr` with the head commit SHA.

**Top 10 UI flows.** `ui_top10: true` marks the flows that also get Playwright tests (FR-09). Today `login` and `job-creation` are marked, because they already have UI tests. The QA lead confirms or changes the list.

**Checked on 4 Oct 2026 (dry run, not committed):** following the command's steps for the made-up case file PM-9001 (3 cases: job type required) produced 3 pytest tests. Flow tags, collection, type check, `ruff` and the case-file check passed, and all 3 tests passed against the pretend PoolBrain, started with made-up accounts. The "not merged on main" guard stopped as it should. The dry-run files were deleted. Still to do: a real run on a ticket whose PR 1 the QA lead has merged.

## Agent workflows in GitHub: identity, first step and run-outcome (Story 4.4)

**Every agent workflow** (`draft-cases`, `generate-tests`, `triage`, `quarantine`) starts and ends with the same two steps:

```yaml
permissions:
  actions: read          # to count today's runs
  contents: read
steps:
  - uses: actions/checkout@v5
    with: { persist-credentials: false }
  - uses: actions/setup-python@v6
    with: { python-version-file: .python-version }
  - id: gate
    uses: ./.github/actions/agent-start
    with:
      ticket: ${{ inputs.ticket }}
      agent-enabled: ${{ vars.AGENT_ENABLED }}
      agent-caps: ${{ vars.AGENT_CAPS }}
  # ... every AI step has: if: steps.gate.outputs.proceed == 'true'
  - if: always()
    uses: ./.github/actions/agent-finish
    with:
      ticket: ${{ inputs.ticket }}
      status: ${{ job.status == 'success' && 'ok' || 'error' }}
```

- **First step** (`scripts/agent_gate.py start`), before any model call:
  - If `AGENT_ENABLED` isn't exactly `true`, the run ends as `disabled` ("Result: Not run (agent is turned off)").
  - If `AGENT_CAPS` is missing, broken or has no entry for the workflow, the run ends as `error` with the reason, and the job fails.
  - If today's runs (since 00:00 IST, with the rule shared with n8n and tested against `contracts/cap-count.fixture.json`) are at the limit, the run ends as `capped` ("Result: Waiting until tomorrow (daily limit reached)", with the limit and the count).
  - It reads earlier runs' outcomes from their `run-outcome` artifacts, downloading without sending the GitHub token to the artifact storage.
- **Last step** (`scripts/agent_gate.py finish`, `if: always()`): writes `run-outcome.json` following `contracts/run-outcome.schema.json` (status `ok`, `blocked`, `capped`, `disabled` or `error`, a reason, an optional PR link and the UTC time), checks it, and uploads it as the artifact `run-outcome` for 30 days. When the first step already ended the run, its outcome is kept.

### Setup still to do (people, not code)

Nothing below exists yet. The code above is ready for it.

1. **Repository variables** (QA lead), under **Settings → Secrets and variables → Actions → Variables**: `AGENT_ENABLED` = `true` and `AGENT_CAPS` = `{"draft-cases": 20, "generate-tests": 20, "triage": 2, "quarantine": 5}`. Only people change them. Until they exist, every agent run ends as `disabled` and n8n's gate counts AI work as off.
2. **GitHub App `qa-agent`** (the agent's own identity, like `qa-relay`): create it under the repository owner's **Settings → Developer settings → GitHub Apps**. Webhooks off. Repository permissions: **Contents: read and write** and **Pull requests: read and write** only, with **no Actions permission**. Install it only on this repository. Keep its app ID and a private key for step 4.
3. **Claude token:** on a laptop logged in to the ai.team Claude Max account, run `claude setup-token` and keep the token for step 4. It lasts a year: the QA lead owns renewing it (put a reminder 11 months out), and so the agent stops working when it expires. **Before using it in CI, the QA lead confirms that using the Claude Max subscription in scheduled GitHub runs is within its terms (PRD assumption A7).** Max usage is shared with people's own Claude Code use.
4. **Where the three secrets live** (`CLAUDE_CODE_OAUTH_TOKEN`, the `qa-agent` app ID and private key): the plan is an `agent` Environment restricted to `main`. GitHub Free has none for private repositories, so **the team decides** and records the decision here before anything is added. A repository secret is readable by any workflow on any branch that someone with write access pushes, so if that is the choice, agent workflows must run only from `main` (`workflow_dispatch` on `main`), and PRs that change `.github/` get extra review.

**Owner:** the QA lead owns the variables, the `qa-agent` app and the yearly token renewal.

**Stopping AI work:** set `AGENT_ENABLED` to `false` (see "Kill switch and daily limits"). **Stopping one run already going:** open it on the Actions tab and click **Cancel workflow**.

**Checked on 4 Oct 2026 (unit tests only, as no agent workflow exists yet):** the counting rule passes every case in the shared fixture. Each way of stopping (switch off or any other value, limit reached with outcomes read from artifacts, broken or missing limits) stops before GitHub or a model is asked, and writes a valid `run-outcome`. The first live run will be the `draft-cases` workflow (Story 4.5).

### `draft-cases` workflow (Story 4.5)

**Actions → draft-cases → Run workflow** (on `main`), with the ticket key and the ticket text. **Paste only sanitized text:** no customer data, secrets or links to them. n8n W1 will start it the same way later. In order, it:
1. writes the ticket text to a file and hides every line of it from the log;
2. checks the key (otherwise `error`, `invalid-ticket-key`);
3. runs the shared first step (kill switch and daily limit, Story 4.4);
4. checks that the agent is set up: the Claude token, `QA_AGENT_APP_ID` and the `qa-agent` private key. Otherwise it ends `error`, `agent-not-set-up`, before any model call, saying what is missing;
5. stops if `cases/<KEY>.md` is already on `main` (`blocked`, `cases-already-on-main`), or if PR 1 is already open (`ok`, `already-open`, with that PR's link; no second PR);
6. runs the agent (`anthropics/claude-code-action`, pinned to the commit of v1.0.241). It gets the `/draft-cases` steps, and only file tools plus the case, flow and contract checkers; web tools are denied and full output is off. If no flow fits, or the text has no acceptance criteria, it writes nothing and the run ends `blocked` (`no-matching-flow` or `no-acceptance-criteria`) with its one-line reason;
7. checks the output with `scripts/agent_cases.py check`: the case file and questions file must pass `case_lint`, and nothing else may have changed. Otherwise it ends `error`, `invalid-output`, and no PR is opened;
8. saves the questions as the artifact `questions` (for n8n W6), then, as the `qa-agent` app, pushes `agent/<KEY>-cases` and opens PR 1 with the Cases template, so `ci` runs on it;
9. always saves `run-outcome`. An agent step that fails (Claude Max limit, expired token) ends `error`, `agent-failed`, with the hint that a QA member can run `/draft-cases` on a laptop instead.

**Secrets it expects** (Story 4.4 setup): the secret `CLAUDE_CODE_OAUTH_TOKEN`, the variable `QA_AGENT_APP_ID` and the secret `QA_AGENT_PRIVATE_KEY`, wherever the team decides on GitHub Free. It holds no UAT, database or Slack secret, and runs only from `main`.

**Known gap on GitHub Free: pushing to `main`.** The story expects branch protection to refuse an agent push to `main`. Free has no branch protection, so the `qa-agent` app's "Contents: write" could technically push to `main`. What stops it today:
- the agent has no git or shell tools beyond the named checkers;
- the workflow pushes only the explicit `refs/heads/agent/<KEY>-cases`;
- a test checks the workflow file for that.

On a plan with branch protection, protect `main` and record here that an agent push is refused.

**Try it now, before the setup exists:** run it with any key, for example `PM-1`. With `AGENT_ENABLED` not created yet, it should end at step 3 with "Result: Not run (agent is turned off)" and a `run-outcome` artifact whose status is `disabled`. That checks the shared first and last steps live.

**Checked on 4 Oct 2026 (unit tests only):** every decision above, including a run that ends `ok` with the PR link and an invalid key recorded as an empty ticket. The full run waits for the Story 4.4 setup.

### `generate-tests` workflow (Story 4.6)

**Actions → generate-tests → Run workflow** (on `main`), with the same two inputs as `draft-cases`. It runs the same first steps as `draft-cases`: hide the ticket text, check the key, the kill switch and daily limit, and whether the agent is set up. Then:
1. **Cases must be merged.** If `cases/<KEY>.md` isn't on `main`, it ends before any model call: "Result: Blocked — cases for <KEY> are not merged on `main` yet. Merge PR 1; this retries on its own after that." (`blocked`, `cases-not-merged`). Blocked runs don't count toward the daily limit, and n8n W1 retries once the case file is merged. If PR 2 is already open, it ends `ok`, `already-open`, with that PR's link.
2. **The agent** writes the tests following `/generate-api-tests`. Its tools are file tools plus the flow-tag linter, pytest collection, the type check and `ruff`. It **can't run the tests**: the job has no UAT, database or Slack settings. If it can't automate a case with the existing helpers, it changes nothing and the run ends `blocked` (`cannot-automate` or `case-file-unusable`).
3. **The check** (`scripts/agent_cases.py check --kind tests`) opens no PR and ends `error` if the agent:
   - changed a workflow file under `.github/` or `flows/quarantine.yaml` (`forbidden-change`);
   - added a skip, skipif, xfail, fixme or only, even the account guard some specs have (`weakened-test`);
   - changed anything outside the test folders, the page objects, `api-tests/utils/api_client.py` and `flows/inventory.yaml`, or wrote no test (`invalid-output`);
   - left the flow-tag linter, pytest collection or the type check failing (`invalid-output`).
   Skips that were already on `main` aren't counted.
4. **PR 2** is opened as `qa-agent` on `agent/<KEY>-tests` with the Tests template, so `ci` runs. It says "UAT: **not run yet.**" and that the tests haven't run anywhere. `uat-pr` stays expected but missing until a QA member who approved the PR starts it with the head commit SHA (Story 1.5).
5. `run-outcome` is always saved; a model or token failure ends `error`, `agent-failed`, with the hint to run `/generate-api-tests` on a laptop.

**The B6 exit check** (people, once the Story 4.4 setup exists): the QA lead runs `draft-cases` for one real ticket, merges PR 1, then runs `generate-tests`. Both must give reviewable PRs, and neither may push to `main` (see the GitHub Free gap under `draft-cases`).

**Checked on 4 Oct 2026 (unit tests):** every decision above, using a small Git repository in the tests. The real flow-tag linter, collection and type check were also run on this repository through the check's own code, and passed.

### `triage` workflow (Story 6.2)

**Actions → triage → Run workflow** (on `main`) with a nightly run's ID, the number in its URL. n8n W2 will start it after a failed nightly (Story 6.3). Its run title is `triage <nightly run ID>`. In order, it:
1. checks the ID is a number (otherwise `error`, `invalid-nightly-run-id`);
2. runs the shared first step: kill switch, and the `triage` daily limit (2 in `AGENT_CAPS`);
3. checks the Claude token is set up. Triage opens no PR, so it needs no `qa-agent` app;
4. downloads **only** that nightly run's `triage-input`, the masked text from Story 6.1, and checks its contract; an unknown `schema_version` or a file for another run is rejected. A run with no `triage-input` ends `blocked`, `no-triage-input`, which doesn't count toward the limit;
5. runs the agent with **only the Read and Write tools** (no shell, edit, web or Jira/Slack tools). For each failure it chooses product defect (with a drafted bug title), test defect, environment, flaky or unknown, plus a one-line reason;
6. checks the result (`scripts/agent_triage.py check`):
   - **flaky without evidence becomes unknown**, with the reason starting "Downgraded from flaky": the evidence must be a pass on retry tonight, or a failure or retry pass in the last 7 nights;
   - every input test must appear exactly once;
   - a bug title is required for product defects and only allowed there;
   - `contracts/triage.schema.json` must pass, and no repository file may have changed;
   anything else ends `error`, `invalid-triage`, and nothing is saved;
7. saves `triage.json` as the artifact `triage` (30 days), and always `run-outcome`. A model or token failure ends `error`, `agent-failed`.

Triage only suggests: it never changes a test result, the gate or a file. People decide by reacting in Slack (Stories 6.4–6.6).

**Try it now, before the setup exists:** run it with any nightly run ID. With `AGENT_ENABLED` not created, it should end at step 2 with "Result: Not run (agent is turned off)".

**The B6 exit check** (people, after the Story 4.4 setup): make a nightly fail on purpose, run triage on it by hand, and check that `triage.json` makes sense.

**Checked on 4 Oct 2026 (unit tests):** the ID check; the token-only setup check; the download of only `triage-input` (and its contract and run-ID checks); the flaky rule in six history cases; the "every test exactly once" and bug-title rules; and the repository-unchanged check.

## Kill switch and daily limits (Story 5.6)

**Turning AI work off and on.** In GitHub: **Settings → Secrets and variables → Actions → Variables**, the repository variable `AGENT_ENABLED`. Only the exact value `true` lets AI work run. `false`, any other value, or no variable at all counts as off. Only people change it (the QA lead or n8n maintainer), never a workflow.

**Daily limits.** The repository variable `AGENT_CAPS` holds each agent workflow's daily limit as JSON: `{"draft-cases": 20, "generate-tests": 20, "triage": 2, "quarantine": 5}`. Only the QA lead changes it. A missing or broken value, or a workflow with no entry, counts as "limit reached".

**Stopping a run already in progress:** open it on the Actions tab and click **Cancel workflow**.

**How n8n obeys them.** Before any AI action (starting an agent workflow, posting triage, asking for a quarantine, writing to Jira), an n8n workflow calls the shared sub-workflow **"Gate: check"** (`n8n/workflows/gate-check.json`) with `action` (`dispatch`, `triage-post`, `quarantine` or `jira-write`), `workflow` (for `dispatch`: the agent workflow, for example `draft-cases`), `target` (usually the ticket key) and `payload` (what is needed to do it later). It answers `allowed: true`, or `allowed: false` with the `reason` and the waiting-list entry. The caller acts only on `allowed: true`. W0, W5, audit writes and the audit export never call it.

- **Off:** the request goes on the waiting list, and is asked about again after 15 minutes (so the audit log isn't filled with a refusal every 5 minutes while AI work stays off). The first skipped action after the switch goes off posts "Alert: AI work is off" (what stops, what still runs, how to turn it back on). The first action after it is back on posts "FYI: AI work is on again". Each goes out once per change, and the switch is read on every check, so everything stops within one polling cycle.
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

## Daily QA update W4 (Story 7.1)

**Nightly side.** The nightly's **Failure list** job also saves `nightly-summary` (30 days, `contracts/nightly-summary.schema.json`, built by `scripts/nightly_summary.py`). It holds the gate's verdict (`passed`, `failed`, or `not-run` when no tests ran), the counts (passed, failed, passed on retry, quarantined, skipped), coverage (flows automated of all flows, worked out like the coverage report), up to 50 failures, the quarantine registry as it was that night, and the links. If its check fails, that step fails and nothing is saved; the test result is unchanged.

**n8n side.** "W4 Daily QA update" (`n8n/workflows/w4-daily-update.json`) runs every day at 04:00 UTC (09:30 IST):
1. reads the last 14 **scheduled** nightly runs (runs started by a merge or by hand don't count as "last night") and downloads each one's `nightly-summary`;
2. builds the update: the header "Daily QA update — <date>, 09:30 IST"; "Nightly UAT: **PASSED**/**FAILED** — N passed, N failed, N passed on retry."; "Coverage: N of M regression flows automated (P%)."; "Flaky rate (last 14 nights): P%." (fewer nights are named; above 2% it adds "Above the 2% target. Review flaky tests and react 🔁 Flaky to quarantine them."); the failures, or "No failures last night."; the quarantined tests with owner, Jira key and deadline; lists cut at 10 with "and N more — see the run"; and the links Nightly run · Allure report;
3. always posts, even without a result: "Nightly run: no result found for last night." when the newest scheduled run is older than 36 hours or saved no summary;
4. adds "AI work is off (`AGENT_ENABLED` is not `true`): failures are not classified." when the switch is off (W4 itself is never stopped by it);
5. writes an audit entry (`n8n:w4-daily-update`, `daily-update-posted` or `daily-update-preview`, with `-ai-off` when the switch is off). If Slack doesn't take the update, the run fails and W0 alerts.

The flaky rate is the tests that failed and then passed on retry, divided by all tests that ran (passed, failed, passed on retry, quarantined), over the nights that have a summary.

**Not there yet:**
- Triage classes and people's decisions (🐞, 🌩️, 🙈 with reasons) come with Epic 6; until then each failure says "no decision yet" and there is no "Ignored" section.
- Datadog: there is no Datadog connection, so the line always says "Datadog: not available."

**Laptop host.** W4 posts only if the Mac is awake with n8n running at 09:30 IST. If it isn't, that day's update is skipped (the next day's covers its own night).

**Checked on 4 Oct 2026:** the message rules are covered by unit tests (failed and passed nights, flaky rate above and below 2%, cutting long lists, no result, AI off). A live run in n8n read GitHub, found no scheduled nightly yet (the 02:30 IST schedule had not run from `main` yet), and correctly previewed "Nightly run: no result found for last night." with the AI-off line, and wrote its audit entry. The first update with real numbers is the morning after the first scheduled nightly that has this story's `nightly-summary` step.

## Weekly audit log W7 (Story 7.2)

"W7 Weekly audit log" (`n8n/workflows/w7-weekly-audit.json`) runs every Monday at 04:00 UTC (09:30 IST) and needs no access to the n8n server:
1. It takes the audit entries of the **last full week**, Monday 00:00 to Monday 00:00 UTC. Running it again in the same week gives the same file. Its own entry is written at run time, so it falls in the next week and is never counted twice.
2. It writes `audit-<last day of the week>.csv` following `contracts/audit-export.schema.json`:
   - a header row with the columns `ts, actor, actor_type, action, target, link`, in that order;
   - UTC times;
   - standard CSV quoting: a value with a comma, quote or line break is quoted, with quotes doubled;
   - CRLF line ends, oldest entry first.
   A week with no entries gives a header-only file.
3. It uploads the file to the QA channel (Slack's `files.getUploadURLExternal`, then sending the file, then `files.completeUploadExternal`). The message is "Weekly audit log: <date range>", one line about the file (or "No entries were recorded this week. The file has only the header row."), and "Columns: ts, actor, actor_type, action, target, link. Times in the file are UTC."
4. It writes its own audit entry (`n8n:w7-weekly-audit`, `weekly-audit-posted` or `weekly-audit-preview`). It runs whatever `AGENT_ENABLED` says.

If Slack refuses or can't be reached, the run fails and W0 alerts; run it again by hand (**Run now**) in the same week to post the same file. Until Slack is set up, nothing is uploaded: the message and the whole CSV are in the execution in n8n as a preview. The upload also needs the Slack app's `files:write` scope (already in the manifest), and `n8n/slack-setup.sh` puts the channel into W7 as well as the post sub-workflow.

**Checking a CSV by hand:** `python scripts/validate_contract.py audit-export audit-2026-10-04.csv`. `scripts/validate_contract.py` now checks CSV contracts (schemas with `x-csv-columns`) row by row.

**Checked on 4 Oct 2026:** a live run took the week 21–27 Sep, which was empty because the audit log started on 1 Oct, and previewed a header-only `audit-2026-09-27.csv` with the "no entries" line, then wrote its audit entry. W7's CSV code was also run on the 134 real entries of 28 Sep–4 Oct (9 different actors), and the file passed the contract check.

## W1 Ticket watcher (Story 5.5)

"W1 Ticket watcher" (`n8n/workflows/w1-ticket-watcher.json`) turns Jira moves into agent runs. Every 5 minutes:
1. **Checks its masking patterns.** It holds a copy of `scripts/masking-patterns.json` pinned by its SHA-256, and re-hashes the copy on every run. If they don't match, it starts nothing and W0 alerts. `ci` (`scripts/check_masking_hash.py`) fails a PR that changes the patterns without regenerating W1's copy.
2. **Finds tickets** in PM that moved, since its last fully successful poll (plus 10 minutes), to:
   - **"In Progress"**, which starts `draft-cases`. This board has no "Ready for Dev" status, so **the QA lead confirms or changes this** in W1's Settings node (`draft_status`);
   - **"Ready to Test"**, which starts `generate-tests`.
   Other statuses and projects are ignored. Its first run starts from that moment.
3. **Skips** any ticket that already has a record for that workflow (`audit.w1_requests`, one per ticket and workflow) or is already on the waiting list, so nothing is started twice.
4. **Reads only the description and the "Acceptance Criteria" field** (`customfield_11600`), turns them into plain text, masks them with the pinned patterns, and cuts them at 15,000 characters.
5. **Asks "Gate: check"** for each request. The waiting list (`audit.deferred_requests`) goes first, oldest first, then new tickets. If allowed, it starts the workflow on `main` with the ticket key and the masked text, records it as `dispatched`, takes it off the waiting list and writes an audit entry (`dispatch-draft-cases` or `dispatch-generate-tests`). If not, the gate keeps it on the waiting list and W1 records it as `deferred`.
6. Saves its checkpoint only when everything above succeeded.

### W1 Follow-up (Story 5.5, part 2)

"W1 Follow-up" (`n8n/workflows/w1-follow-up.json`) runs every 5 minutes. For every request W1 started, it finds the GitHub run by its title (`draft-cases PM-1234`, the workflows' `run-name`) and reads its `run-outcome`:

| The run ended | Follow-up |
|---|---|
| `ok` with a PR | record `done`. Posts S7 "Test cases drafted for <KEY>" (flows, "review and edit PR 1, then merge it to accept the cases.", PR 1 · Jira · Case file) or S9 "Tests generated for <KEY>" ("review every line, approve, then start `uat-pr` with the reviewed commit SHA.", PR 2 · Run workflow: uat-pr · Jira). Once per PR |
| `blocked`, `cases-not-merged` | record `blocked`. Posts S10 "Action needed: tests for <KEY> can't be generated yet" once ("review and merge PR 1. This retries on its own after that."). Once `cases/<KEY>.md` is on `main`, it puts the request back on the waiting list, and W1 starts it again through the gate |
| `blocked`, any other reason | `cases-already-on-main` counts as `done`. Otherwise the record is `blocked` with S10 once, saying what a person must do; a person restarts the workflow by hand |
| `capped` | back on the waiting list until after 00:00 IST, with one S11 per workflow per day |
| `disabled` | back on the waiting list (the gate's "AI work is off" notice already covers it) |
| `error`, no `run-outcome`, or no run with its title 20 minutes after the start | tried again through the waiting list, at most 3 tries in all; then `failed`, with one S10 and the laptop command |

A notice that Slack doesn't take fails the run (W0 alerts) before anything is saved, so it is tried again and never posted twice. Every decision writes an audit entry (`n8n:w1-follow-up`).

### Switching W1 on

**W1 and its follow-up are installed but switched off.** While AI work is off, every ticket W1 sees would join the waiting list, and turning AI on would then start all of them, held back only by the daily limits. When AI work should begin (after the Story 4.4 setup and with `AGENT_ENABLED` = `true`):

```bash
cd n8n
docker compose run --rm --no-deps -T n8n publish:workflow --id=w1TicketWatch001
docker compose run --rm --no-deps -T n8n publish:workflow --id=w1FollowUp000001
docker compose run --rm --no-deps -T n8n publish:workflow --id=w2NightlyWatch01
docker compose run --rm --no-deps -T n8n publish:workflow --id=w3TriagePoster01
docker compose run --rm --no-deps -T n8n unpublish:workflow --id=readyNotice00001
docker compose restart n8n
```

W1's first run then starts from that moment. **Decision (Story 5.7):** the Ready-for-QA notice is switched off at the same time, because W1's S9 "Tests generated" message replaces it and a ticket must not get two messages. Record the date here when that happens.

**Checked on 4 Oct 2026:**
- A manual W1 run read Jira (no tickets had moved in the last 10 minutes) and passed its masking-pin check. n8n's own hash of the copy matched the pin (`0521d2bb…`).
- A temporary copy with the gate replaced by "allowed" started `draft-cases` in GitHub for the made-up ticket `PM-0`. That run's shared first step stopped it as `disabled` (AI work off, no model call) and saved a `run-outcome` artifact with `ticket_key: PM-0`, which n8n read back. That is the full chain n8n → GitHub → first step → run-outcome, working.
- The temporary workflows, the `PM-0` record and W1's checkpoint were removed afterwards. The audit entry for that start remains.
- Part 2, the same day: a fresh `PM-0` start got the title "draft-cases PM-0". "W1 Follow-up" found that run, read its `disabled` outcome, marked the record `deferred` and put it back on the waiting list with its masked text. The real W1 then took it off the list and asked the real gate, which kept it waiting (AI off), so nothing started. That run showed two things, both fixed: the try counter rose although nothing had started (now only real starts count), and while AI is off every 5-minute poll audited a refusal (the gate now asks again after 15 minutes). The test data was removed afterwards.

## Triage in n8n: W2 Nightly watcher (Story 6.3, part 1)

"W2 Nightly watcher" (`n8n/workflows/w2-nightly-watcher.json`) starts triage on its own. Every 5 minutes:
1. it lists `nightly` runs of the last 36 hours that **failed**, and keeps those with no triage request yet (`audit.triage_requests`, one per nightly run) and not already on the waiting list;
2. of those, it keeps only runs whose report job saved a **`failure-list`**, which carries the Slack thread W3 replies in. **A `failure-list` exists only once Slack is set up** (Story 2.4), so until then W2 never starts triage;
3. it asks the gate (kill switch and the `triage` limit) for the waiting list first, oldest first, then the new nights. If allowed, it starts `triage` on `main` with the nightly run's ID, records it as `dispatched`, takes it off the waiting list and writes an audit entry (`dispatch-triage`). If not, the gate keeps it on the waiting list and W2 records it as `deferred`.

At most one triage per nightly run. W2 is installed but **switched off**, with W1 (see "Switching W1 on", which now switches W2 on too).

**"GitHub: read artifact"** (`n8n/workflows/github-read-artifact.json`) is a shared sub-workflow. Given a repository, run ID and artifact name, it returns `{found, data}` with the JSON file inside, using the same two-step download as before (GitHub's storage rejects GitHub's login). W3 uses it.

**Checked on 4 Oct 2026:** the shared step read the real `nightly-summary` of the latest nightly run (status `passed`), and gave `found: false` for a name that doesn't exist. W2 ran against the real runs: no failed nightly in the last 36 hours, so it did nothing.

### W3 Triage poster (Story 6.3, part 2)

"W3 Triage poster" (`n8n/workflows/w3-triage-poster.json`) runs every 5 minutes. For each night W2 started (or the gate kept back), it finds the triage run by its title (`triage <nightly run ID>`) and decides:
- **Classified**, when triage ended `ok`: one reply per failure in the failure list's Slack thread (S2): "Class: <class> (suggested)", the test and its flow, "Why:" with the evidence, "Drafted bug:" for product defects, the suggested reaction ("check the run, then react. Suggested: 🐞 Bug."), the links Run · Allure report, and the legend "React: 🐞 Bug (file in Jira, you are Reporter) · 🔁 Flaky (quarantine PR) · 🌩️ Environment · 🙈 Ignore (reply with a reason) · ↩️ Undo within 24 h. Reply appears in about 2 minutes." A failure triage left out gets an unclassified message.
- **Fallback**, when triage failed, was blocked or capped, didn't say how it ended, didn't finish within 60 minutes of the start, or the gate kept it back for 60 minutes. First S3 in the thread: "Classification didn't run for last night's failures.", the reason, "work from the list above. A QA member can run triage in Claude Code on a laptop. The gate is unchanged." and the triage run link. Then one unclassified message per failure with the same legend, so reactions still work.
- Otherwise it waits.

**Rules:**
- Posting is a gated action. While AI work is off, the gate holds it back and W3 asks again after 15 minutes.
- More than 10 failures still give one message each; the test ID is shortened to its last part.
- W3 never edits the failure list itself.
- Each message is remembered as soon as it goes out (`posted` on the night), so if Slack fails halfway, the run fails (W0 alerts) and the retry posts only the rest.
- Every failure message that really posted gets a row in `audit.message_map` (kind `failure`, channel, ts, test, nightly run, suggested class), which reactions (Story 6.4) use.
- The night is then `posted` or `fallback`, with an audit entry.

**Turning on the "classifying" line:** when triage goes live, set the repository variable `TRIAGE_LIVE` = `true`. The failure list then says "The agent is classifying these. Results appear in this thread." (Story 2.4).

**Needs Slack to be real:** replies go in the failure list's thread, which exists only once Slack is set up. Until then, everything is a preview.

**Checked on 4 Oct 2026:** unit tests cover every decision and both message kinds, retries that skip what was already posted, and shortened IDs. Live: a made-up open request for the real latest nightly run, "started" 61 minutes earlier, was put on the fallback. The real gate refused posting (AI off) and held it back for 15 minutes, so nothing was posted. The test data was removed.

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

## Sanitizer and triage-input (Story 6.1)

After the failure list, the nightly's **Failure list** job builds `triage-input`, the only text the triage AI may ever see.

- **What it keeps:** for each failed, quarantined or passed-on-retry test, the error message, stack trace and failed step names of its last failed attempt, plus its flow, attempts, last 7 nights and whether it is a flaky candidate. These come from the Allure `*-result.json` files in the test output. Screenshots, traces, videos, attachments and raw logs are never read.
- **Masking:** every text is masked with `scripts/masking-patterns.json` before it is cut to size (message 2,000 characters, trace 4,000, at most 10 steps). The patterns cover private keys, JWTs, known token formats (Slack, GitHub, Stripe, AWS, Google, Anthropic), auth headers, `password=` / `token:` style values, passwords in URLs, emails, street addresses, card-like numbers, phone numbers and long hex keys. They are applied in the order listed.
- **Saved file:** the artifact `triage-input` (30 days), checked against `contracts/triage-input.schema.json`. If the check fails, the "Sanitize failures into triage-input" step fails and nothing is saved; the test result and the gate are unchanged. When nothing failed, nothing is saved.

**Changing the patterns.** Edit `scripts/masking-patterns.json`. Each pattern needs `examples` (text it must mask) and a fixture in `scripts/tests/test_sanitize.py`; a pattern without one fails `ci`. Use only regex features that Python and JavaScript share (no named groups, no lookbehind, plain-text replacements): a test checks that both mask every example the same way. n8n W1 (Story 5.5) will keep a copy pinned by its SHA-256 hash, and `ci` (`scripts/check_masking_hash.py`) fails if the pinned hash differs from the file, so update the n8n copy in the same PR.

**Checked on 4 Oct 2026:** a local rehearsal ran a temporary failing pytest test whose message, stack trace and step names held a fake email, street address, card number and bearer token. Its real Allure output went through `run_summary.py` and `sanitize.py`. Every value came out masked, the file passed its contract, and test names, line numbers and short commit IDs were kept.
## Contracts (AD-5)

`contracts/` holds the schema for every file handed between components (`<name>.schema.json`), a sample of each in `contracts/samples/`, and the shared vocabulary.

- `schema_version` comes first in every file.
- A breaking change bumps `schema_version`, and consumers reject versions they don't know.
- Producers validate before saving: `python scripts/validate_contract.py <name> <file>`, or call `validate()` from Python.
- The `ci` check validates every sample (`--samples`), so each schema needs at least one sample.
