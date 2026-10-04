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
