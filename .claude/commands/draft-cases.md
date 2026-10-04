---
description: Draft test cases for a Jira ticket from pasted ticket text and open PR 1 (Story 4.2)
argument-hint: <JIRA-KEY, for example PM-1234>
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(git *), Bash(gh pr create *), Bash(command -v gh), Bash(api-tests/.venv/bin/python scripts/case_lint.py*), Bash(api-tests/.venv/bin/python scripts/validate_contract.py *)
---

Draft the test cases for Jira ticket **$ARGUMENTS** and open PR 1. Follow `CLAUDE.md` throughout. You have no Jira access: use only the text the QA member pastes.

## 1. Check the key and ask for the text

- If `$ARGUMENTS` is not a Jira key like `PM-1234` (capital letters, a dash, digits), say "Usage: /draft-cases PM-1234" and stop.
- Say exactly: "Paste the ticket text for $ARGUMENTS, then press Enter." Then stop and wait for the reply. Use only that pasted text.

## 2. Start a clean branch from the latest `main`

1. If `git status --porcelain` shows uncommitted changes, stop: "You have uncommitted changes. Commit or stash them, then run /draft-cases again."
2. `git fetch origin main`
3. If `git cat-file -e origin/main:cases/$ARGUMENTS.md` succeeds, stop: "Cases for $ARGUMENTS are already on main. Change cases/$ARGUMENTS.md in a normal PR instead."
4. `git switch -c agent/$ARGUMENTS-cases origin/main`. If that branch already exists, stop and ask the QA member whether to delete it or continue on it.

## 3. Choose the flows

Read `flows/inventory.yaml`. Pick the flow or flows the ticket's acceptance criteria belong to, by their business rules.
**If no flow fits, stop.** Say which behaviour you could not place, list the flow IDs that exist, and ask the QA member to choose one or to ask the QA lead to add a flow. Never invent a flow ID.

## 4. Write `cases/$ARGUMENTS.md`

Follow the format in `cases/README.md` exactly:
- Front matter: `ticket: $ARGUMENTS`, `flows` (from step 3), `priority` (`high`, `medium` or `low`; from the ticket if it says, otherwise `medium`), `layer`.
- **Layer** per case: `api` for behaviour checked through the API, `db` when the result must be checked in the database (read replica), `ui` only for what can only be seen on screen in one of the top 10 UI flows. Prefer `api`/`db` (approach B). If the file mixes layers, list them in `layer` and give each case a `Layer:` line.
- Title `# $ARGUMENTS — <ticket title>`, then `Source: Jira $ARGUMENTS (acceptance criteria …)` naming the criteria the cases test.
- One `## $ARGUMENTS-01 — <short name>` section per case, numbered from 01, each with `Business rule:`, `Preconditions:`, `Steps:` and `Expected:`.
- Cover each acceptance criterion with at least one case, including the obvious failure or edge case. Use the testing company's seeded data and `qa-auto-` names for anything created. No PROD data, no real customer details.
- Quote only the acceptance criteria being tested, never the rest of the ticket text.

## 5. Clarification questions: `cases/$ARGUMENTS.questions.json`

Where an acceptance criterion is unclear or contradicts itself, don't guess: write a question instead, and leave that case out or mark its unclear part in the case text.
- Write the file following `contracts/questions.schema.json`: `{"schema_version": 1, "ticket": "$ARGUMENTS", "questions": [{"number": 1, "question": "…", "about": "AC 2: …"}]}`. Plain questions the ticket author can answer; at most 10.
- With no questions, write the same file with `"questions": []`.
- When there are questions, add the line `Questions sent to Slack for approval` under the Source line of the case file (and nothing else about them there).

## 6. Check

Run `api-tests/.venv/bin/python scripts/validate_contract.py questions cases/$ARGUMENTS.questions.json` and `api-tests/.venv/bin/python scripts/case_lint.py`. Fix every problem they name and run them again until both pass.

## 7. Open PR 1

1. `git add cases/$ARGUMENTS.md cases/$ARGUMENTS.questions.json` and commit with the message `[$ARGUMENTS] Cases: <ticket title in a few words>`.
2. `git push -u origin agent/$ARGUMENTS-cases`
3. Fill in `.github/PULL_REQUEST_TEMPLATE/cases.md` (case count, flows, question count; Questions: "Clarification questions were posted to Slack for QA approval." when there are any, otherwise "None.").
4. If `command -v gh` finds the GitHub CLI, run `gh pr create --base main --head agent/$ARGUMENTS-cases --title "[$ARGUMENTS] Cases: <title>" --body "<filled template>"`. Otherwise print the filled body and the link `https://github.com/<owner>/<repo>/compare/main...agent/$ARGUMENTS-cases?quick_pull=1` (owner and repo from `git remote get-url origin`) and ask the QA member to open the PR there with that title and body.

## 8. Finish

Print exactly these lines:

```
Drafted <N> cases in cases/$ARGUMENTS.md.
Opened PR 1: <PR link, or "open it here: <compare link>">
Next: review and merge PR 1 in GitHub.
```

If there are questions, add one line: "<N> clarification questions are in cases/$ARGUMENTS.questions.json."
