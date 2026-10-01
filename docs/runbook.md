# PoolBrain QA runbook

Decisions and procedures that are not visible in the code. Each section names the story that set it.

## GitHub plan (Story 1.3, AR-32)

**Plan: not confirmed yet.** The QA lead confirms whether the repository is on GitHub Free, Team or Enterprise and records it here, with the date.

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

- Merge a PR only when `ci` is green and one QA member, not the author, has approved it.
- Before approving, the reviewer runs the UAT tests for the PR on their laptop with `.env.uat`.

## Tool versions and dependency updates (Story 1.3, AR-16)

- Python and Node versions come from `.python-version` and `.nvmrc`. CI reads both files.
- Node packages are installed in CI with `npm ci` from `ui-tests/package-lock.json`.
- Python packages are pinned in `api-tests/requirements.txt`.
- Pinned test dependencies are updated once a month through one PR, which must pass `ci` like any other PR.
