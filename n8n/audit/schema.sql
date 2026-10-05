-- Audit log (Story 5.3, FR-26): one append-only record of every agent run,
-- n8n action and QA decision. Safe to run again: it only creates what is missing.
--
-- n8n writes through the `audit_writer` role, which can INSERT and SELECT but
-- not UPDATE, DELETE or TRUNCATE, so entries can't be changed once written.

SET client_min_messages = warning;

CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.audit_log (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT now(),  -- stored in UTC
    actor      text NOT NULL,
    actor_type text NOT NULL CHECK (actor_type IN ('human', 'agent', 'n8n', 'ci')),
    action     text NOT NULL CHECK (action <> ''),
    target     text NOT NULL DEFAULT '',
    link       text NOT NULL DEFAULT '',
    -- Humans are recorded by email; everything else as <type>:<workflow>.
    CONSTRAINT actor_format CHECK (
        (actor_type = 'human' AND actor LIKE '%_@_%')
        OR (actor_type <> 'human' AND actor ~ ('^' || actor_type || ':[a-z0-9][a-z0-9-]*$'))
    )
);

CREATE INDEX IF NOT EXISTS audit_log_ts ON audit.audit_log (ts);

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_writer') THEN
        CREATE ROLE audit_writer LOGIN;
    END IF;
END
$$;

REVOKE ALL ON SCHEMA audit FROM PUBLIC;
REVOKE ALL ON audit.audit_log FROM PUBLIC, audit_writer;
GRANT USAGE ON SCHEMA audit TO audit_writer;
GRANT INSERT, SELECT ON audit.audit_log TO audit_writer;

-- One entry per completed GitHub run (Story 5.3 recorder): a run's link is
-- recorded at most once, so the recorder can safely look back after downtime.
CREATE UNIQUE INDEX IF NOT EXISTS audit_log_run_once ON audit.audit_log (link) WHERE action LIKE 'run-%';

-- Checkpoints that polling workflows keep for themselves (not audit entries,
-- so they may be updated).
CREATE TABLE IF NOT EXISTS audit.checkpoints (
    name  text PRIMARY KEY,
    value timestamptz NOT NULL
);
REVOKE ALL ON audit.checkpoints FROM PUBLIC, audit_writer;
GRANT SELECT, INSERT, UPDATE ON audit.checkpoints TO audit_writer;

-- Gate state (Story 5.6): the last kill-switch value seen, and the day each
-- workflow's "waits until tomorrow" notice was last posted, so each notice
-- goes out once per change or once per day. Not audit entries, so updatable.
CREATE TABLE IF NOT EXISTS audit.relay_state (
    name       text PRIMARY KEY,
    value      text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON audit.relay_state FROM PUBLIC, audit_writer;
GRANT SELECT, INSERT, UPDATE ON audit.relay_state TO audit_writer;

-- Requests the gate did not let through (AI work off, daily cap reached):
-- kept here so nothing is lost. The workflow that made a request picks it up
-- again once not_before has passed, in arrival order, and sets done_at.
CREATE TABLE IF NOT EXISTS audit.deferred_requests (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    action     text NOT NULL CHECK (action IN ('dispatch', 'triage-post', 'quarantine', 'jira-write')),
    workflow   text NOT NULL DEFAULT '',
    target     text NOT NULL DEFAULT '',
    payload    jsonb NOT NULL DEFAULT '{}',
    reason     text NOT NULL CHECK (reason IN ('disabled', 'capped', 'caps-invalid')),
    not_before timestamptz NOT NULL,
    done_at    timestamptz
);
-- One open request per (action, workflow, target): asking again only updates it.
CREATE UNIQUE INDEX IF NOT EXISTS deferred_requests_open
    ON audit.deferred_requests (action, workflow, target) WHERE done_at IS NULL;
REVOKE ALL ON audit.deferred_requests FROM PUBLIC, audit_writer;
GRANT SELECT, INSERT, UPDATE ON audit.deferred_requests TO audit_writer;

-- W1 ticket watcher (Story 5.5): one record per (ticket, workflow), so a ticket
-- is never started twice. state: dispatched (run started), deferred (the gate
-- kept it on the waiting list), blocked (the run ended blocked; retried later),
-- done (its PR or run-outcome was seen). Not audit entries, so updatable.
CREATE TABLE IF NOT EXISTS audit.w1_requests (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket        text NOT NULL CHECK (ticket ~ '^[A-Z][A-Z0-9]+-[0-9]+$'),
    workflow      text NOT NULL CHECK (workflow IN ('draft-cases', 'generate-tests')),
    state         text NOT NULL CHECK (state IN ('dispatched', 'deferred', 'blocked', 'done')),
    dispatched_at timestamptz,
    run_id        bigint,
    pr_url        text NOT NULL DEFAULT '',
    attempts      integer NOT NULL DEFAULT 1,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ticket, workflow)
);
REVOKE ALL ON audit.w1_requests FROM PUBLIC, audit_writer;
GRANT SELECT, INSERT, UPDATE ON audit.w1_requests TO audit_writer;

