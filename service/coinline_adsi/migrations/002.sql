CREATE TABLE IF NOT EXISTS bank_links (
    subject text PRIMARY KEY,
    phone_key text NOT NULL UNIQUE,
    alias text NOT NULL,
    sealed bytea NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);
