"""Alembic environment: the URL and schema come from `glassdesk.db.run_migrations`."""

from alembic import context
from sqlalchemy import create_engine, text

cfg = context.config
url: str = cfg.attributes["url"]
schema: str = cfg.attributes["schema"]

engine = create_engine(url)
with engine.begin() as conn:
    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    conn.execute(text(f'SET search_path TO "{schema}"'))
    context.configure(connection=conn, version_table_schema=schema)
    context.run_migrations()
engine.dispose()
