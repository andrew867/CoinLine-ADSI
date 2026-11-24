#!/bin/sh
set -eu
psql -X --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv application_password ADSI_DATABASE_PASSWORD
CREATE ROLE coinline LOGIN PASSWORD :'application_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER DATABASE coinline OWNER TO coinline;
SQL
