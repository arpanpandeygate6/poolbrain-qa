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
- web fetch, web search, `curl` and `wget` are denied, and so are claude.ai connector and plugin MCP tools (`mcp__claude_ai_*`, `mcp__plugin_*`, and the design plugin's servers by name). The only MCP server allowed is `playwright-test` from `.mcp.json`, used by the healer (Story 4.7; `enabledMcpjsonServers`);
- reading or editing `.env`, `.env.uat`, `.env.preprod`, `.env.prod`, `.env.npp` and `.env.local` is denied, including through common shell commands (`cat`, `head`, `grep`, `sed`, `cp`, `base64` and others). Shell denies can't cover every possible command, so the rule in `CLAUDE.md` still matters.

Plugins synced from the organisation's claude.ai account (for example the "design" plugin, which brings Slack, Atlassian, Asana, Figma, Notion and other MCP servers) can still **load** in a session, even though the deny list stops their tools being used. The laptop check below counts a loaded tool as a fail.

### Laptop connector check

Do this on each QA laptop before it is used for agent work, and again after Claude Code or plugin changes:

1. Log in to Claude Code with the ai.team Claude Max account, and make sure no API key is set (`echo $ANTHROPIC_API_KEY` prints nothing).
2. Start a **fresh** session in the repository folder.
3. Type `/mcp`: the only server allowed is `playwright-test` (approve it the first time it asks). Type `/context`: the only MCP tools allowed are `mcp__playwright-test__…`.
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

### Decision: AI only from laptops

**Decision (5 Oct 2026, the developer):** QA members use the AI only from Claude Code on their laptops (`/draft-cases`, `/generate-api-tests`, the healer). No Claude token goes into GitHub, so the setup below is **not done for now**: `AGENT_ENABLED` and `AGENT_CAPS` are not created, and the `draft-cases`, `generate-tests` and `triage` workflows stay unused. This avoids the open question of using the Claude Max subscription in unattended runs (A7). Because of it, W2 runs in plain mode (see "Triage in n8n"), and the Jira writes from people's reactions have their own switch (see "Decision: people's reactions write to Jira without the AI switch").

### Decision: people's reactions write to Jira without the AI switch

**Decision (5 Oct 2026, the developer):** 🐞 Bug, 🔁 Flaky, ✅ Approve and their ↩️ undos are people's decisions, not AI work, so they no longer ask the AI gate. They have their own switch, the repository variable **`JIRA_WRITES_ENABLED`** (**Settings → Secrets and variables → Actions → Variables**). Only the exact value `true` lets W3b write to Jira. A missing variable, any other value, or a failed read counts as off: nothing is written, the reaction stays unhandled, and W3b looks at it again on its next run (every 2 minutes, while the message is less than 7 days old). The switch is read once per W3b run, so setting it to `false` stops Jira writes within about 2 minutes. **Not created yet:** create it with `true` when the team is ready for reactions to write to the live PM project.

Still behind the AI gate: starting the `quarantine` workflow after 🔁 (it also needs `AGENT_ENABLED` and the `qa-agent` app, which are on hold). So 🔁 creates the owner's Jira Task, but the quarantine PR waits; a QA member can add the entry to `flows/quarantine.yaml` in a PR by hand.

The gate's "AI work is off" alert no longer says Jira writes stop: it reads "The agent will not draft, generate, triage or quarantine." and lists "people's Jira reactions (while `JIRA_WRITES_ENABLED` is `true`)" as still running. This changes the M12 wording in EXPERIENCE.md, on purpose.

**Checked on 5 Oct 2026:** unit tests cover the switch (`true` on; `false`, `TRUE` or a failed read off) for both reactions and undos, and that only the quarantine start still asks the AI gate. Live: a manual W3b run read `JIRA_WRITES_ENABLED`, got "not found" (the variable doesn't exist yet), counted it as off, and finished normally with its lock released. No Jira write was tried. The updated gate is published, and `n8n/slack-setup.sh` was run again so the installed W3b keeps its Slack settings.

### Setup still to do (people, not code)

Nothing below exists yet. The code above is ready for it. It is on hold while "Decision: AI only from laptops" stands.

1. **Repository variables** (QA lead), under **Settings → Secrets and variables → Actions → Variables**: `AGENT_ENABLED` = `true` and `AGENT_CAPS` = `{"draft-cases": 20, "generate-tests": 20, "triage": 2, "quarantine": 5}`. Only people change them. Until they exist, every agent run ends as `disabled` and n8n's gate counts AI work as off.
2. **GitHub App `qa-agent`** (the agent's own identity, like `qa-relay`): create it under the repository owner's **Settings → Developer settings → GitHub Apps**. Webhooks off. Repository permissions: **Contents: read and write** and **Pull requests: read and write** only, with **no Actions permission**. Install it only on this repository. Keep its app ID and a private key for step 4.
3. **Claude token:** on a laptop logged in to the ai.team Claude Max account, run `claude setup-token` and keep the token for step 4. It lasts a year: the QA lead owns renewing it (put a reminder 11 months out), and so the agent stops working when it expires. **Before using it in CI, the QA lead confirms that using the Claude Max subscription in scheduled GitHub runs is within its terms (PRD assumption A7).** Max usage is shared with people's own Claude Code use.
4. **Where the three secrets live** (`CLAUDE_CODE_OAUTH_TOKEN`, the `qa-agent` app ID and private key): the plan is an `agent` Environment restricted to `main`. GitHub Free has none for private repositories, so **the team decides** and records the decision here before anything is added. A repository secret is readable by any workflow on any branch that someone with write access pushes, so if that is the choice, agent workflows must run only from `main` (`workflow_dispatch` on `main`), and PRs that change `.github/` get extra review.

**Owner:** the QA lead owns the variables, the `qa-agent` app and the yearly token renewal.

**Stopping AI work:** set `AGENT_ENABLED` to `false` (see "Kill switch and daily limits"). **Stopping one run already going:** open it on the Actions tab and click **Cancel workflow**.

**Checked on 4 Oct 2026 (unit tests only, as no agent workflow exists yet):** the counting rule passes every case in the shared fixture. Each way of stopping (switch off or any other value, limit reached with outcomes read from artifacts, broken or missing limits) stops before GitHub or a model is asked, and writes a valid `run-outcome`. The first live run will be the `draft-cases` workflow (Story 4.5).

### Playwright healer on a laptop (Story 4.7)

When a UI test fails in CI because the page changed (a locator, a label, a button's text), a QA member can let the healer propose a fix. **Laptops only, against UAT:** `ci` (`scripts/skip_check.py`) fails any workflow that runs the healer.

**What is committed:**
- `.claude/agents/playwright-test-healer.md`: made with `npx playwright init-agents --loop=claude -c ui-tests/playwright.config.ts` (Playwright 1.63.0), then adapted to the house rules. It changes **only page objects in `ui-tests/pages/`**; it never changes assertions, expected values, test data or waits; it never adds `test.fixme`, `test.skip` or `test.only`; and when the feature itself is broken it **stops** and says "The feature failed: …". It can edit existing files but not create new ones.
- `.mcp.json`: the `playwright-test` server, started from the installed Playwright in `ui-tests/node_modules` (the generated file used plain `npx playwright`, which from the repository root would download Playwright).

**Left out on purpose:** the planner and generator agents (tests come from cases through `/generate-api-tests`), and the generated `seed.spec.ts`, a test with no flow tag that the flow-tag check would reject.

**How to use it:**
1. Make sure the UAT settings are in `ui-tests/.env.uat` (on the prototype, start the pretend PoolBrain: README).
2. Start Claude Code in the repository folder and approve the `playwright-test` server when asked.
3. Ask: "Use the playwright-test-healer agent to fix `tests/login.spec.ts`" (or whichever test failed).
4. If it fixed a locator, check the change is only in `ui-tests/pages/`, then open a PR from a new branch titled "[<KEY>] Fix: <summary>" with `.github/PULL_REQUEST_TEMPLATE/fix.md` (Type: "Locator fix (healer)"). Merge only after `ci` and `uat-pr` are green.
5. If it says the feature failed, file the defect in Jira. The test and the gate stay red. If the team decides to park the test, a QA member adds `test.fixme` **with the Jira key in its reason**, and uses the Fix template's "`test.fixme` — link the filed defect" type.

**Skips need a defect (`ci`):** a PR that adds `test.fixme`, `test.skip`, `describe.skip`, a pytest skip or an xfail fails `ci` unless the reason, on the same line or the next, contains a Jira key such as `PM-5678`. Skips already on `main` (for example the specs' "account not set" guard) are left alone. The PR still needs QA approval. `ci` now checks out the full history to compare a PR with its base branch.

**Checked on 5 Oct 2026:**
- The setup was generated on a scratch copy and then adapted.
- The `playwright-test` server started from the repository root with the installed Playwright and listed its tools.
- Unit tests cover the skip rule (six kinds of skip, with and without a key, existing skips untouched) and the "no healer in CI" rule. They also check that the healer has no Write or shell tool, keeps its house rules and uses only its own MCP tools, and that only that server is allowed.
- **Not yet tried:** a real healing session. It needs a fresh Claude Code session (the project settings changed) and a test broken on purpose. The first QA member to try it records the result here.

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

### `quarantine` workflow (Story 6.5)

Turns a quarantine request into a PR that adds one entry to `flows/quarantine.yaml`. n8n W3b starts it after a QA member reacts 🔁 (Story 6.6). By hand: **Actions → quarantine → Run workflow** with the owner's Jira key and the request JSON, following `contracts/quarantine-request.schema.json` (sample in `contracts/samples/`). Its run title is `quarantine <Jira key>`. In order, it:
1. checks the request against its contract and that it names the same Jira key (otherwise `error`, `invalid-request`; an unknown `schema_version` is rejected);
2. runs the shared first step: kill switch, and the `quarantine` daily limit (5 in `AGENT_CAPS`);
3. checks the `qa-agent` app is set up;
4. stops with `ok` if the test is already in `flows/quarantine.yaml` (`already-quarantined`), or if `agent/<KEY>-quarantine` already has an open PR (`already-open`, with its link);
5. adds the entry (test, owner, Jira key, deadline) to `flows/quarantine.yaml`, keeping its comments. **No model is called:** the change is four lines, so `scripts/agent_quarantine.py` writes it, and nothing else can change;
6. as `qa-agent`, pushes `agent/<KEY>-quarantine` and opens "[<KEY>] Quarantine: <test_id>" with the Quarantine template (`.github/PULL_REQUEST_TEMPLATE/quarantine.md`): the rerun evidence and who marked it, what changed, what happens after merge, the reviewer's steps and the links;
7. always saves `run-outcome` (`ok` with the PR link).

**Until QA merges the PR, the test keeps gating.** After the merge, the next nightly reports it as QUARANTINED: it still runs but doesn't gate, and its flow counts as not covered. It can't push to `main` (the GitHub Free gap under `draft-cases` applies the same way).

**Checked on 5 Oct 2026 (unit tests):**
- the request checks (bad JSON, unknown version, missing owner, bad date, mismatched key);
- already quarantined, already open, and the app-only setup check;
- adding to the real file format (comments kept, the empty `[]` replaced) and appending, with awkward values;
- the PR body;
- the nightly's own reader seeing the test as quarantined after the change;
- that the workflow commits only `flows/quarantine.yaml` and calls no model.

## Smoke: read-only release checks (Stories 3.1 and 3.2)

**Smoke tests** live in `api-tests/tests/test_smoke.py`, marked `smoke` and with a flow tag. They **only read**, and **only the testing company's data**:
- On Preprod, PROD and NPP, `ApiClient` refuses every call except reads and the login (`SAFE_METHODS`, `SAFE_CALLS` in `utils/api_client.py`), **before any network call**: "POST jobs refused: prod is read-only (smoke tests may only read). Nothing was sent." Another safe call is added only when the release owner agrees, with the reason.
- Each smoke test checks what it read with `assert_testing_company` (`utils/testing_company.py`) against `TESTING_COMPANY_ID`. That ID is required on Preprod, PROD and NPP, and the test fails without it; on UAT and the pretend site the check is skipped when it's empty.
- How tests log in is chosen by which variables are set (`Settings.auth_mode`): a testing-company **API key** (`API_TOKEN`), or, until such keys exist, the **testing-company user** (`API_USER_EMAIL`, `API_USER_PASSWORD`), without OTP bypass. Preprod, PROD and NPP still run only in CI (`CI=true`); on a laptop they are refused.

**Porting Postman (Story 3.1):** `api-tests/postman-mapping.md` lists every Postman release-gate request and the test that replaces it, with the porting rules. **It is empty until the collection arrives.** The one check today, "the customer list answers and holds only the testing company's customers", isn't from Postman.

**One button (Story 3.2):** **Actions → smoke → Run workflow** (`.github/workflows/smoke.yml`), choosing `all`, `uat`, `preprod`, `prod` or `npp` ("read-only, testing company only"):
- one job per environment, 10 minutes each, where one failure doesn't stop the others; each runs only `pytest -m smoke` with `CI=true` and `POOLBRAIN_ENV`;
- each job's summary: "## smoke — PASSED" or "FAILED", the environment, commit, who started it, the IST time, a table of **every check** with PASSED or FAILED (`run_summary.py --every-check`), and the Allure link. A run cut off at 9 minutes says "FAILED: timed out after 10 minutes.";
- runs only from `main`;
- **UAT** runs against the pretend PoolBrain until there is UAT access.

**Preprod, PROD and NPP credentials (GitHub Free):** the plan is a `prod-smoke` Environment restricted to `main` (and `uat-nightly` for UAT). Free has no Environments for private repositories, so until the team decides where they live, those jobs end "## smoke — NOT RUN" with the names they need: `<ENV>_API_BASE_URL`, `<ENV>_TESTING_COMPANY_ID`, and `<ENV>_API_TOKEN` or `<ENV>_API_USER_EMAIL` plus `<ENV>_API_USER_PASSWORD` (for example `PROD_API_BASE_URL`). On a plan with Environments, create `prod-smoke` (deployment branch: `main` only), put the credentials there, and uncomment the `environment:` line in `smoke.yml`. **Owner: the QA lead; rotate the credentials every 90 days** (record the next date here).

**Checked on 5 Oct 2026:**
- Unit tests (`api-tests/unit/test_smoke_helpers.py`): writes refused on PROD with nothing sent, reads and the login allowed, the login choice, PROD refused outside CI, and the testing-company check.
- Against the pretend PoolBrain: the smoke test passed as UAT, and the whole API suite still passed. As `prod` in CI mode, the non-smoke tests were skipped, the smoke test failed because `TESTING_COMPANY_ID` was missing, and creating a job was refused before anything was sent.
- The workflow itself first runs after this is merged: try **Run workflow → uat**, then **all** (Preprod, PROD and NPP should say "NOT RUN").

## Kill switch and daily limits (Story 5.6)

**Turning AI work off and on.** In GitHub: **Settings → Secrets and variables → Actions → Variables**, the repository variable `AGENT_ENABLED`. Only the exact value `true` lets AI work run. `false`, any other value, or no variable at all counts as off. Only people change it (the QA lead or n8n maintainer), never a workflow.

**Daily limits.** The repository variable `AGENT_CAPS` holds each agent workflow's daily limit as JSON: `{"draft-cases": 20, "generate-tests": 20, "triage": 2, "quarantine": 5}`. Only the QA lead changes it. A missing or broken value, or a workflow with no entry, counts as "limit reached".

**Stopping a run already in progress:** open it on the Actions tab and click **Cancel workflow**.

**How n8n obeys them.** Before any AI action (starting an agent workflow, posting triage, asking for a quarantine), an n8n workflow calls the shared sub-workflow **"Gate: check"** (`n8n/workflows/gate-check.json`) with `action` (`dispatch`, `triage-post`, `quarantine` or `jira-write`; since 5 Oct 2026 nothing uses `jira-write`, see "Decision: people's reactions write to Jira without the AI switch"), `workflow` (for `dispatch`: the agent workflow, for example `draft-cases`), `target` (usually the ticket key) and `payload` (what is needed to do it later). It answers `allowed: true`, or `allowed: false` with the `reason` and the waiting-list entry. The caller acts only on `allowed: true`. W0, W5, audit writes and the audit export never call it.

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
2. builds the update: the header "Daily QA update — <date>, 09:30 IST"; "Nightly UAT: **PASSED**/**FAILED** — N passed, N failed, N passed on retry."; "Coverage: N of M regression flows automated (P%)."; "Flaky rate (last 14 nights): P%." (fewer nights are named; above 2% it adds "Above the 2% target. Review flaky tests and react 🔁 Flaky to quarantine them."); the failures with their class and decision (see "Decisions" below), or "No failures last night."; "Ignored (with reasons)"; the quarantined tests with owner, Jira key and deadline; lists cut at 10 with "and N more — see the run"; and the links Nightly run · Allure report;
3. always posts, even without a result: "Nightly run: no result found for last night." when the newest scheduled run is older than 36 hours or saved no summary;
4. adds "AI work is off (`AGENT_ENABLED` is not `true`): failures are not classified." when the switch is off (W4 itself is never stopped by it);
5. writes an audit entry (`n8n:w4-daily-update`, `daily-update-posted` or `daily-update-preview`, with `-ai-off` when the switch is off). If Slack doesn't take the update, the run fails and W0 alerts.

The flaky rate is the tests that failed and then passed on retry, divided by all tests that ran (passed, failed, passed on retry, quarantined), over the nights that have a summary.

**Decisions (5 Oct 2026).** Before building the update, W4 reads the failure messages of the last 3 days from `audit.message_map`, each with its live decision from `audit.reaction_decisions` (undone ones don't count), and keeps last night's. Each failure line is "`test` — status — class — decision":
- the class is the one W3 posted, or "Not classified" (plain mode). A failure with no Slack message (Slack off, or not posted yet) shows no class;
- the decision is the reaction as emoji and word, the Jira key for 🐞 and 🔁, and the person, for example "🐞 Bug PM-5678 by @asha" or "🌩️ Environment by @ravi". It is "no decision yet" when nobody has reacted, and "🙈 Ignore by @asha, waiting for a reason" until the reason reply arrives;
- names are plain text (the Slack display name), so the update doesn't notify people every morning;
- failures ignored with a reason move to "Ignored (with reasons)": '`test` — 🙈 Ignore by @asha: "reason"', with the reason on one line and cut at 200 characters;
- if the audit database doesn't answer, the update still posts, with "no decision yet" and the line "Decisions: not available (the audit database didn't answer)."

While `JIRA_WRITES_ENABLED` is not `true`, 🐞 and 🔁 wait (see "W3b Reactions"), so they show as "no decision yet" until Jira takes them.

**Not there yet:**
- Datadog: there is no Datadog connection, so the line always says "Datadog: not available."

**Laptop host.** W4 posts only if the Mac is awake with n8n running at 09:30 IST. If it isn't, that day's update is skipped (the next day's covers its own night).

**Checked on 5 Oct 2026 (decisions):** unit tests cover every kind of decision line, decisions of other nights left out, the Ignored section with a long reason, and the database not answering. The query ran in Postgres as W4's own user (`audit_writer`); with sample rows inside a transaction that was rolled back, an ignored failure came back with its person and reason, and an undone decision came back as no decision. The new W4 is installed and published; the next 09:30 IST update is the first to use it.

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
docker compose run --rm --no-deps -T n8n publish:workflow --id=w6QuestionsPost1
docker compose run --rm --no-deps -T n8n publish:workflow --id=w3bReactions0001
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

**Plain mode (the default, 5 Oct 2026).** AI is used only from laptops, never in GitHub (see "Decision: AI only from laptops"), so W2's Settings node has `triage_mode` = `plain`. Only the exact value `agent` starts AI triage as described above. In plain mode, step 3 changes: W2 records each new failed night as `plain` in `audit.triage_requests`, never asks the gate and never starts `triage`. W3 then posts the plain messages (below). The waiting list is left alone.

**"GitHub: read artifact"** (`n8n/workflows/github-read-artifact.json`) is a shared sub-workflow. Given a repository, run ID and artifact name, it returns `{found, data}` with the JSON file inside, using the same two-step download as before (GitHub's storage rejects GitHub's login). W3 uses it.

**Checked on 4 Oct 2026:** the shared step read the real `nightly-summary` of the latest nightly run (status `passed`), and gave `found: false` for a name that doesn't exist. W2 ran against the real runs: no failed nightly in the last 36 hours, so it did nothing.

### W3 Triage poster (Story 6.3, part 2)

"W3 Triage poster" (`n8n/workflows/w3-triage-poster.json`) runs every 5 minutes. For each night W2 started (or the gate kept back), it finds the triage run by its title (`triage <nightly run ID>`) and decides:
- **Classified**, when triage ended `ok`: one reply per failure in the failure list's Slack thread (S2): "Class: <class> (suggested)", the test and its flow, "Why:" with the evidence, "Drafted bug:" for product defects, the suggested reaction ("check the run, then react. Suggested: 🐞 Bug."), the links Run · Allure report, and the legend "React: 🐞 Bug (file in Jira, you are Reporter) · 🔁 Flaky (quarantine PR) · 🌩️ Environment · 🙈 Ignore (reply with a reason) · ↩️ Undo within 24 h. Reply appears in about 2 minutes." A failure triage left out gets an unclassified message.
- **Fallback**, when triage failed, was blocked or capped, didn't say how it ended, didn't finish within 60 minutes of the start, or the gate kept it back for 60 minutes. First S3 in the thread: "Classification didn't run for last night's failures.", the reason, "work from the list above. A QA member can run triage in Claude Code on a laptop. The gate is unchanged." and the triage run link. Then one unclassified message per failure with the same legend, so reactions still work.
- **Plain**, for a `plain` night (W2's plain mode): the fallback at once, **without the gate**, because no AI is involved. The messages come only from the failure list. S3 gives the reason "AI triage is used only on laptops, not in GitHub (`plain`)", then one "Not classified" message per failure with the reaction legend. The night ends as `fallback` with reason `plain`.
- Otherwise it waits.

**Rules:**
- Posting AI results (or their fallback) is a gated action. While AI work is off, the gate holds it back and W3 asks again after 15 minutes. Plain nights skip the gate: W3 splits the nights at "Needs the gate?" and joins them again at "Nights to post".
- More than 10 failures still give one message each; the test ID is shortened to its last part.
- W3 never edits the failure list itself.
- Each message is remembered as soon as it goes out (`posted` on the night), so if Slack fails halfway, the run fails (W0 alerts) and the retry posts only the rest.
- Every failure message that really posted gets a row in `audit.message_map` (kind `failure`, channel, ts, test, nightly run, suggested class), which reactions (Story 6.4) use.
- The night is then `posted` or `fallback`, with an audit entry.

**Turning on the "classifying" line:** when triage goes live, set the repository variable `TRIAGE_LIVE` = `true`. The failure list then says "The agent is classifying these. Results appear in this thread." (Story 2.4).

**Needs Slack to be real:** replies go in the failure list's thread, which exists only once Slack is set up. Until then, everything is a preview.

**Checked on 4 Oct 2026:** unit tests cover every decision and both message kinds, retries that skip what was already posted, and shortened IDs. Live: a made-up open request for the real latest nightly run, "started" 61 minutes earlier, was put on the fallback. The real gate refused posting (AI off) and held it back for 15 minutes, so nothing was posted. The test data was removed.

### Switching on the failure messages (plain mode, no AI)

With plain mode, each failure of a failed nightly gets its own "Not classified" message in the failure list's Slack thread, so people can react to it. This needs Slack on in GitHub (the nightly saves a `failure-list` only then). To switch it on, publish W2, W3 and W3b (not W1, W1 follow-up or W6):

```bash
cd n8n
./audit-setup.sh   # once, adds the `plain` state to audit.triage_requests
docker compose run --rm --no-deps -T n8n publish:workflow --id=w2NightlyWatch01
docker compose run --rm --no-deps -T n8n publish:workflow --id=w3TriagePoster01
docker compose run --rm --no-deps -T n8n publish:workflow --id=w3bReactions0001
docker compose restart n8n
```

**What reactions do:** 🌩️ Environment and 🙈 Ignore work fully. 🐞 Bug, 🔁 Flaky and ✅ Approve write to Jira only while `JIRA_WRITES_ENABLED` is `true`; until then they wait. After 🔁, the quarantine PR still waits for the AI gate.

**Checked on 5 Oct 2026:** unit tests cover plain mode in W2 (the default, and the waiting list is skipped) and W3 (fallback at once, the gate skipped, the reason line, answers matched to nights). The merge step was tried in n8n 2.41.5 with throwaway workflows: it ran once with plain nights only, gated nights only, and both. Live: W2 found no failed nightly in the last 36 hours, so it did nothing. A made-up `plain` request for a passed nightly (37292202078) went through W3 without the gate, found no `failure-list`, posted nothing and was saved as `fallback` (`plain`). The test row was removed. Its audit entry (`triage-fallback-posted`, "nightly 37292202078 (plain)") remains, because the audit log is append-only.

## W6 Questions poster (Story 6.7, part 1)

"W6 Questions poster" (`n8n/workflows/w6-questions-poster.json`) runs every 5 minutes. For each `draft-cases` run of the last 2 days that finished successfully and hasn't been handled (`audit.w6_runs`, one row per run):
1. it reads the run's `questions` artifact with "GitHub: read artifact";
2. it checks it against the questions contract. n8n can't run the Python validator, so W6 has a JavaScript copy of the rules, and a test checks that both agree on 13 good and bad cases;
   - **no file or no questions:** recorded as `none`, nothing posted;
   - **invalid** (including an unknown `schema_version`): recorded as `invalid`, nothing posted, and the run fails so W0 reports it, once;
3. otherwise it asks the gate (`questions-post`). While AI work is off, nothing is posted, and it asks again after 15 minutes;
4. it posts S8 at the top level: "Questions about <KEY> before testing", "The agent found unclear acceptance criteria:", the numbered questions, "react ✅ to add these to <KEY> as a comment naming you. Nothing goes to Jira without ✅.", the links PR 1 (from the run's `run-outcome`) · Jira, and the legend "React: ✅ Approve (send to Jira) · ↩️ Undo within 24 h";
5. it records the run as `posted` (or `preview` while Slack isn't set up), maps a really posted message in `audit.message_map` (kind `questions`, ticket, `source_run_id`) for the ✅ reaction (W3b), and writes an audit entry. A post Slack didn't take is not recorded, so it is tried again, and the run fails so W0 alerts.

Each run is posted at most once. W6 is installed but **switched off** with W1 (see "Switching W1 on").

**Checked on 5 Oct 2026:**
- Unit tests: the contract copy agrees with the Python validator, plus the states, the message, the saved rows and the error report.
- Live: W6 found the two real `draft-cases` runs (the `PM-0` tests) and recorded both as `none`, since they stopped before drafting and had no questions.

## W3b Reactions (Story 6.4, part 1: reading reactions, 🌩️ and 🙈)

"W3b Reactions" (`n8n/workflows/w3b-reactions.json`) runs every 2 minutes, **one run at a time**: a lock in `audit.relay_state` (`w3b-lock`), released at the end. A run that dies leaves the lock to expire after 5 minutes. With no Slack channel set, it does nothing.

**What counts:**
- only messages in `audit.message_map` up to **7 days old**, and only the **first valid reaction** Slack lists for each:
  - on `failure` messages: 🐞 Bug, 🔁 Flaky, 🌩️ Environment, 🙈 Ignore;
  - on `questions` messages: ✅ Approve;
  - ↩️ Undo is handled separately (Story 6.8);
- only reactions from the **QA group**, set in `n8n/.env` and filled in by `n8n/slack-setup.sh`:
  - `SLACK_QA_GROUP`, a Slack user group ID. User groups need a paid Slack plan;
  - and/or `SLACK_QA_MEMBERS`, a comma-separated list of member IDs (in Slack: a profile → ⋮ → Copy member ID). This works on any plan.

Everything else is ignored with no reply: other emoji, people outside the group, older messages, second reactions. Removing a reaction undoes nothing. Slack names each emoji (🐞 is `lady_beetle` or `ladybug`); the names are in `contracts/vocabulary.json` (`slack_names`), and W3b's copy is checked by a test.

**Decisions** (`audit.reaction_decisions`, at most one live decision per message; never deleted):
- **🌩️ Environment:** recorded, with a thread reply: "<@member> marked this failure 🌩️ Environment. The gate is unchanged. This will show in the daily update." and "↩️ within 24 h to undo". Nothing goes to Jira. Audit entry with the member's email as actor.
- **🙈 Ignore:** W3b asks once in the thread: "<@member>, to record 🙈 Ignore, reply in this thread with a short reason. Nothing is recorded until then." When that member's reply arrives, the reason is recorded and confirmed ('… Reason: "…". The gate is unchanged.'), with an audit entry.
- **🐞 Bug, 🔁 Flaky and ✅ Approve** write to Jira (parts 2 and 3, below).

W3b needs the Slack app's `reactions:read`, `channels:history` (`groups:history` for a private channel), `usergroups:read`, `users:read` and `users:read.email` scopes, which are all in the manifest. A member whose email can't be read is recorded as `<member ID>@slack.invalid`. W3b is installed but **switched off** with W1.

**Checked on 5 Oct 2026:**
- Unit tests: the emoji names match the vocabulary; ten cases for the first valid reaction (wrong emoji, outsider, wrong message kind, skin tones, ↩️, nothing); the QA group from a user group or a list; the replies; and the 🙈 reason (only that member's reply after the prompt counts).
- Live, without Slack: W3b stopped at "Slack set up?". Its lock (a second lock refused), the load query, the release, and recording a decision (a second reaction refused; a reason recorded once) were run against the real database. The test rows were deleted.

### W3b part 2: 🐞 Bug and ✅ Approve (Stories 6.4 and 6.7)

Both are **Jira writes**, so they run only while `JIRA_WRITES_ENABLED` is `true` (W3b reads it once per run, right after taking its lock). Otherwise nothing is written, the reaction stays unhandled, and it is looked at again on the next run. Before 5 Oct 2026 this was the AI gate (`jira-write`); a reaction the gate had already held back still waits out that hold. 🌩️ and 🙈 run first, so a Jira problem can't hold them up.

**🐞 Bug** calls the sub-workflow "Reaction: file bug" (`n8n/workflows/reaction-file-bug.json`). It:
1. finds the member's Jira account: first in its **`account_map`** setting, then by email search;
2. creates a **Bug** in PM:
   - the summary is the drafted bug title, or "Nightly failure: <test>" when unclassified;
   - the label is `filed-via-qa-bot`, because Jira labels can't contain spaces;
   - the description opens with "Filed via QA bot, by <name> from Slack.", then gives the run date, the test, the flow, and links (Nightly run · Allure report · Slack thread). It never includes error text or other raw evidence;
   - **Reporter = the member**;
3. if Jira refuses the Reporter (the ai.team account lacks "Modify Reporter"), creates the bug without it;
4. reads the bug back. If the member isn't the Reporter, it adds the S20 comment "Filed by <name> (<email>) via Slack. Jira didn't accept them as Reporter. Filed via QA bot.";
5. any other Jira error fails the run (W0 alerts), and the reaction stays unhandled for a later run.

**✅ Approve** (on a `questions` message) calls "Reaction: send questions" (`n8n/workflows/reaction-send-questions.json`). It reads the `draft-cases` run's `questions` file and `run-outcome`, then adds the S19 comment to the ticket: "Clarification questions from QA, approved by <name> — Filed via QA bot", the numbered questions, and links to PR 1 and the Slack thread.

After either, W3b **records the decision straight away** (with the Jira key and link), before replying, so a failed reply can never file a second bug. Then it replies in the thread:
- 'Bug PM-… filed by @member. Labelled "Filed via QA bot".', or the Reporter-fallback wording;
- or "Questions added to PM-… as a comment naming @member.";

with "↩️ within 24 h to undo", and an audit entry with the member's email.

**Before 🐞 is used:**
- Ask the Jira admin for **"Modify Reporter"** in PM for the ai.team account.
- **Fill in `account_map`**, in the "Settings" node of "Reaction: file bug": `{"member@gate6.com": "<Jira accountId>"}` for each QA member, with emails in lower case. A Jira accountId is the last part of the URL of that person's Jira profile. The read-only check on 5 Oct 2026 found that **Jira's email search returned nobody**, not even the ai.team account, because Jira hides most emails. Without this list, every bug takes the "Filed by" comment fallback.

**Checked on 5 Oct 2026:**
- Unit tests: the bug fields (no raw evidence, Reporter set, the links), Reporter from the list, the three creation outcomes (created; Reporter refused; other error), the read-back check, the S20 comment, the questions comment, the gate wait, and the replies.
- Read-only Jira checks: PM has the issue types Story, Task, **Bug**, Epic and Subtask, and the email search answers but finds nobody.
- **Nothing was written to Jira:** these paths are first used for real after Slack and the Story 4.4 setup, on a staged failure (B9 exit check).

### W3b part 3: 🔁 Flaky (Story 6.6)

Also a Jira write, so it needs `JIRA_WRITES_ENABLED` = `true` first. "Reaction: flaky" (`n8n/workflows/reaction-flaky.json`):
1. reads `flows/inventory.yaml` and `flows/quarantine.yaml` from `main`. If the test is **already quarantined**, or its flow has **no owner** (missing or "TBD"), it creates nothing. W3b records that and replies: "Nothing was created: this test is already in the quarantine list." or "…the flow `<flow>` has no owner in the flow inventory. QA lead to add it to the inventory, then undo ↩️ and react 🔁 again.";
2. builds the rerun evidence from that night's `failure-list` ("Failed 2 of the last 4 nights, passed on retry.");
3. creates the owner's **Task** in PM first (S18): "Flaky test: <test>", label `filed-via-qa-bot`, **due date two weeks from today**, the owner, "Marked flaky by <name>" with the evidence, "A quarantine PR is opened by the QA bot only while AI work is on; otherwise a QA member adds the test to flows/quarantine.yaml in a PR. The test keeps gating until QA merges the quarantine PR.", and links. (Before 6 Oct 2026 it promised the PR would be opened, which isn't true while AI work is off.) Reporter works as for 🐞 (`account_map`, or the "Filed by" comment);
4. returns a `quarantine-request` that follows its contract.

W3b then records the decision, puts the **quarantine request on the waiting list** (`audit.deferred_requests`, workflow `quarantine`), and replies "Quarantine requested by @member. Owner ticket PM-… created. The quarantine PR opens by itself only while AI work is on; otherwise a QA member adds the test to `flows/quarantine.yaml` in a PR. The test keeps gating until QA merges the quarantine PR." The waiting list is queued **before** the reply, so a failed reply can't lose the request.

**Starting the quarantine workflow:** in every run, after the reactions, W3b takes due quarantine requests oldest first, asks the gate (kill switch and the `quarantine` limit of 5 a day), starts `quarantine` with the Jira key and the request, and marks them started (audit `dispatch-quarantine`). A request the gate holds back, or one whose start fails, stays on the list and is retried. The Jira ticket stays either way. When the limit is reached, the gate posts its "waits until tomorrow" notice.

**Note: every flow owner in `flows/inventory.yaml` is still "TBD",** so 🔁 replies "owner missing" until the QA lead fills them in.

**Checked on 5 Oct 2026:**
- Unit tests: the owner (TBD, named, other flow, unknown flow, already quarantined), the owner ticket (summary, Task, due date, evidence, description), the request passing the real `quarantine-request` contract, the three replies, which decisions are queued, the gate on due requests, and that queueing comes before the reply.
- Database: the queue queries (queued once, due, started) were run on the real database, and the test row was deleted.
- **Nothing was written to Jira.**

### W3b part 4: ↩️ Undo within 24 hours (Story 6.8)

A QA member reacts ↩️ on a message whose decision is handled. **Nothing is ever deleted** in Jira, GitHub or the audit table.

| Undone | What W3b does |
|---|---|
| 🐞 bug | "Reaction: undo" (`n8n/workflows/reaction-undo.json`) moves the bug to the first available of Won't Do, Cancelled, Canceled, Closed or Done (setting `close_names`), adds the label `qa-bot-undone`, and comments "Undone by <name> via Slack within 24 hours of filing. Nothing was deleted." |
| 🔁 flaky | the same for the owner ticket; an open quarantine PR gets the label `undo-requested` (through `qa-relay`, `issues: write`); a request still on the waiting list is cancelled. A 🔁 that created nothing is just marked reversed |
| ✅ questions | a follow-up comment "These clarification questions were withdrawn by <name> via Slack. Please ignore them." |
| 🌩️ / 🙈 | the decision is marked reversed |

Undos that change Jira also need `JIRA_WRITES_ENABLED` = `true`. While it is off, or if Jira fails, nothing changes; the undo is retried while the 24 hours last, and a Jira failure goes to W0. W3b then marks the decision undone (`undone_at`, `undone_by`), replies S6 "Undone by @member. <what was reversed>. Nothing was deleted. You can now react again on the message above." and writes an audit entry (`undo-<action>`, the member's email). The message is then open for one new valid reaction.

**More than 24 hours after the action:** nothing changes, and W3b replies once: "Undo is closed for this message (more than 24 hours). Ask the QA lead to change <PM-… in Jira, or the decision> by hand."

**Ignored:** a message with no handled decision, a ↩️ from outside the QA group, and a repeated ↩️.

**Two limits that come from Slack** (it doesn't say when a reaction was added, and old reactions stay on the message):
- after an undo, **the same person's same reaction doesn't count again** on that message (it's "used up"): react with a different emoji, or another QA member reacts;
- **each person's ↩️ undoes once per message.** Removing and re-adding the same emoji looks the same to Slack.

**Checked on 5 Oct 2026:**
- Unit tests: used-up reactions, the 24-hour window, the QA group, a used ↩️, the gate wait, which undos go to Jira, the S6 replies (undone and too late), the transition choice, the comments, and that the undo sub-workflow has no delete call.
- A new test parses every Code node in every n8n workflow. It caught a name declared twice in the undo comment, which would have failed every Jira undo, now fixed.
- Database: the undo queries (undo once, a second refused, a new decision allowed afterwards, "too late" noted once, the load listing the used reaction) were run on the real database, and the test rows were deleted.
- Nothing was written to Jira or GitHub.

## Ready-for-QA notice (Story 5.7)

The n8n workflow "Ready-for-QA notice" (`n8n/workflows/ready-for-qa-notice.json`) is the early n8n demo: Jira, GitHub and Slack working together. It only reads Jira and GitHub; it never writes to Jira or starts a GitHub workflow.

- **When:** every 5 minutes. It asks Jira for PM tickets that moved to **"Ready to Test"** (this board's name for "Ready for QA") since its last fully successful poll, plus 10 minutes of overlap. Its first run starts from that moment, so old tickets aren't announced.
- **What it reads:** only each ticket's key and title. It never reads the description or acceptance criteria.
- **The message:** "FYI: PM-123 is ready for QA", the ticket title, "Latest test result (pretend site): **PASSED**" or "**FAILED**" with the workflow and its IST start time (from the newest finished `nightly` run on `main` or `uat-pr` run; cancelled runs are skipped. Since 6 Oct 2026 a nightly started by hand on another branch doesn't count: the end-to-end demo's failing run on `demo/e2e-failure` would otherwise have marked real tickets FAILED), or "No test run yet (pretend site)", and the links Jira · Latest run. "pretend site" is the notice's `test_target` setting (in its Settings node); change it to `UAT` together with `TEST_TARGET` in `nightly.yml`. It goes through "Slack: post message", so it is a preview until Slack is set up.
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

**Where the tests ran, in messages (6 Oct 2026).** `nightly.yml` sets `TEST_TARGET: pretend site`. The failure list header says "(pretend site, <date>)", and the `nightly-summary` carries it as `target`, so the daily update says "Nightly (pretend site): …". Older summaries have no `target` and read as UAT. **When the tests move to UAT, change two things:** `TEST_TARGET` in `nightly.yml` to `UAT`, and `test_target` in the Ready-for-QA notice's Settings node to `UAT`.

**To confirm with the QA lead before running on UAT (Story 2.3):** UAT uses Stripe test mode, the QBO sandbox and the Chargebee test site. Not confirmed yet.

Checked on 1 Oct 2026, in a local rehearsal with temporary tests:

- A test that failed once and then passed was PASSED ON RETRY, and the run was green.
- A failing quarantined test was QUARANTINED, the run was green, and its flow showed as not covered.
- The same failing test without quarantine turned the run red.

## Failure list (Story 2.4)

After the tests, the nightly's separate **Failure list** job builds the plain list of last night's failures. That job holds no test credentials.

- **Which tests:** FAILED, QUARANTINED and PASSED ON RETRY tests, each with its last 7 scheduled nights' results (fewer while there are fewer runs).
- **Parametrized tests (6 Oct 2026):** test IDs leave out a case's `[parameter]`, so the cases of one test share an ID. They are combined into one entry with the most serious status and `cases`, the number of cases with that status (for example "(flow `job-creation`, 3 cases)"). So the test gets one line, one "Not classified" message ("Status: FAILED (3 cases).") and one decision. Before, W3 posted only the first of them. The nightly summary and triage-input combine them the same way.
- **The Slack message** follows EXPERIENCE.md M1: the header "Nightly run failed: N tests (UAT, <date> 02:30 IST)", one line per test (cut at 10, with "and N more — see the run"), a "Passed on retry" section, a "What to do" line, and the labelled links Run · Allure report. Nothing is posted when every test passed with no retries.
- **Triage line:** "The agent is classifying these. Results appear in this thread." appears only when the repository variable `TRIAGE_LIVE` is `true`. It stays unset until the triage epic.
- **Words:** every status word, reaction, triage class, run outcome, notice kind and label comes from `contracts/vocabulary.json`, never from code (UX-DR1).
- **Saved file:** after a successful post, the list is checked against `contracts/failure-list.schema.json` and saved as the artifact `failure-list` (30 days), with the message's `slack_channel` and `slack_ts`. If the check fails, the job fails and nothing is saved. If the Slack post fails, the job fails with the reason and nothing is saved. Either way the test result is unchanged.

**Slack is on (5 Oct 2026).** The "Build the failure list" step gets the repository variable `SLACK_CHANNEL` and the secret `SLACK_BOT_TOKEN`. Without them it shows the message as a preview in its summary and saves no `failure-list`, because the file needs the Slack message's ID.

**Decision (5 Oct 2026, the developer):** on GitHub Free, `SLACK_BOT_TOKEN` is a **repository secret**. It belongs to the QA Bot in the developer's private **test** Slack workspace (`poolbrain-qa-test`, channel `#qa-bot-test`, `C0C6P6Z4JAJ`). Any workflow on any branch could read it, which is acceptable for a test workspace with no one else in it. **Before switching to the company Slack (Gate6)**, the team decides again: on a plan with Environments, move it to a `notify` Environment restricted to `main` and add `environment: notify` to the report job.

**Slack setup (5 Oct 2026):** the Gate6 Slack doesn't let members install apps (an admin must approve), so a private test workspace with only the developer in it is used for now. n8n has the same bot token (`n8n/slack-setup.sh`), `SLACK_CHANNEL` and `SLACK_QA_MEMBERS` (the developer's member ID) in `n8n/.env`. The first real post was the daily update on 5 Oct 2026 at 14:53 IST. **For the real team:** create the app from `n8n/slack-app-manifest.yaml` in Gate6 and click "Request to install"; once approved, re-run `n8n/slack-setup.sh` with the Gate6 channel, member IDs and token, and replace the GitHub variable and secret.

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

## Pilot numbers (Story 8.1)

The two-week pilot measures three things against the bars in Story 8.2. `pilot/README.md` explains the sheet. In short:

1. **Before the start**, the QA lead fills in `pilot/pilot.yaml` (start and end dates, who agreed). The **major-edit rule** is written there and in `pilot/README.md`: a reviewer adds the label **`major-edits`** before merging an agent PR they changed by more than about a quarter. It doesn't change during the pilot.
2. **During the pilot**, through PRs:
   - QA members add each job-creation regression run's manual minutes to `pilot/manual-time.csv`, as `baseline` (before) or `pilot` (during), with date and recorder;
   - the QA lead marks agree or disagree in `pilot/triage-marks.csv` for failures triage called Test defect or Unknown;
   - anyone notes data gaps (n8n down, Claude Max limits hit, UAT down) in `pilot/gaps.csv`.
3. **At the end**, the n8n maintainer runs `n8n/pilot-export.sh <start> <end> > pilot/decisions.json` (read-only: each failure message with its suggested class and final reaction after any undo) and commits it.
4. **Actions → pilot-numbers → Run workflow** (`.github/workflows/pilot-numbers.yml`, any time) runs `scripts/pilot_numbers.py`:
   - **acceptance:** the agent's PR 1s and PR 2s created during the pilot, merged without `major-edits`, merged with it, or closed (rejected); open PRs are listed, not counted;
   - **triage agreement:** the final reaction matches the suggestion (🐞 Product defect, 🔁 Flaky, 🌩️ Environment; 🙈 never matches), plus the QA marks for Test defect and Unknown. Unclassified messages, ones with no reaction, and unmarked ones are listed, not counted;
   - **time saved:** 1 − average pilot minutes ÷ average baseline minutes.
   Each measure is shown against its bar (70%, 80%, 50%) as met, not met or no data, with every PR and message behind it and the gaps. The job summary shows it, and the artifact `pilot-numbers` keeps it for 90 days. That is the input for the report and decision (Story 8.2).

**Checked on 5 Oct 2026:**
- Unit tests: PR counting (with major edits, rejected, open, not the agent's, before the pilot), the agreement rules (each reaction, 🙈, QA marks, unclassified, no reaction), time saved, the report, and the "dates first" check.
- `n8n/pilot-export.sh` ran on the real database: no failure messages yet, and a bad date was refused.

**Artifact actions updated (5 Oct 2026):** `actions/upload-artifact` v4 → v7 and `actions/download-artifact` v4 → v8, which run on Node.js 24 and so clear the "Node.js 20 is deprecated" warning. Their release notes were checked: artifacts are still zipped (n8n and the scripts read them as zip), hidden files are still left out, `artifact-url` is unchanged, and downloads by name or pattern work as before.
