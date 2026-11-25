"""Database engine, migrations and the dependencies the app runs on."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from lite_agent import SessionStore
from lite_agent.pg.db import migrate as migrate_agent_schema
from lite_model import AsyncToolModel
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from glassdesk.steward import StewardPort

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def sync_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def make_engine(url: str, schema: str) -> AsyncEngine:
    """An engine whose connections resolve unqualified table names in `schema`."""
    return create_async_engine(url, connect_args={"options": f"-csearch_path={schema}"})


@dataclass(frozen=True)
class Deps:
    """What the app runs on; tests pass their own, `create_app` builds it from settings."""

    engine: AsyncEngine
    model: AsyncToolModel | None = None  # None: no model configured; asking answers 503
    sessions: SessionStore | None = None  # lite-agent's event log
    steward: StewardPort | None = None


def _migrate(url: str, schema: str, agent_schema: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["url"] = url
    cfg.attributes["schema"] = schema
    command.upgrade(cfg, "head")
    with psycopg.connect(sync_url(url), autocommit=True) as conn:
        migrate_agent_schema(conn, agent_schema)


async def run_migrations(url: str, schema: str, agent_schema: str) -> None:
    """Alembic for the app's tables in `schema`, lite-agent's own migrations in `agent_schema`."""
    await asyncio.to_thread(_migrate, url, schema, agent_schema)