-- W1 follow-up (Story 5.5, part 2): the masked text to start a request again,
-- why it is blocked, which notice was last posted for it (so each goes out
-- once), and the `failed` state after 3 tries. A retry goes back on the
-- waiting list with reason `retry`.
ALTER TABLE audit.w1_requests ADD COLUMN IF NOT EXISTS ticket_text text NOT NULL DEFAULT '';
ALTER TABLE audit.w1_requests ADD COLUMN IF NOT EXISTS reason text NOT NULL DEFAULT '';
ALTER TABLE audit.w1_requests ADD COLUMN IF NOT EXISTS notified text NOT NULL DEFAULT '';
ALTER TABLE audit.w1_requests DROP CONSTRAINT IF EXISTS w1_requests_state_check;
ALTER TABLE audit.w1_requests ADD CONSTRAINT w1_requests_state_check
    CHECK (state IN ('dispatched', 'deferred', 'blocked', 'done', 'failed'));
ALTER TABLE audit.deferred_requests DROP CONSTRAINT IF EXISTS deferred_requests_reason_check;
ALTER TABLE audit.deferred_requests ADD CONSTRAINT deferred_requests_reason_check
    CHECK (reason IN ('disabled', 'capped', 'caps-invalid', 'retry'));

-- Triage requests (Story 6.3): one per nightly run. W2 starts triage
-- (dispatched) or the gate keeps it back (deferred); W3 posts the result
-- (posted) or the fallback when triage didn't run (fallback).
CREATE TABLE IF NOT EXISTS audit.triage_requests (
    nightly_run_id bigint PRIMARY KEY,
    state          text NOT NULL CHECK (state IN ('dispatched', 'deferred', 'posted', 'fallback')),
    dispatched_at  timestamptz,
    triage_run_id  bigint,
    reason         text NOT NULL DEFAULT '',
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON audit.triage_requests FROM PUBLIC, audit_writer;
GRANT SELECT, INSERT, UPDATE ON audit.triage_requests TO audit_writer;

-- Slack messages people react to (Story 6.3 onwards): which message is about
-- which test, so W3b knows what a reaction means. kind: failure or questions.
CREATE TABLE IF NOT EXISTS audit.message_map (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    channel        text NOT NULL,
    ts             text NOT NULL,
    kind           text NOT NULL CHECK (kind IN ('failure', 'questions')),
    test_id        text NOT NULL DEFAULT '',
    ticket         text NOT NULL DEFAULT '',
    nightly_run_id bigint,
    class          text NOT NULL DEFAULT '',
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (channel, ts)
);
REVOKE ALL ON audit.message_map FROM PUBLIC, audit_writer;
GRANT SELECT, INSERT ON audit.message_map TO audit_writer;
-- What W3 already posted for a nightly run ("s3", "test:<test_id>"), so a retry
-- after a Slack failure never posts the same message twice.
ALTER TABLE audit.triage_requests ADD COLUMN IF NOT EXISTS posted jsonb NOT NULL DEFAULT '[]';

-- W6 questions poster (Story 6.7): each draft-cases run is handled once.
-- state: posted (or preview while Slack isn't set up), none (no questions),
-- invalid (the questions file broke its contract; W0 alerted).
CREATE TABLE IF NOT EXISTS audit.w6_runs (
    run_id     bigint PRIMARY KEY,
    ticket     text NOT NULL DEFAULT '',
    state      text NOT NULL CHECK (state IN ('posted', 'preview', 'none', 'invalid')),
    created_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON audit.w6_runs FROM PUBLIC, audit_writer;
GRANT SELECT, INSERT ON audit.w6_runs TO audit_writer;

-- The run a mapped message came from (the draft-cases run for `questions`).
ALTER TABLE audit.message_map ADD COLUMN IF NOT EXISTS source_run_id bigint;
-- Posting clarification questions is a gated action too (Story 6.7).
ALTER TABLE audit.deferred_requests DROP CONSTRAINT IF EXISTS deferred_requests_action_check;
ALTER TABLE audit.deferred_requests ADD CONSTRAINT deferred_requests_action_check
    CHECK (action IN ('dispatch', 'triage-post', 'questions-post', 'quarantine', 'jira-write'));

-- W3b reactions (Story 6.4): the thread a mapped message is in (for reason
-- replies), and one decision per handled reaction. A decision is never
-- deleted: undo (Story 6.8) sets undone_at. state: handled, or
-- waiting-for-reason (🙈 before its reason reply arrives).
ALTER TABLE audit.message_map ADD COLUMN IF NOT EXISTS thread_ts text NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS audit.reaction_decisions (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    map_id       bigint NOT NULL REFERENCES audit.message_map (id),
    action       text NOT NULL CHECK (action IN ('bug', 'flaky', 'environment', 'ignore', 'approve')),
    state        text NOT NULL CHECK (state IN ('handled', 'waiting-for-reason')),
    actor_id     text NOT NULL,
    actor_email  text NOT NULL DEFAULT '',
    actor_name   text NOT NULL DEFAULT '',
    reason       text NOT NULL DEFAULT '',
    jira_key     text NOT NULL DEFAULT '',
    link         text NOT NULL DEFAULT '',
    prompt_ts    text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    handled_at   timestamptz,
    undone_at    timestamptz
);
-- At most one live (not undone) decision per message.
CREATE UNIQUE INDEX IF NOT EXISTS reaction_decisions_live ON audit.reaction_decisions (map_id) WHERE undone_at IS NULL;
REVOKE ALL ON audit.reaction_decisions FROM PUBLIC, audit_writer;
GRANT SELECT, INSERT, UPDATE ON audit.reaction_decisions TO audit_writer;
-- For 🐞 (Story 6.4): the failure's flow and the drafted bug title, from W3.
ALTER TABLE audit.message_map ADD COLUMN IF NOT EXISTS flow_id text NOT NULL DEFAULT '';
ALTER TABLE audit.message_map ADD COLUMN IF NOT EXISTS bug_title text NOT NULL DEFAULT '';

-- Undo (Story 6.8): who undid a decision, and whether the "undo is closed"
-- reply was already posted for it. Nothing is deleted.
ALTER TABLE audit.reaction_decisions ADD COLUMN IF NOT EXISTS undone_by text NOT NULL DEFAULT '';
ALTER TABLE audit.reaction_decisions ADD COLUMN IF NOT EXISTS undo_closed_noted boolean NOT NULL DEFAULT false;

-- Plain mode (W2 `triage_mode`, 5 Oct 2026): no AI triage in GitHub. W2 records
-- a failed night as `plain`, and W3 posts one "Not classified" message per
-- failure for it, without the gate.
ALTER TABLE audit.triage_requests DROP CONSTRAINT IF EXISTS triage_requests_state_check;
ALTER TABLE audit.triage_requests ADD CONSTRAINT triage_requests_state_check
    CHECK (state IN ('dispatched', 'deferred', 'plain', 'posted', 'fallback'));
