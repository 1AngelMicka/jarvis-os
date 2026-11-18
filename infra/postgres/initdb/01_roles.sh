#!/bin/sh
# Premier démarrage de la base : crée le rôle applicatif, distinct du propriétaire.
# Le propriétaire (POSTGRES_USER) ne sert qu'aux migrations ; le Core tourne avec jarvis2_app,
# qui n'a aucun droit sur la structure (pas de CREATE, ALTER, DROP, TRUNCATE).
# Crée aussi la base de test jarvis2_test (pytest), avec les mêmes rôles.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v mdp="$JARVIS2_APP_MOT_DE_PASSE" <<'SQL'
CREATE ROLE jarvis2_app LOGIN PASSWORD :'mdp' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
SQL

for base in "$POSTGRES_DB" jarvis2_test; do
  if [ "$base" != "$POSTGRES_DB" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
         -c "CREATE DATABASE $base OWNER \"$POSTGRES_USER\""
  fi
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$base" <<SQL
REVOKE ALL ON DATABASE "$base" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE "$base" TO jarvis2_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO jarvis2_app;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
SQL
done
