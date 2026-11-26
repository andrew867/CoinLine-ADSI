CREATE TABLE IF NOT EXISTS shadybank_pin_attempts (
    card_key bytea PRIMARY KEY CHECK (octet_length(card_key) = 32),
    attempts smallint NOT NULL CHECK (attempts BETWEEN 1 AND 3),
    expires_at timestamptz NOT NULL,
    reservation uuid NOT NULL
);

CREATE INDEX IF NOT EXISTS shadybank_pin_attempts_expiry_idx ON shadybank_pin_attempts(expires_at);
