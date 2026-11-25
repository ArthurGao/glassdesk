"""PostgreSQL fixtures. Tests run against GLASSDESK_TEST_DATABASE_URL (env or backend/.env), only in
schemas TEST_SCHEMA and TEST_AGENT_SCHEMA, which every test drops and recreates. The app's Settings
refuse *_test schema names, so no app process can hold data in a schema the tests drop."""

from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from lite_agent.pg import PgSessionStore
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from glassdesk.app import create_app
from glassdesk.config import Settings
from glassdesk.db import Deps, make_engine, run_migrations
from glassdesk.testing import FakeSteward
from tests.helpers import P1

TEST_SCHEMA = "glassdesk_test"
TEST_AGENT_SCHEMA = "lite_agent_test"


class _TestTarget(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str | None = Field(default=None, validation_alias="GLASSDESK_TEST_DATABASE_URL")


def _test_url() -> str:
    url = _TestTarget().database_url
    if not url:
        pytest.fail("PostgreSQL tests need GLASSDESK_TEST_DATABASE_URL (env or backend/.env)")
    return url


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=_test_url(),
        steward_api_key="stw_test_key",  # type: ignore[arg-type]
        session_secret="s" * 32,  # type: ignore[arg-type]
        brand_name="Acme",
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = _test_url()
    eng = make_engine(url, TEST_SCHEMA)
    async with eng.begin() as conn:
        for schema in (TEST_SCHEMA, TEST_AGENT_SCHEMA):
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await run_migrations(url, TEST_SCHEMA, TEST_AGENT_SCHEMA)
    yield eng
    await eng.dispose()


@pytest.fixture
def deps(engine: AsyncEngine) -> Deps:
    return Deps(engine=engine)


@pytest.fixture
async def sessions() -> AsyncIterator[PgSessionStore]:
    store = PgSessionStore(_test_url().replace("+psycopg", ""), schema=TEST_AGENT_SCHEMA)
    yield store
    await store.close()


@pytest.fixture
def make_app(
    settings: Settings, engine: AsyncEngine, sessions: PgSessionStore
) -> Callable[..., FastAPI]:
    def make(model: object, steward: FakeSteward | None = None) -> FastAPI:
        deps = Deps(
            engine=engine,
            model=model,
            sessions=sessions,  # type: ignore[arg-type]
            steward=steward or FakeSteward([P1]),
        )
        return create_app(settings, deps=deps)

    return make
