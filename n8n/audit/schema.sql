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
