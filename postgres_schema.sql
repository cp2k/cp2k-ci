CREATE TYPE job_state_enum AS ENUM (
    'NEW',
    'QUEUING',
    'RUNNING',
    'CANCELING',
    'CANCELED',
    'SUCCEEDED', -- deprecated
    'FAILED', -- deprecated
    'OUT_OF_MEMORY', -- deprecated
    'TIMEOUT', -- deprecated
    'PREEMPTED',
    'CI_ERROR',
    'DONE',
    );

CREATE TABLE jobs (
    jobid INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name VARCHAR(100) NOT NULL UNIQUE,
    state job_state_enum NOT NULL DEFAULT 'NEW',
    spec JSONB NOT NULL,
    annotations JSONB NOT NULL,
    priority BOOLEAN NOT NULL,
    offloadable BOOLEAN NOT NULL,
    nodepool VARCHAR(100) NOT NULL,
    worker VARCHAR(100),
    created TIMESTAMPTZ NOT NULL DEFAULT now(),
    started TIMESTAMPTZ,
    finished TIMESTAMPTZ,
    heartbeat TIMESTAMPTZ
);

GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO cloudsqlsuperuser;
GRANT ALL PRIVILEGES ON SCHEMA public TO cloudsqlsuperuser;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO cloudsqlsuperuser;
GRANT ALL ON SCHEMA public TO cloudsqlsuperuser;

-- EOF
