CREATE TABLE IF NOT EXISTS applications (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    draft jsonb NOT NULL,
    generation integer NOT NULL DEFAULT 1,
    archived boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS revisions (
    id uuid PRIMARY KEY,
    app_id uuid NOT NULL REFERENCES applications(id),
    generation integer NOT NULL,
    graph jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (app_id, generation)
);

CREATE TABLE IF NOT EXISTS routes (
    name text PRIMARY KEY,
    revision_id uuid REFERENCES revisions(id)
);

CREATE TABLE IF NOT EXISTS settings (
    name text PRIMARY KEY,
    value jsonb NOT NULL,
    generation integer NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    happened_at timestamptz NOT NULL DEFAULT now(),
    action text NOT NULL,
    scope text NOT NULL
);

INSERT INTO routes(name) VALUES ('infoline') ON CONFLICT DO NOTHING;
