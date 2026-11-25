"""The FastAPI application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute

from glassdesk import auth
from glassdesk.config import Settings
from glassdesk.db import Deps, make_engine


def _operation_id(route: APIRoute) -> str:
    return route.name


def build_deps(settings: Settings) -> Deps:
    return Deps(engine=make_engine(settings.database_url, settings.db_schema))


def create_app(settings: Settings, *, deps: Deps | None = None) -> FastAPI:
    owned = deps is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if owned:
            await app.state.deps.engine.dispose()

    app = FastAPI(
        title="glassdesk",
        version="0.1.0",
        lifespan=lifespan,
        # operationId = the handler's name, so the generated TS client reads `login`, `me`, …
        generate_unique_id_function=_operation_id,
    )
    app.state.settings = settings
    app.state.deps = deps if deps is not None else build_deps(settings)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    return app
