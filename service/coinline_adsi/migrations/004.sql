CREATE TABLE IF NOT EXISTS bank_pending (
    subject text PRIMARY KEY,
    claim_id uuid NOT NULL,
    access_sealed bytea,
    choices_sealed bytea,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bank_reads (
    subject text NOT NULL,
    scope text NOT NULL,
    day date NOT NULL,
    used integer NOT NULL CHECK (used BETWEEN 1 AND 24),
    PRIMARY KEY (subject, scope, day)
);
