#!/bin/sh
# First start of the database volume only: one role and database per service, each the owner of
# its database (lite-mem, lite-rag and glassdesk create their extensions and schemas there).
set -eu
psql -v ON_ERROR_STOP=1 --username postgres <<SQL
CREATE ROLE glassdesk LOGIN PASSWORD '${GLASSDESK_DB_PASSWORD}';
CREATE DATABASE glassdesk OWNER glassdesk;
CREATE ROLE steward LOGIN PASSWORD '${STEWARD_DB_PASSWORD}';
CREATE DATABASE steward OWNER steward;
CREATE ROLE lite_rag LOGIN PASSWORD '${LITERAG_DB_PASSWORD}';
CREATE DATABASE lite_rag OWNER lite_rag;
SQL
# pgvector needs a superuser to create; the services only use it
for db in steward lite_rag; do
  psql -v ON_ERROR_STOP=1 --username postgres --dbname "$db" -c "CREATE EXTENSION IF NOT EXISTS vector"
done
