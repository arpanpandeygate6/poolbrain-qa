# Test cases

One file per Jira ticket, drafted by `/draft-cases <KEY>` (Story 4.2) and accepted when QA merges its PR. Tests are generated from a case file only after it is on `main`.

- `cases/<KEY>.md`: the cases.
- `cases/<KEY>.questions.json`: clarification questions about the acceptance criteria (`contracts/questions.schema.json`). An empty list means none.

`ci` checks every case file with `scripts/case_lint.py`.

## Format

```markdown
---
ticket: PM-1234
flows: [job-creation]
priority: high        # high, medium or low
layer: api            # api, db or ui, or a list such as [api, ui]
---

# PM-1234 — Job creation with empty route

Source: Jira PM-1234 (acceptance criteria 1–3)

## PM-1234-01 — Job is rejected without a route
Business rule: a job needs a route.
Preconditions: seeded testing company; logged in as office admin.
Steps: create a job with no route via the API.
Expected: the request is rejected with a clear error; no job row is saved.
```

- Flow IDs come only from `flows/inventory.yaml`.
- Cases are numbered `<KEY>-01`, `<KEY>-02`, … in order.
- When `layer` lists more than one layer, each case also has a `Layer:` line.
- When there are clarification questions, the file has the line "Questions sent to Slack for approval" (the questions themselves are only in the `.questions.json` file).
- Only the acceptance criteria being tested are quoted from the ticket, never the rest of its text.
