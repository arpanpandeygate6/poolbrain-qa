# Pilot tracking sheet (Story 8.1)

The two-week pilot measures three things against the bars in Story 8.2. Everything here is filled in by people (the QA lead and QA members) through PRs, except `decisions.json`, which is exported from n8n. `scripts/pilot_numbers.py` turns it into the numbers (Actions → pilot-numbers → Run workflow).

## Agreed before the pilot starts (don't change during the pilot)

See `pilot.yaml`: the start and end dates, and the **major-edit rule**. The rule, decided before the pilot:

> An agent PR (`agent/<KEY>-cases` or `agent/<KEY>-tests`) counts as "accepted with major edits" when the reviewer adds the label **`major-edits`** before merging it. A reviewer adds it when they rewrote, removed or added more than about a quarter of what the agent wrote. Merged without the label: accepted without major edits. Closed without merging: rejected.

## The files

| File | Who fills it | What |
|---|---|---|
| `pilot.yaml` | QA lead, before the start | start and end dates, the major-edit rule, who agreed |
| `manual-time.csv` | QA members | minutes of **manual** regression work on job creation, per run: `baseline` (before the pilot) and `pilot` (during it), with date and recorder |
| `triage-marks.csv` | QA lead | agree or disagree for failures triage called **Test defect** or **Unknown**, which no reaction can confirm |
| `gaps.csv` | anyone | gaps in the data (n8n down, Claude Max limits hit, UAT down), with dates |
| `decisions.json` | n8n maintainer, at the end | `n8n/pilot-export.sh <start> <end> > pilot/decisions.json`: every failure message of the pilot with its suggested class and final reaction |
