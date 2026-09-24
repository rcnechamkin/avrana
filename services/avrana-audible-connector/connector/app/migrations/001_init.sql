-- Ownership map + per-book state. Everything is scoped by authentik_sub so one user
-- can never reach another user's catalog.

-- One row per connected Audible account, owned by exactly one Authentik subject.
CREATE TABLE connection (
    id            TEXT PRIMARY KEY,          -- uuid4
    authentik_sub TEXT NOT NULL,             -- Authentik subject (stable user id)
    profile_id    TEXT NOT NULL UNIQUE,      -- companion Libation profile dir id
    audible_email TEXT NOT NULL,             -- account reference (not a secret)
    marketplace   TEXT NOT NULL,
    sync_mode     TEXT NOT NULL DEFAULT 'once',   -- once | ask | auto
    state         TEXT NOT NULL DEFAULT 'connecting', -- connecting|connected|disconnected|error
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_scan_at  TEXT,
    failure       TEXT,                      -- sanitized, human-readable; never secrets
    UNIQUE (authentik_sub, audible_email)
);
CREATE INDEX idx_connection_sub ON connection(authentik_sub);

-- Pending browser auth handshakes. The pasted response URL is NEVER stored here or
-- anywhere: it is forwarded to the companion and discarded. We keep only the sessionId.
CREATE TABLE auth_session (
    id            TEXT PRIMARY KEY,          -- our session id
    authentik_sub TEXT NOT NULL,
    connection_id TEXT NOT NULL REFERENCES connection(id) ON DELETE CASCADE,
    companion_session TEXT NOT NULL,         -- opaque id returned by companion
    expires_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_auth_session_sub ON auth_session(authentik_sub);

-- One row per ASIN discovered for a connection. ASIN is the identity/dedup key.
CREATE TABLE book (
    connection_id TEXT NOT NULL REFERENCES connection(id) ON DELETE CASCADE,
    asin          TEXT NOT NULL,
    title         TEXT,
    author        TEXT,
    narrator      TEXT,
    runtime_min   INTEGER,
    cover_url     TEXT,
    -- eligibility: purchased | plus | ineligible
    eligibility   TEXT NOT NULL DEFAULT 'ineligible',
    -- lifecycle: available|already|selected|queued|importing|imported|failed|excluded|pending|review
    status        TEXT NOT NULL DEFAULT 'available',
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (connection_id, asin)
);
CREATE INDEX idx_book_status ON book(connection_id, status);

-- One row per import job. Idempotent creation: a UNIQUE key on (connection_id, asin)
-- for non-terminal jobs prevents a refresh from creating duplicate active jobs.
CREATE TABLE job (
    id            TEXT PRIMARY KEY,          -- uuid4 (our id)
    connection_id TEXT NOT NULL REFERENCES connection(id) ON DELETE CASCADE,
    asin          TEXT NOT NULL,
    companion_job TEXT,                      -- companion's job id once created
    status        TEXT NOT NULL DEFAULT 'queued', -- queued|running|succeeded|failed
    attempts      INTEGER NOT NULL DEFAULT 0,
    failure       TEXT,                      -- sanitized
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
-- At most one active (non-terminal) job per book. Partial unique index = the dedup lock.
CREATE UNIQUE INDEX idx_job_active ON job(connection_id, asin)
    WHERE status IN ('queued', 'running');

-- Append-only audit trail. Never contains secrets or the response URL.
CREATE TABLE audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT NOT NULL DEFAULT (datetime('now')),
    authentik_sub TEXT,
    connection_id TEXT,
    event         TEXT NOT NULL,
    detail        TEXT
);
CREATE INDEX idx_audit_sub ON audit(authentik_sub, at);
