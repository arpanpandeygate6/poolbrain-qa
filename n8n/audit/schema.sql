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
