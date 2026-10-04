<!-- Title: [<KEY>] Quarantine: <test_id> -->

## Summary
<Rerun evidence.> A QA member (<who>) marked it Flaky.

## What changed
- `flows/quarantine.yaml`: test_id, owner <owner>, Jira <KEY>, deadline <date>

## What happens after merge
The test still runs every night but no longer blocks the gate. Its flow counts as not covered until it is fixed.

## What the reviewer must do
1. Confirm the owner (default from the flow inventory).
2. Merge. Until then, the test keeps gating.

## Links
Jira <KEY> · Slack thread · Run
